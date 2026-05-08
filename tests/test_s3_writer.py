"""S3Writer 和 build_target_key 单元测试，使用 moto mock AWS S3。"""

from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from src.exceptions import S3UploadError
from src.s3_writer import S3Writer, build_target_key

REGION = "us-east-1"
BUCKET = "test-bucket"


# ---------------------------------------------------------------------------
# build_target_key tests
# ---------------------------------------------------------------------------

def test_build_target_key_basic():
    """基本路径转换：将扩展名替换为 .md。"""
    result = build_target_key("report.pdf", "", "")
    assert result == "report.md"


def test_build_target_key_with_prefixes():
    """带源前缀和目标前缀的路径转换。"""
    result = build_target_key("docs/report.pdf", "docs/", "results/")
    assert result == "results/report.md"


def test_build_target_key_no_prefix():
    """无前缀情况下仅替换扩展名。"""
    result = build_target_key("report.pdf", "", "")
    assert result == "report.md"


def test_build_target_key_nested_path():
    """多层目录结构保持不变，仅替换扩展名。"""
    result = build_target_key("a/b/c/file.pdf", "a/", "out/")
    assert result == "out/b/c/file.md"


# ---------------------------------------------------------------------------
# S3Writer tests
# ---------------------------------------------------------------------------

@mock_aws
def test_upload_success():
    """成功上传时内容存储在 S3 中，Content-Type 正确。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)

    writer = S3Writer(bucket=BUCKET, region=REGION, retry_interval=0)
    writer.upload("# Hello\n\nWorld", "output/result.md")

    obj = s3.get_object(Bucket=BUCKET, Key="output/result.md")
    assert obj["Body"].read().decode("utf-8") == "# Hello\n\nWorld"
    assert "text/markdown" in obj["ContentType"]


@mock_aws
def test_upload_retry_then_success():
    """前几次失败后重试成功，最终上传成功。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)

    writer = S3Writer(bucket=BUCKET, region=REGION, max_retries=3, retry_interval=0)

    call_count = 0
    original_put = writer.s3_client.put_object

    def flaky_put(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ClientError(
                {"Error": {"Code": "ServiceUnavailable", "Message": "Service unavailable"}},
                "PutObject",
            )
        return original_put(**kwargs)

    with patch.object(writer.s3_client, "put_object", side_effect=flaky_put):
        writer.upload("content", "key.md")

    assert call_count == 3


@mock_aws
def test_upload_exceeds_retries_raises_error():
    """超过最大重试次数后抛出 S3UploadError。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)

    writer = S3Writer(bucket=BUCKET, region=REGION, max_retries=3, retry_interval=0)

    def always_fail(**kwargs):
        raise ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "Service unavailable"}},
            "PutObject",
        )

    with patch.object(writer.s3_client, "put_object", side_effect=always_fail):
        with pytest.raises(S3UploadError):
            writer.upload("content", "key.md")
