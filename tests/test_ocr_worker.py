"""ocr_worker.run_ocr_job 单元测试。"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.config import AppConfig
from src.exceptions import UnsupportedFormatError
from src.job_store import JobStore
from src.mineru_runner import OCRResult
from src.ocr_worker import run_ocr_job

pytestmark = pytest.mark.asyncio


@pytest.fixture
def config():
    return AppConfig(
        source_bucket="src-bucket",
        target_bucket="tgt-bucket",
        aws_region="us-east-1",
        source_prefix="input/",
        target_prefix="output/",
    )


@pytest_asyncio.fixture
async def job_store(tmp_path):
    store = JobStore(db_path=str(tmp_path / "test.db"))
    await store.init_db()
    await store.create_job(
        job_id="job-1",
        file_key="input/doc.pdf",
        file_size=1024,
        submitted_at="2024-01-01T00:00:00Z",
    )
    yield store
    await store.close()


@pytest.mark.asyncio
async def test_run_ocr_job_success(config, job_store):
    """成功路径：状态更新为 success，填充 page_count、target_key、completed_at。"""
    ocr_result = OCRResult(md_content="# Hello", page_count=3)

    with (
        patch("src.ocr_worker.S3Reader") as MockReader,
        patch("src.ocr_worker.MinerURunner") as MockRunner,
        patch("src.ocr_worker.S3Writer") as MockWriter,
    ):
        MockReader.return_value.download_file = MagicMock()
        MockRunner.return_value.run = MagicMock(return_value=ocr_result)
        MockWriter.return_value.upload = MagicMock()

        await run_ocr_job("job-1", "input/doc.pdf", config, job_store)

    record = await job_store.get_job("job-1")
    assert record.status == "success"
    assert record.page_count == 3
    assert record.target_key == "output/doc.md"
    assert record.completed_at is not None
    assert record.completed_at.endswith("Z")


@pytest.mark.asyncio
async def test_run_ocr_job_unsupported_format(config, job_store):
    """UnsupportedFormatError → 状态更新为 skipped，填充 error。"""
    with (
        patch("src.ocr_worker.S3Reader") as MockReader,
        patch("src.ocr_worker.MinerURunner") as MockRunner,
    ):
        MockReader.return_value.download_file = MagicMock()
        MockRunner.return_value.run = MagicMock(
            side_effect=UnsupportedFormatError("不支持的格式：.xyz")
        )

        await run_ocr_job("job-1", "input/doc.pdf", config, job_store)

    record = await job_store.get_job("job-1")
    assert record.status == "skipped"
    assert "不支持的格式" in record.error


@pytest.mark.asyncio
async def test_run_ocr_job_generic_exception(config, job_store):
    """其他异常 → 状态更新为 failed，填充 error。"""
    with (
        patch("src.ocr_worker.S3Reader") as MockReader,
        patch("src.ocr_worker.MinerURunner") as MockRunner,
    ):
        MockReader.return_value.download_file = MagicMock()
        MockRunner.return_value.run = MagicMock(
            side_effect=RuntimeError("unexpected error")
        )

        await run_ocr_job("job-1", "input/doc.pdf", config, job_store)

    record = await job_store.get_job("job-1")
    assert record.status == "failed"
    assert "unexpected error" in record.error


@pytest.mark.asyncio
async def test_run_ocr_job_sets_running_first(config, job_store):
    """任务开始时状态先变为 running。"""
    statuses = []

    original_update = job_store.update_job

    async def tracking_update(job_id, **kwargs):
        if "status" in kwargs:
            statuses.append(kwargs["status"])
        await original_update(job_id, **kwargs)

    job_store.update_job = tracking_update

    ocr_result = OCRResult(md_content="# Test", page_count=1)

    with (
        patch("src.ocr_worker.S3Reader") as MockReader,
        patch("src.ocr_worker.MinerURunner") as MockRunner,
        patch("src.ocr_worker.S3Writer") as MockWriter,
    ):
        MockReader.return_value.download_file = MagicMock()
        MockRunner.return_value.run = MagicMock(return_value=ocr_result)
        MockWriter.return_value.upload = MagicMock()

        await run_ocr_job("job-1", "input/doc.pdf", config, job_store)

    assert statuses[0] == "running"
    assert statuses[-1] == "success"
