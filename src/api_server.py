"""FastAPI API Server for s3-ocr-mineru Web UI."""

from __future__ import annotations

import io
import os
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import asyncio
import boto3
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import AppConfig, ConfigLoader
from src.exceptions import S3AccessError
from src.job_store import JobStore
from src.logger import StructuredLogger
from src.mineru_runner import SUPPORTED_EXTENSIONS
from src.ocr_worker import run_ocr_job
from src.s3_reader import S3Reader

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class JobResponse(BaseModel):
    job_id: str
    file_key: str
    file_size: int
    status: str
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    page_count: Optional[int] = None
    error: Optional[str] = None


class ConfigResponse(BaseModel):
    source_bucket: str
    target_bucket: str
    aws_region: str
    source_prefix: str
    target_prefix: str
    mineru_lang: str
    mineru_backend: str


class SubmitRequest(BaseModel):
    file_keys: list[str]
    lang: Optional[str] = None  # 若为 None 则使用 config 默认值


class SubmitResponse(BaseModel):
    jobs: list[dict]


class DeleteRequest(BaseModel):
    job_ids: list[str]


class DownloadRequest(BaseModel):
    job_ids: list[str]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
_STATIC_DIR = _PROJECT_ROOT / "static"
_CONFIG_FILE = _PROJECT_ROOT / os.environ.get("CONFIG_FILE", "config.yaml")

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger = StructuredLogger("api_server")

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    config = ConfigLoader().load(str(_CONFIG_FILE))
    job_store = JobStore(db_path=str(_PROJECT_ROOT / "jobs.db"))
    await job_store.init_db()

    app.state.config = config
    app.state.job_store = job_store

    # 恢复上次未完成的任务（pending / running → 重新入队）
    unfinished = await job_store.list_pending_and_running()
    if unfinished:
        logger.info("Resuming unfinished jobs on startup", count=len(unfinished))
        for job in unfinished:
            # running 状态说明上次进程中途退出，重置为 pending 再重跑
            if job.status == "running":
                await job_store.update_job(job.job_id, status="pending")
            asyncio.create_task(run_ocr_job(job.job_id, job.file_key, config, job_store))

    yield

    await job_store.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", exc_info=True, path=str(request.url))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# 5.2 Basic endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config", response_model=ConfigResponse)
async def get_config(request: Request):
    config: AppConfig = request.app.state.config
    return ConfigResponse(
        source_bucket=config.source_bucket,
        target_bucket=config.target_bucket,
        aws_region=config.aws_region,
        source_prefix=config.source_prefix,
        target_prefix=config.target_prefix,
        mineru_lang=config.mineru_lang,
        mineru_backend=config.mineru_backend,
    )


# ---------------------------------------------------------------------------
# 5.3 File listing
# ---------------------------------------------------------------------------

@app.get("/api/files")
async def list_files(request: Request, show_all: bool = False):
    config: AppConfig = request.app.state.config
    job_store: JobStore = request.app.state.job_store
    reader = S3Reader(bucket=config.source_bucket, region=config.aws_region)
    try:
        files = reader.list_files(config.source_prefix)
    except S3AccessError as e:
        raise HTTPException(status_code=503, detail=f"S3 service unavailable: {e}") from e

    # 查出所有已有任务的 file_key，取每个 key 的最新任务状态
    all_jobs = await job_store.list_jobs()
    key_status: dict[str, str] = {}
    key_job_id: dict[str, str] = {}
    for job in reversed(all_jobs):  # reversed → 最旧到最新，后覆盖前，保留最新
        key_status[job.file_key] = job.status
        key_job_id[job.file_key] = job.job_id

    result = []
    for f in files:
        job_status = key_status.get(f.key)
        has_job = job_status is not None
        if not show_all and has_job:
            continue
        result.append({
            "key": f.key,
            "size": f.size,
            "job_status": job_status,
            "job_id": key_job_id.get(f.key),
        })

    return result


# ---------------------------------------------------------------------------
# 5.4 Job submission
# ---------------------------------------------------------------------------

@app.post("/api/jobs", status_code=202, response_model=SubmitResponse)
async def submit_jobs(body: SubmitRequest, request: Request):
    config: AppConfig = request.app.state.config
    job_store: JobStore = request.app.state.job_store

    created_jobs = []

    for file_key in body.file_keys:
        ext = Path(file_key).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")

        running = await job_store.get_running_job_for_key(file_key)
        if running:
            raise HTTPException(status_code=409, detail=f"Job already running for: {file_key}")

        job_id = str(uuid.uuid4())
        submitted_at = datetime.utcnow().isoformat() + "Z"

        # Try to get file size from S3
        file_size = 0
        try:
            reader = S3Reader(bucket=config.source_bucket, region=config.aws_region)
            files = reader.list_files(prefix=file_key)
            for f in files:
                if f.key == file_key:
                    file_size = f.size
                    break
        except S3AccessError:
            pass

        await job_store.create_job(
            job_id=job_id,
            file_key=file_key,
            file_size=file_size,
            submitted_at=submitted_at,
            lang=body.lang or config.mineru_lang,
        )

        asyncio.create_task(run_ocr_job(job_id, file_key, config, job_store))

        created_jobs.append({"job_id": job_id, "file_key": file_key})

    return SubmitResponse(jobs=created_jobs)


# ---------------------------------------------------------------------------
# 5.5 Job queries
# ---------------------------------------------------------------------------

@app.get("/api/jobs", response_model=list[JobResponse])
async def list_jobs(request: Request):
    job_store: JobStore = request.app.state.job_store
    jobs = await job_store.list_jobs()
    result = []
    for j in jobs:
        d = {k: getattr(j, k) for k in JobResponse.model_fields}
        # 截断过长的 error 字段，避免前端渲染卡顿
        if d.get("error") and len(d["error"]) > 300:
            d["error"] = d["error"][:300] + "…"
        result.append(JobResponse(**d))
    return result


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request):
    job_store: JobStore = request.app.state.job_store
    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobResponse(**{k: getattr(job, k) for k in JobResponse.model_fields})


# ---------------------------------------------------------------------------
# 5.6 Comparison view
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}/source")
async def get_source_url(job_id: str, request: Request):
    config: AppConfig = request.app.state.config
    job_store: JobStore = request.app.state.job_store

    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    reader = S3Reader(bucket=config.source_bucket, region=config.aws_region)
    url = reader.generate_presigned_url(job.file_key, expires_in=900)
    return {"url": url}


@app.get("/api/jobs/{job_id}/result")
async def get_result(job_id: str, request: Request):
    config: AppConfig = request.app.state.config
    job_store: JobStore = request.app.state.job_store

    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if not job.target_key:
        raise HTTPException(status_code=404, detail="Result file not found")

    s3_client = boto3.client("s3", region_name=config.aws_region)
    try:
        response = s3_client.get_object(Bucket=config.target_bucket, Key=job.target_key)
        content = response["Body"].read().decode("utf-8")
    except s3_client.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="Result file not found")
    except Exception as e:
        raise HTTPException(status_code=404, detail="Result file not found") from e

    # 将 Markdown 中的图片相对路径替换为 S3 预签名 URL
    # MinerU 输出的图片引用格式：![...](images/xxx.png)
    # 对应 S3 路径：{target_key_without_ext}/images/xxx.png
    import re
    target_prefix = job.target_key[:-3]  # 去掉 .md

    def replace_image_url(match: re.Match) -> str:
        alt = match.group(1)
        img_path = match.group(2)
        if img_path.startswith("http://") or img_path.startswith("https://"):
            return match.group(0)
        # 构建 S3 key
        img_key = f"{target_prefix}/{img_path.lstrip('./')}"
        try:
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": config.target_bucket, "Key": img_key},
                ExpiresIn=900,
            )
            return f"![{alt}]({url})"
        except Exception:
            return match.group(0)

    content = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_image_url, content)

    return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile):
    config: AppConfig = request.app.state.config

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")

    # 上传到源桶，路径为 source_prefix + filename
    key = config.source_prefix + file.filename if config.source_prefix else file.filename

    s3_client = boto3.client("s3", region_name=config.aws_region)
    try:
        content = await file.read()
        s3_client.put_object(
            Bucket=config.source_bucket,
            Key=key,
            Body=content,
            ContentType=file.content_type or "application/octet-stream",
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Upload failed: {e}") from e

    return {"key": key, "size": len(content)}

@app.delete("/api/jobs")
async def delete_jobs(body: DeleteRequest, request: Request):
    job_store: JobStore = request.app.state.job_store
    if not body.job_ids:
        raise HTTPException(status_code=400, detail="No job_ids provided")
    deleted = await job_store.delete_jobs(body.job_ids)
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Batch download (zip)
# ---------------------------------------------------------------------------

@app.post("/api/jobs/download")
async def download_jobs(body: DownloadRequest, request: Request):
    config: AppConfig = request.app.state.config
    job_store: JobStore = request.app.state.job_store

    if not body.job_ids:
        raise HTTPException(status_code=400, detail="No job_ids provided")

    src_client = boto3.client("s3", region_name=config.aws_region)
    dst_client = boto3.client("s3", region_name=config.aws_region)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for job_id in body.job_ids:
            job = await job_store.get_job(job_id)
            if job is None:
                continue

            folder_name = Path(job.file_key).stem[:80]

            # 原始文件
            try:
                obj = src_client.get_object(Bucket=config.source_bucket, Key=job.file_key)
                orig_bytes = obj["Body"].read()
                orig_filename = Path(job.file_key).name
                zf.writestr(f"{folder_name}/{orig_filename}", orig_bytes)
            except Exception:
                pass

            # OCR 结果（Markdown + 图片）
            if job.target_key:
                try:
                    obj = dst_client.get_object(Bucket=config.target_bucket, Key=job.target_key)
                    md_bytes = obj["Body"].read()
                    md_filename = Path(job.target_key).name
                    zf.writestr(f"{folder_name}/{md_filename}", md_bytes)
                except Exception:
                    pass

                # 打包图片：列出 {target_prefix}/images/ 下所有文件
                target_prefix = job.target_key[:-3]  # 去掉 .md
                images_prefix = f"{target_prefix}/images/"
                try:
                    paginator = dst_client.get_paginator("list_objects_v2")
                    for page in paginator.paginate(Bucket=config.target_bucket, Prefix=images_prefix):
                        for obj_info in page.get("Contents", []):
                            img_key = obj_info["Key"]
                            try:
                                img_obj = dst_client.get_object(Bucket=config.target_bucket, Key=img_key)
                                img_bytes = img_obj["Body"].read()
                                img_name = Path(img_key).name
                                zf.writestr(f"{folder_name}/images/{img_name}", img_bytes)
                            except Exception:
                                pass
                except Exception:
                    pass

    buf.seek(0)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"ocr_results_{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Static files — mounted LAST so API routes take priority
# ---------------------------------------------------------------------------

if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
