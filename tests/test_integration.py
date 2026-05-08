"""集成测试：端到端流程测试，使用 moto mock S3，mock MinerU CLI。"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from src.config import AppConfig, ConfigLoader
from src.main import OCRApplication


def _make_config(**kwargs) -> AppConfig:
    defaults = dict(
        source_bucket="source-bucket",
        target_bucket="target-bucket",
        aws_region="us-east-1",
        source_prefix="input/",
        target_prefix="output/",
        log_level="WARNING",
        mineru_backend="pipeline",
        mineru_lang="ch",
    )
    defaults.update(kwargs)
    return AppConfig(**defaults)


def _create_buckets(region: str = "us-east-1") -> tuple:
    """Create source and target S3 buckets, return (s3_client, source_bucket, target_bucket)."""
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket="source-bucket")
    s3.create_bucket(Bucket="target-bucket")
    return s3


# ---------------------------------------------------------------------------
# test_full_pipeline_with_moto
# ---------------------------------------------------------------------------

@mock_aws
def test_full_pipeline_with_moto(tmp_path):
    """端到端流程：从 S3 读取 PDF，OCR 处理，结果上传到目标 S3 桶。"""
    s3 = _create_buckets()

    # Upload a test PDF to source bucket
    s3.put_object(Bucket="source-bucket", Key="input/test.pdf", Body=b"%PDF-1.4 test content")

    config = _make_config()

    def mock_subprocess_run(cmd, **kwargs):
        """Simulate MinerU CLI: create output files in the expected directory."""
        # cmd: ["mineru", "-p", input_path, "-o", output_dir, ...]
        output_dir = Path(cmd[4])  # -o argument
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "test.md").write_text("# Test OCR Result", encoding="utf-8")
        (output_dir / "test_middle.json").write_text(
            json.dumps({"pdf_info": [{}, {}, {}]}), encoding="utf-8"
        )
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        app = OCRApplication(config)
        app.run()

    # Verify result file exists in target bucket
    response = s3.get_object(Bucket="target-bucket", Key="output/test.md")
    content = response["Body"].read().decode("utf-8")
    assert content == "# Test OCR Result"

    # Verify report shows 1 success
    results = app.tracker.get_results()
    assert len(results) == 1
    assert results[0].status == "success"


# ---------------------------------------------------------------------------
# test_pipeline_skips_unsupported_format
# ---------------------------------------------------------------------------

@mock_aws
def test_pipeline_skips_unsupported_format():
    """不支持的文件格式（.txt）在 S3 列举阶段被过滤，不上传到目标桶，不调用 MinerU。"""
    s3 = _create_buckets()

    # Upload a .txt file (unsupported format — filtered by S3Reader.list_files)
    s3.put_object(Bucket="source-bucket", Key="input/document.txt", Body=b"plain text content")

    config = _make_config()

    with patch("subprocess.run") as mock_run:
        app = OCRApplication(config)
        app.run()

    # subprocess.run should NOT be called — unsupported file is filtered at listing stage
    mock_run.assert_not_called()

    # Verify no files uploaded to target bucket
    response = s3.list_objects_v2(Bucket="target-bucket")
    assert response.get("KeyCount", 0) == 0

    # S3Reader.list_files filters .txt files, so no jobs are tracked
    results = app.tracker.get_results()
    assert len(results) == 0


# ---------------------------------------------------------------------------
# test_pipeline_continues_on_mineru_failure
# ---------------------------------------------------------------------------

@mock_aws
def test_pipeline_continues_on_mineru_failure(tmp_path):
    """MinerU 失败时，继续处理下一个文件，最终报告显示 1 成功 1 失败。"""
    s3 = _create_buckets()

    # Upload two PDF files
    s3.put_object(Bucket="source-bucket", Key="input/bad.pdf", Body=b"%PDF bad")
    s3.put_object(Bucket="source-bucket", Key="input/good.pdf", Body=b"%PDF good")

    config = _make_config()

    call_count = {"n": 0}

    def mock_subprocess_run(cmd, **kwargs):
        """Fail for bad.pdf, succeed for good.pdf."""
        input_path = Path(cmd[2])  # -p argument
        output_dir = Path(cmd[4])  # -o argument
        call_count["n"] += 1

        result = MagicMock()
        if input_path.name == "bad.pdf":
            result.returncode = 1
            result.stderr = "MinerU processing error"
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "good.md").write_text("# Good OCR Result", encoding="utf-8")
            (output_dir / "good_middle.json").write_text(
                json.dumps({"pdf_info": [{}, {}]}), encoding="utf-8"
            )
            result.returncode = 0
            result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        app = OCRApplication(config)
        app.run()

    # Verify only good.pdf result is in target bucket
    response = s3.list_objects_v2(Bucket="target-bucket")
    keys = [obj["Key"] for obj in response.get("Contents", [])]
    assert "output/good.md" in keys
    assert "output/bad.md" not in keys

    # Verify report shows 1 success, 1 failed
    results = app.tracker.get_results()
    statuses = {r.file_key: r.status for r in results}
    assert statuses.get("input/bad.pdf") == "failed"
    assert statuses.get("input/good.pdf") == "success"
    assert len(results) == 2
