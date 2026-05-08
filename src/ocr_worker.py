"""后台 OCR Worker，异步执行 OCR 任务（串行队列，避免 GPU 资源竞争）。"""

import asyncio
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from src.config import AppConfig
from src.exceptions import UnsupportedFormatError
from src.job_store import JobStore
from src.mineru_runner import MinerURunner
from src.s3_reader import S3Reader
from src.s3_writer import S3Writer, build_target_key

# 全局串行队列：同一时刻只允许一个 OCR 任务运行，避免 GPU 资源竞争
_ocr_semaphore = asyncio.Semaphore(1)


async def run_ocr_job(
    job_id: str,
    file_key: str,
    config: AppConfig,
    job_store: JobStore,
) -> None:
    """在后台线程中执行 OCR 处理，并更新 Job 状态。串行执行，避免 GPU 资源竞争。"""
    # 等待获取串行锁，确保同一时刻只有一个 OCR 任务运行
    async with _ocr_semaphore:
        started_at = datetime.utcnow().isoformat() + "Z"
        await job_store.update_job(job_id, status="running", started_at=started_at)

        # 读取 job 里存储的语言设置
        job_record = await job_store.get_job(job_id)
        job_lang = job_record.lang if job_record else None

        tmp_dir = tempfile.mkdtemp()
        try:
            local_filename = Path(file_key).name
            local_path = Path(tmp_dir) / local_filename

            reader = S3Reader(bucket=config.source_bucket, region=config.aws_region)
            reader.download_file(file_key, local_path)

            # 使用 job 里存储的语言设置，回退到 config 默认值
            lang = job_lang or config.mineru_lang
            runner = MinerURunner(backend=config.mineru_backend, lang=lang)
            loop = asyncio.get_event_loop()
            work_dir = Path(tmp_dir) / "work"
            work_dir.mkdir(exist_ok=True)
            ocr_result = await loop.run_in_executor(
                None, runner.run, local_path, work_dir
            )

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

        except UnsupportedFormatError as e:
            completed_at = datetime.utcnow().isoformat() + "Z"
            await job_store.update_job(
                job_id,
                status="skipped",
                error=str(e),
                completed_at=completed_at,
            )

        except Exception as e:  # noqa: BLE001
            completed_at = datetime.utcnow().isoformat() + "Z"
            await job_store.update_job(
                job_id,
                status="failed",
                error=str(e),
                completed_at=completed_at,
            )

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
