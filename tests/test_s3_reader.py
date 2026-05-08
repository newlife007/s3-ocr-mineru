"""S3Reader 单元测试，使用 moto mock AWS S3。"""

import boto3
import pytest
from moto import mock_aws

from src.exceptions import S3AccessError
from src.s3_reader import S3FileInfo, S3Reader

REGION = "us-east-1"
BUCKET = "test-bucket"


def _make_reader(bucket: str = BUCKET) -> S3Reader:
    return S3Reader(bucket=bucket, region=REGION)


def _put_object(s3_client, key: str, body: bytes = b"data") -> None:
    s3_client.put_object(Bucket=BUCKET, Key=key, Body=body)


@mock_aws
def test_list_files_returns_supported_formats():
    """只返回支持的文件格式，忽略不支持的格式。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)

    supported = ["doc.pdf", "img.png", "photo.jpg", "scan.jpeg", "fax.tiff"]
    unsupported = ["readme.txt", "data.csv", "archive.zip"]

    for key in supported + unsupported:
        _put_object(s3, key)

    reader = _make_reader()
    result = reader.list_files()

    returned_keys = {f.key for f in result}
    assert returned_keys == set(supported)
    assert all(isinstance(f, S3FileInfo) for f in result)


@mock_aws
def test_list_files_with_prefix_filter():
    """只返回匹配 prefix 的文件。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)

    _put_object(s3, "docs/report.pdf")
    _put_object(s3, "docs/image.png")
    _put_object(s3, "other/file.pdf")

    reader = _make_reader()
    result = reader.list_files(prefix="docs/")

    returned_keys = {f.key for f in result}
    assert returned_keys == {"docs/report.pdf", "docs/image.png"}


@mock_aws
def test_s3_bucket_not_found():
    """当 bucket 不存在时抛出 S3AccessError。"""
    reader = _make_reader(bucket="nonexistent-bucket")
    with pytest.raises(S3AccessError):
        reader.list_files()


@mock_aws
def test_empty_prefix_returns_empty_list():
    """当 prefix 下没有支持格式的文件时返回空列表。"""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)

    _put_object(s3, "notes/readme.txt")
    _put_object(s3, "notes/data.csv")

    reader = _make_reader()
    result = reader.list_files(prefix="notes/")

    assert result == []
