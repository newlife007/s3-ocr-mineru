"""后台 OCR Worker，异步执行 OCR 任务（串行队列，避免 GPU 资源竞争）。"""

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.config import AppConfig
from src.exceptions import UnsupportedFormatError
from src.job_store import JobStore
from src.logger import StructuredLogger
from src.mineru_runner import MinerURunner
from src.s3_reader import S3Reader
from src.s3_writer import S3Writer, build_target_key

# 全局串行队列：同一时刻只允许一个 OCR 任务运行，避免 GPU 资源竞争
_ocr_semaphore = asyncio.Semaphore(1)

# 创建 logger
logger = StructuredLogger("ocr_worker")

# 全局监控任务
_monitor_task: Optional[asyncio.Task] = None


async def _monitor_stuck_jobs(job_store: JobStore, check_interval: int = 300, max_hours: float = 2.0) -> None:
    """
    后台监控任务，定期检查并清理卡住的任务
    
    Args:
        job_store: 任务存储
        check_interval: 检查间隔（秒），默认5分钟
        max_hours: 任务运行超过多少小时视为卡住，默认2小时
    """
    logger.info("Starting stuck job monitor", check_interval=check_interval, max_hours=max_hours)
    
    while True:
        try:
            await asyncio.sleep(check_interval)
            
            # 查找状态为 running 的任务
            running_jobs = await job_store.list_pending_and_running()
            running_jobs = [j for j in running_jobs if j.status == "running"]
            
            if not running_jobs:
                continue
            
            now = datetime.now(timezone.utc)
            max_duration = timedelta(hours=max_hours)
            
            for job in running_jobs:
                if not job.started_at:
                    # 没有 started_at 的任务肯定有问题
                    logger.warning("Found running job without started_at", job_id=job.job_id)
                    completed_at = now.isoformat().replace("+00:00", "Z")
                    await job_store.update_job(
                        job.job_id,
                        status="failed",
                        error="Task stuck: no started_at timestamp",
                        completed_at=completed_at,
                    )
                    continue
                
                try:
                    # 解析 ISO 格式时间
                    started_time = datetime.fromisoformat(job.started_at.replace("Z", "+00:00"))
                    duration = now - started_time
                    
                    if duration > max_duration:
                        duration_hours = duration.total_seconds() / 3600
                        logger.warning(
                            "Found stuck job",
                            job_id=job.job_id,
                            file_key=job.file_key,
                            duration_hours=f"{duration_hours:.1f}",
                        )
                        
                        completed_at = now.isoformat().replace("+00:00", "Z")
                        await job_store.update_job(
                            job.job_id,
                            status="failed",
                            error=f"Task stuck for more than {max_hours} hours, automatically marked as failed",
                            completed_at=completed_at,
                        )
                        
                        logger.info("Marked stuck job as failed", job_id=job.job_id)
                        
                except Exception as e:
                    logger.error("Error checking job duration", job_id=job.job_id, error=str(e))
                    
        except asyncio.CancelledError:
            logger.info("Stuck job monitor cancelled")
            break
        except Exception as e:
            logger.error("Error in stuck job monitor", error=str(e), exc_info=True)
            # 继续运行，不要因为一次错误就停止监控


def start_monitor(job_store: JobStore, check_interval: int = 300, max_hours: float = 2.0) -> None:
    """启动后台监控任务"""
    global _monitor_task
    
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(
            _monitor_stuck_jobs(job_store, check_interval, max_hours)
        )
        logger.info("Stuck job monitor started")


def stop_monitor() -> None:
    """停止后台监控任务"""
    global _monitor_task
    
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        logger.info("Stuck job monitor stopped")


async def run_ocr_job(
    job_id: str,
    file_key: str,
    config: AppConfig,
    job_store: JobStore,
) -> None:
    """在后台线程中执行 OCR 处理，并更新 Job 状态。串行执行，避免 GPU 资源竞争。"""
    try:
        # 等待获取串行锁，确保同一时刻只有一个 OCR 任务运行
        async with _ocr_semaphore:
            logger.info("Starting OCR job", job_id=job_id, file_key=file_key)
            started_at = datetime.utcnow().isoformat() + "Z"
            await job_store.update_job(job_id, status="running", started_at=started_at)

            # 读取 job 里存储的语言设置和阿拉伯语修复模式
            job_record = await job_store.get_job(job_id)
            job_lang = job_record.lang if job_record else None
            job_arabic_bidi_fix = job_record.arabic_bidi_fix if job_record else None
            job_backend = job_record.backend if job_record else None

            tmp_dir = tempfile.mkdtemp()
            try:
                local_filename = Path(file_key).name
                local_path = Path(tmp_dir) / local_filename

                logger.info("Downloading file from S3", job_id=job_id, file_key=file_key)
                reader = S3Reader(bucket=config.source_bucket, region=config.aws_region)
                reader.download_file(file_key, local_path)

                # 使用 job 里存储的设置，回退到 config 默认值
                lang = job_lang or config.mineru_lang
                arabic_bidi_fix = job_arabic_bidi_fix or config.arabic_bidi_fix
                backend = job_backend or config.mineru_backend
                logger.info("Running OCR", job_id=job_id, lang=lang, backend=backend, arabic_bidi_fix=arabic_bidi_fix)
                runner = MinerURunner(
                    backend=backend, 
                    lang=lang,
                    arabic_bidi_fix=arabic_bidi_fix,
                    arabic_post_process=True  # 默认启用阿拉伯语后处理
                )
                work_dir = Path(tmp_dir) / "work"
                work_dir.mkdir(exist_ok=True)
                
                # 直接使用异步方法，不需要 run_in_executor
                logger.info("Calling run_async", job_id=job_id)
                ocr_result = await runner.run_async(local_path, work_dir)
                logger.info("run_async completed", job_id=job_id)

                logger.info("OCR completed, uploading results", job_id=job_id, page_count=ocr_result.page_count)
                target_key = build_target_key(
                    file_key, config.source_prefix, config.target_prefix
                )
                # target_key 形如 "ZHGW/report.md"，图片上传到同级目录
                target_prefix = target_key[:-3]  # 去掉 .md 后缀，作为图片目录前缀

                writer = S3Writer(bucket=config.target_bucket, region=config.aws_region)
                writer.upload(ocr_result.md_content, target_key)

                # 上传图片到 S3（与 Markdown 同级的 images/ 目录）
                if ocr_result.images_dir.exists():
                    writer.upload_images(ocr_result.images_dir, target_prefix)

                completed_at = datetime.utcnow().isoformat() + "Z"
                await job_store.update_job(
                    job_id,
                    status="success",
                    page_count=ocr_result.page_count,
                    target_key=target_key,
                    completed_at=completed_at,
                )
                logger.info("OCR job completed successfully", job_id=job_id, file_key=file_key)

            except UnsupportedFormatError as e:
                logger.warning("Unsupported format", job_id=job_id, file_key=file_key, error=str(e))
                completed_at = datetime.utcnow().isoformat() + "Z"
                await job_store.update_job(
                    job_id,
                    status="skipped",
                    error=str(e),
                    completed_at=completed_at,
                )

            except Exception as e:  # noqa: BLE001
                logger.error("OCR job failed", job_id=job_id, file_key=file_key, error=str(e), exc_info=True)
                completed_at = datetime.utcnow().isoformat() + "Z"
                await job_store.update_job(
                    job_id,
                    status="failed",
                    error=str(e),
                    completed_at=completed_at,
                )

            finally:
                logger.info("Cleaning up temporary files", job_id=job_id, tmp_dir=tmp_dir)
                shutil.rmtree(tmp_dir, ignore_errors=True)
                
    except Exception as e:
        # 捕获信号量外的异常，确保不会静默失败
        logger.error("Fatal error in run_ocr_job", job_id=job_id, error=str(e), exc_info=True)
        try:
            completed_at = datetime.utcnow().isoformat() + "Z"
            await job_store.update_job(
                job_id,
                status="failed",
                error=f"Fatal error: {str(e)}",
                completed_at=completed_at,
            )
        except Exception:
            pass  # 如果连更新状态都失败了，就放弃
