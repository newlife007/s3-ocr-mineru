"""S3 结果上传模块，提供 build_target_key 函数和 S3Writer 类。"""

import time
from pathlib import PurePosixPath

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from src.exceptions import S3UploadError


def build_target_key(source_key: str, source_prefix: str, target_prefix: str) -> str:
    """
    将源文件 key 转换为目标 key：
    1. 去除 source_prefix
    2. 将扩展名替换为 .md
    3. 添加 target_prefix

    示例：
      source_key="docs/report.pdf", source_prefix="docs/", target_prefix="results/"
      -> "results/report.md"
    """
    relative = source_key
    if source_prefix and source_key.startswith(source_prefix):
        relative = source_key[len(source_prefix):]

    path = PurePosixPath(relative)
    md_path = path.with_suffix(".md")

    return target_prefix + str(md_path)


class S3Writer:
    def __init__(self, bucket: str, region: str, max_retries: int = 3, retry_interval: float = 5.0):
        self.bucket = bucket
        self.s3_client = boto3.client("s3", region_name=region)
        self.max_retries = max_retries
        self.retry_interval = retry_interval

    def upload(self, content: str, key: str) -> None:
        """
        将 content 上传到 bucket/key，Content-Type 为 text/markdown; charset=utf-8。
        失败时重试最多 max_retries 次，每次间隔 retry_interval 秒。
        若超过重试次数则抛出 S3UploadError。
        """
        body = content.encode("utf-8")
        for attempt in range(self.max_retries + 1):
            try:
                self.s3_client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=body,
                    ContentType="text/markdown; charset=utf-8",
                )
                return
            except (ClientError, BotoCoreError) as e:
                if attempt < self.max_retries:
                    time.sleep(self.retry_interval)
                else:
                    raise S3UploadError(
                        f"Failed to upload '{key}' to bucket '{self.bucket}' "
                        f"after {self.max_retries + 1} attempts"
                    ) from e

    def upload_images(self, images_dir: "Path", key_prefix: str) -> list[str]:
        """
        将 images_dir 下所有图片文件上传到 S3，key 为 key_prefix/images/{filename}。
        返回已上传的 S3 key 列表。
        """
        from pathlib import Path
        import mimetypes

        uploaded = []
        if not images_dir.exists():
            return uploaded

        for img_path in sorted(images_dir.iterdir()):
            if not img_path.is_file():
                continue
            img_key = f"{key_prefix}/images/{img_path.name}"
            content_type = mimetypes.guess_type(img_path.name)[0] or "image/png"
            for attempt in range(self.max_retries + 1):
                try:
                    self.s3_client.put_object(
                        Bucket=self.bucket,
                        Key=img_key,
                        Body=img_path.read_bytes(),
                        ContentType=content_type,
                    )
                    uploaded.append(img_key)
                    break
                except (ClientError, BotoCoreError):
                    if attempt >= self.max_retries:
                        pass  # 单张图片失败不中断整体流程
                    else:
                        time.sleep(self.retry_interval)
        return uploaded
