"""API Server 测试，使用 FastAPI TestClient + moto mock S3。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from moto import mock_aws

import src.api_server as api_server_module
from src.config import AppConfig
from src.job_store import JobStore

# ---------------------------------------------------------------------------
# 测试配置常量
# ---------------------------------------------------------------------------

REGION = "us-east-1"
SOURCE_BUCKET = "test-source-bucket"
TARGET_BUCKET = "test-target-bucket"

TEST_CONFIG = AppConfig(
    source_bucket=SOURCE_BUCKET,
    target_bucket=TARGET_BUCKET,
    aws_region=REGION,
    source_prefix="",
    target_prefix="",
)


# ---------------------------------------------------------------------------
# 构建不挂载 StaticFiles 的测试专用 app
# ---------------------------------------------------------------------------

def _build_test_app() -> FastAPI:
    """复用 api_server 中的路由，但不挂载 StaticFiles（避免拦截 /api/* 路由）。"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 将 api_server 中所有 APIRoute 复制到 test_app（跳过 StaticFiles Mount）
    from starlette.routing import Mount
    from fastapi.routing import APIRoute
    for route in api_server_module.app.routes:
        if isinstance(route, Mount):
            continue  # 跳过 StaticFiles
        if isinstance(route, APIRoute):
            test_app.router.routes.append(route)

    return test_app


_test_app = _build_test_app()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _run(coro):
    """在新事件循环中运行协程（避免 DeprecationWarning）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def memory_job_store():
    """创建内存 SQLite JobStore 并初始化。"""
    store = JobStore(db_path=":memory:")
    _run(store.init_db())
    yield store
    _run(store.close())


@pytest.fixture
def client(memory_job_store):
    """创建 TestClient，覆盖 app.state 中的 config 和 job_store。"""
    # 同时设置原始 app 和 test_app 的 state（路由函数通过 request.app.state 访问）
    api_server_module.app.state.config = TEST_CONFIG
    api_server_module.app.state.job_store = memory_job_store
    _test_app.state.config = TEST_CONFIG
    _test_app.state.job_store = memory_job_store
    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# 5.1 健康检查
# ---------------------------------------------------------------------------

def test_health_returns_200(client):
    """GET /api/health 应返回 200 及 {"status": "ok"}。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 4.1 / 4.3 配置端点
# ---------------------------------------------------------------------------

def test_config_returns_fields(client):
    """GET /api/config 应返回配置字段，不含凭证。"""
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_bucket"] == SOURCE_BUCKET
    assert data["target_bucket"] == TARGET_BUCKET
    assert data["aws_region"] == REGION
    assert "source_prefix" in data
    assert "target_prefix" in data


def test_config_no_credentials(client):
    """GET /api/config 响应中不得包含 AWS 凭证字段。"""
    resp = client.get("/api/config")
    data = resp.json()
    forbidden = {
        "access_key", "secret_key", "aws_access_key_id",
        "aws_secret_access_key", "session_token",
    }
    lower_keys = {k.lower() for k in data}
    assert lower_keys.isdisjoint(forbidden)


# ---------------------------------------------------------------------------
# 1.1 / 1.4 文件列表端点
# ---------------------------------------------------------------------------

@mock_aws
def test_list_files_normal(client):
    """GET /api/files 正常路径：moto mock S3 中有文件时返回列表。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=SOURCE_BUCKET)
    s3.put_object(Bucket=SOURCE_BUCKET, Key="doc.pdf", Body=b"pdf content")
    s3.put_object(Bucket=SOURCE_BUCKET, Key="img.png", Body=b"png content")
    s3.put_object(Bucket=SOURCE_BUCKET, Key="readme.txt", Body=b"text")

    resp = client.get("/api/files")
    assert resp.status_code == 200
    data = resp.json()
    keys = {f["key"] for f in data}
    assert "doc.pdf" in keys
    assert "img.png" in keys
    assert "readme.txt" not in keys


@mock_aws
def test_list_files_s3_unavailable(client):
    """GET /api/files 当 S3 桶不存在时应返回 503。"""
    # 不创建桶，直接请求
    resp = client.get("/api/files")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 1.2 / 1.3 / 1.5 / 1.6 任务提交端点
# ---------------------------------------------------------------------------

@mock_aws
def test_submit_jobs_normal(client):
    """POST /api/jobs 正常路径应返回 202 及 job 列表。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=SOURCE_BUCKET)
    s3.put_object(Bucket=SOURCE_BUCKET, Key="doc.pdf", Body=b"pdf")

    with patch("src.api_server.run_ocr_job", new_callable=AsyncMock):
        resp = client.post("/api/jobs", json={"file_keys": ["doc.pdf"]})

    assert resp.status_code == 202
    data = resp.json()
    assert "jobs" in data
    assert len(data["jobs"]) == 1
    assert "job_id" in data["jobs"][0]
    assert data["jobs"][0]["file_key"] == "doc.pdf"


@mock_aws
def test_submit_jobs_unsupported_format(client):
    """POST /api/jobs 不支持格式应返回 400。"""
    with patch("src.api_server.run_ocr_job", new_callable=AsyncMock):
        resp = client.post("/api/jobs", json={"file_keys": ["document.docx"]})

    assert resp.status_code == 400
    assert "Unsupported format" in resp.json()["detail"]


@mock_aws
def test_submit_jobs_duplicate_running(client, memory_job_store):
    """POST /api/jobs 对 running 状态的 Job 重复提交应返回 409。"""
    # 先手动插入一个 running 状态的 job
    _run(
        memory_job_store.create_job(
            job_id="existing-job-id",
            file_key="doc.pdf",
            file_size=1024,
            submitted_at="2024-01-01T00:00:00Z",
        )
    )
    _run(memory_job_store.update_job("existing-job-id", status="running"))

    with patch("src.api_server.run_ocr_job", new_callable=AsyncMock):
        resp = client.post("/api/jobs", json={"file_keys": ["doc.pdf"]})

    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 2.4 / 2.5 / 2.6 任务查询端点
# ---------------------------------------------------------------------------

def test_list_jobs_returns_list(client, memory_job_store):
    """GET /api/jobs 应返回 Job 列表。"""
    _run(
        memory_job_store.create_job(
            job_id="job-1",
            file_key="a.pdf",
            file_size=100,
            submitted_at="2024-01-01T00:00:00Z",
        )
    )

    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["job_id"] == "job-1"


def test_get_job_exists(client, memory_job_store):
    """GET /api/jobs/{job_id} 存在时应返回 200 及 Job 详情。"""
    _run(
        memory_job_store.create_job(
            job_id="job-abc",
            file_key="b.pdf",
            file_size=200,
            submitted_at="2024-01-02T00:00:00Z",
        )
    )

    resp = client.get("/api/jobs/job-abc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "job-abc"
    assert data["file_key"] == "b.pdf"
    assert data["status"] == "pending"


def test_get_job_not_found(client):
    """GET /api/jobs/{job_id} 不存在时应返回 404。"""
    resp = client.get("/api/jobs/nonexistent-job-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3.4 / 3.5 / 3.6 对比视图端点
# ---------------------------------------------------------------------------

@mock_aws
def test_get_source_url(client, memory_job_store):
    """GET /api/jobs/{job_id}/source 应返回预签名 URL。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=SOURCE_BUCKET)
    s3.put_object(Bucket=SOURCE_BUCKET, Key="source.pdf", Body=b"pdf")

    _run(
        memory_job_store.create_job(
            job_id="job-src",
            file_key="source.pdf",
            file_size=300,
            submitted_at="2024-01-03T00:00:00Z",
        )
    )

    resp = client.get("/api/jobs/job-src/source")
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert "source.pdf" in data["url"]


@mock_aws
def test_get_result_returns_markdown(client, memory_job_store):
    """GET /api/jobs/{job_id}/result 应返回 Markdown 内容。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=TARGET_BUCKET)
    md_content = "# OCR Result\n\nSome text here."
    s3.put_object(Bucket=TARGET_BUCKET, Key="result/doc.md", Body=md_content.encode())

    _run(
        memory_job_store.create_job(
            job_id="job-res",
            file_key="doc.pdf",
            file_size=400,
            submitted_at="2024-01-04T00:00:00Z",
        )
    )
    _run(
        memory_job_store.update_job(
            "job-res",
            status="success",
            target_key="result/doc.md",
        )
    )

    resp = client.get("/api/jobs/job-res/result")
    assert resp.status_code == 200
    assert "OCR Result" in resp.text
