"""S3 文件读取模块，提供 S3FileInfo dataclass 和 S3Reader 类。"""

from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from src.exceptions import S3AccessError

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}


@dataclass
class S3FileInfo:
    key: str   # S3 对象键
    size: int  # 文件大小（字节）


class S3Reader:
    def __init__(self, bucket: str, region: str):
        self.bucket = bucket
        self.s3_client = boto3.client("s3", region_name=region)

    def list_files(self, prefix: str = "") -> list[S3FileInfo]:
        """列出 bucket 中匹配 prefix 的所有支持格式文件。"""
        files: list[S3FileInfo] = []
        kwargs: dict = {"Bucket": self.bucket, "Prefix": prefix}

        try:
            while True:
                response = self.s3_client.list_objects_v2(**kwargs)
                for obj in response.get("Contents", []):
                    key: str = obj["Key"]
                    if Path(key).suffix.lower() in SUPPORTED_EXTENSIONS:
                        files.append(S3FileInfo(key=key, size=obj["Size"]))
                if response.get("NextContinuationToken"):
                    kwargs["ContinuationToken"] = response["NextContinuationToken"]
                else:
                    break
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("NoSuchBucket", "AccessDenied", "403", "404"):
                raise S3AccessError(f"Cannot access bucket '{self.bucket}': {error_code}") from e
            raise S3AccessError(f"S3 error for bucket '{self.bucket}': {e}") from e

        return files

    def download_file(self, key: str, local_path: Path) -> None:
        """将 S3 文件下载到 local_path。"""
        self.s3_client.download_file(self.bucket, key, str(local_path))

    def generate_presigned_url(self, key: str, expires_in: int = 900) -> str:
        """生成 S3 对象的预签名 URL，默认有效期 900 秒（15 分钟）。"""
        return self.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
