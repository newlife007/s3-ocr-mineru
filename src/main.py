"""OCR 应用程序入口模块。"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from src.config import AppConfig, ConfigLoader
from src.exceptions import (
    ConfigError,
    MinerUError,
    S3AccessError,
    S3UploadError,
    UnsupportedFormatError,
)
from src.job_tracker import JobTracker
from src.logger import StructuredLogger
from src.mineru_runner import SUPPORTED_EXTENSIONS, MinerURunner
from src.report import ReportGenerator
from src.s3_reader import S3Reader
from src.s3_writer import S3Writer, build_target_key


class OCRApplication:
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = StructuredLogger("ocr-app", level=config.log_level)
        self.s3_reader = S3Reader(bucket=config.source_bucket, region=config.aws_region)
        self.mineru_runner = MinerURunner(backend=config.mineru_backend, lang=config.mineru_lang)
        self.s3_writer = S3Writer(bucket=config.target_bucket, region=config.aws_region)
        self.tracker = JobTracker(logger=self.logger)
        self.report_generator = ReportGenerator()

    def run(self) -> None:
        files = self.s3_reader.list_files(self.config.source_prefix)

        if not files:
            self.logger.info("No files found", prefix=self.config.source_prefix)
            return

        for file_info in files:
            tmp_dir = tempfile.mkdtemp()
            try:
                suffix = Path(file_info.key).suffix.lower()
                if suffix not in SUPPORTED_EXTENSIONS:
                    self.logger.warning(
                        "Unsupported file format, skipping",
                        file_key=file_info.key,
                        suffix=suffix,
                    )
                    self.tracker.finish_job(
                        file_key=file_info.key,
                        file_size=file_info.size,
                        page_count=0,
                        status="skipped",
                        error=f"Unsupported format: {suffix}",
                    )
                    continue

                self.tracker.start_job(file_info.key, file_info.size)

                input_path = Path(tmp_dir) / Path(file_info.key).name
                self.s3_reader.download_file(file_info.key, input_path)

                work_dir = Path(tmp_dir) / "output"
                work_dir.mkdir(parents=True, exist_ok=True)

                try:
                    result = self.mineru_runner.run(input_path, work_dir)
                except UnsupportedFormatError as e:
                    self.logger.warning(
                        "Unsupported format during OCR",
                        file_key=file_info.key,
                        error=str(e),
                    )
                    self.tracker.finish_job(
                        file_key=file_info.key,
                        file_size=file_info.size,
                        page_count=0,
                        status="skipped",
                        error=str(e),
                    )
                    continue
                except MinerUError as e:
                    self.logger.error(
                        "MinerU OCR failed",
                        file_key=file_info.key,
                        error=str(e),
                    )
                    self.tracker.finish_job(
                        file_key=file_info.key,
                        file_size=file_info.size,
                        page_count=0,
                        status="failed",
                        error=str(e),
                    )
                    continue

                target_key = build_target_key(
                    source_key=file_info.key,
                    source_prefix=self.config.source_prefix,
                    target_prefix=self.config.target_prefix,
                )

                try:
                    self.s3_writer.upload(result.md_content, target_key)
                except S3UploadError as e:
                    self.logger.error(
                        "S3 upload failed",
                        file_key=file_info.key,
                        target_key=target_key,
                        error=str(e),
                    )
                    self.tracker.finish_job(
                        file_key=file_info.key,
                        file_size=file_info.size,
                        page_count=result.page_count,
                        status="failed",
                        error=str(e),
                    )
                    continue

                self.tracker.finish_job(
                    file_key=file_info.key,
                    file_size=file_info.size,
                    page_count=result.page_count,
                    status="success",
                )

            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        report = self.report_generator.generate(self.tracker.get_results())
        print(self.report_generator.format_text(report))


def main() -> None:
    parser = argparse.ArgumentParser(description="S3 OCR batch processing with MinerU")
    parser.add_argument("--config", dest="config_file", default=None, help="Path to YAML config file")
    args = parser.parse_args()

    try:
        config = ConfigLoader().load(args.config_file)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    logger = StructuredLogger("ocr-app", level=config.log_level)

    try:
        app = OCRApplication(config)
        app.run()
    except S3AccessError as e:
        logger.error("S3 access error", error=str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error", exc_info=True, error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
