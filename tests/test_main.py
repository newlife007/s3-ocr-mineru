"""Unit tests for src/main.py — OCRApplication and main()."""

import sys
from unittest.mock import MagicMock, call, patch

import pytest

from src.config import AppConfig
from src.exceptions import ConfigError, MinerUError, S3AccessError, S3UploadError
from src.job_tracker import JobResult
from src.mineru_runner import OCRResult
from src.s3_reader import S3FileInfo


def _make_config(**kwargs) -> AppConfig:
    defaults = dict(
        source_bucket="src-bucket",
        target_bucket="dst-bucket",
        aws_region="us-east-1",
        source_prefix="input/",
        target_prefix="output/",
        log_level="INFO",
        mineru_backend="pipeline",
        mineru_lang="ch",
    )
    defaults.update(kwargs)
    return AppConfig(**defaults)


def _make_app(config=None):
    """Create an OCRApplication with all dependencies mocked."""
    from src.main import OCRApplication

    cfg = config or _make_config()
    with (
        patch("src.main.S3Reader"),
        patch("src.main.MinerURunner"),
        patch("src.main.S3Writer"),
        patch("src.main.JobTracker"),
        patch("src.main.ReportGenerator"),
        patch("src.main.StructuredLogger"),
    ):
        app = OCRApplication(cfg)

    # Replace with fresh mocks so tests can configure them freely
    app.logger = MagicMock()
    app.s3_reader = MagicMock()
    app.mineru_runner = MagicMock()
    app.s3_writer = MagicMock()
    app.tracker = MagicMock()
    app.report_generator = MagicMock()
    return app


def _dummy_job_result(file_key="input/a.pdf", status="success"):
    return JobResult(
        file_key=file_key,
        file_size=1024,
        page_count=2,
        duration=1.0,
        status=status,
    )


# ---------------------------------------------------------------------------
# test_run_empty_file_list
# ---------------------------------------------------------------------------

def test_run_empty_file_list():
    """When S3Reader returns no files, log INFO and return without processing."""
    app = _make_app()
    app.s3_reader.list_files.return_value = []

    app.run()

    # Should log info about no files found
    app.logger.info.assert_called_once()
    call_args = app.logger.info.call_args
    assert "No files found" in call_args[0][0]

    # Should NOT start any jobs
    app.tracker.start_job.assert_not_called()

    # Should NOT generate a report
    app.report_generator.generate.assert_not_called()


# ---------------------------------------------------------------------------
# test_run_processes_files_sequentially
# ---------------------------------------------------------------------------

def test_run_processes_files_sequentially():
    """All files are processed in order; report is generated at the end."""
    app = _make_app()
    files = [
        S3FileInfo(key="input/a.pdf", size=100),
        S3FileInfo(key="input/b.pdf", size=200),
    ]
    app.s3_reader.list_files.return_value = files
    app.s3_reader.download_file.return_value = None
    app.mineru_runner.run.return_value = OCRResult(md_content="# Hello", page_count=3)
    app.s3_writer.upload.return_value = None
    app.tracker.get_results.return_value = [
        _dummy_job_result("input/a.pdf"),
        _dummy_job_result("input/b.pdf"),
    ]
    app.report_generator.generate.return_value = MagicMock()
    app.report_generator.format_text.return_value = "report text"

    with (
        patch("src.main.tempfile.mkdtemp", return_value="/tmp/fake"),
        patch("src.main.shutil.rmtree"),
    ):
        app.run()

    # start_job called once per file
    assert app.tracker.start_job.call_count == 2
    # finish_job called once per file
    assert app.tracker.finish_job.call_count == 2
    # report generated once
    app.report_generator.generate.assert_called_once()

    # Verify order: a.pdf before b.pdf
    start_calls = [c[0][0] for c in app.tracker.start_job.call_args_list]
    assert start_calls == ["input/a.pdf", "input/b.pdf"]


# ---------------------------------------------------------------------------
# test_run_continues_on_mineru_error
# ---------------------------------------------------------------------------

def test_run_continues_on_mineru_error():
    """When MinerU fails on one file, processing continues for the next file."""
    app = _make_app()
    files = [
        S3FileInfo(key="input/bad.pdf", size=100),
        S3FileInfo(key="input/good.pdf", size=200),
    ]
    app.s3_reader.list_files.return_value = files
    app.s3_reader.download_file.return_value = None

    # First call raises MinerUError, second succeeds
    app.mineru_runner.run.side_effect = [
        MinerUError("mineru crashed"),
        OCRResult(md_content="# OK", page_count=5),
    ]
    app.s3_writer.upload.return_value = None
    app.tracker.get_results.return_value = [
        _dummy_job_result("input/bad.pdf", status="failed"),
        _dummy_job_result("input/good.pdf", status="success"),
    ]
    app.report_generator.generate.return_value = MagicMock()
    app.report_generator.format_text.return_value = "report"

    with (
        patch("src.main.tempfile.mkdtemp", return_value="/tmp/fake"),
        patch("src.main.shutil.rmtree"),
    ):
        app.run()

    # Both files attempted
    assert app.tracker.start_job.call_count == 2
    assert app.tracker.finish_job.call_count == 2

    # First finish_job should be "failed"
    first_call = app.tracker.finish_job.call_args_list[0]
    assert first_call.kwargs.get("status") == "failed"

    # Error logged for the failed file
    app.logger.error.assert_called()


# ---------------------------------------------------------------------------
# test_run_skips_unsupported_format
# ---------------------------------------------------------------------------

def test_run_skips_unsupported_format():
    """Files with unsupported extensions are skipped (status='skipped'), not failed."""
    app = _make_app()
    files = [
        S3FileInfo(key="input/doc.docx", size=500),
        S3FileInfo(key="input/report.pdf", size=300),
    ]
    app.s3_reader.list_files.return_value = files
    app.s3_reader.download_file.return_value = None
    app.mineru_runner.run.return_value = OCRResult(md_content="# PDF", page_count=2)
    app.s3_writer.upload.return_value = None
    app.tracker.get_results.return_value = [
        _dummy_job_result("input/doc.docx", status="skipped"),
        _dummy_job_result("input/report.pdf", status="success"),
    ]
    app.report_generator.generate.return_value = MagicMock()
    app.report_generator.format_text.return_value = "report"

    with (
        patch("src.main.tempfile.mkdtemp", return_value="/tmp/fake"),
        patch("src.main.shutil.rmtree"),
    ):
        app.run()

    # finish_job called for both files
    assert app.tracker.finish_job.call_count == 2

    # The .docx file should be finished with status="skipped"
    skipped_call = app.tracker.finish_job.call_args_list[0]
    assert skipped_call.kwargs.get("status") == "skipped"

    # start_job should only be called for the PDF (not the .docx)
    assert app.tracker.start_job.call_count == 1
    assert app.tracker.start_job.call_args[0][0] == "input/report.pdf"


# ---------------------------------------------------------------------------
# test_main_exits_on_config_error
# ---------------------------------------------------------------------------

def test_main_exits_on_config_error():
    """main() prints error and exits with code 1 when ConfigLoader raises ConfigError."""
    from src.main import main

    with (
        patch("src.main.ConfigLoader") as MockLoader,
        patch("sys.argv", ["main"]),
    ):
        MockLoader.return_value.load.side_effect = ConfigError("missing source_bucket")

        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
