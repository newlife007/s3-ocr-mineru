import time
from unittest.mock import MagicMock, call

import pytest

from src.job_tracker import JobResult, JobTracker
from src.logger import StructuredLogger


def make_tracker():
    logger = MagicMock(spec=StructuredLogger)
    tracker = JobTracker(logger)
    return tracker, logger


def test_start_job_logs_file_info():
    tracker, logger = make_tracker()
    tracker.start_job("docs/report.pdf", 1024)
    logger.info.assert_called_once()
    args, kwargs = logger.info.call_args
    assert kwargs.get("file_key") == "docs/report.pdf"
    assert kwargs.get("file_size") == 1024


def test_finish_job_returns_job_result():
    tracker, _ = make_tracker()
    tracker.start_job("docs/report.pdf", 2048)
    result = tracker.finish_job("docs/report.pdf", 2048, 5, "success")

    assert isinstance(result, JobResult)
    assert result.file_key == "docs/report.pdf"
    assert result.file_size == 2048
    assert result.page_count == 5
    assert result.status == "success"
    assert result.error is None


def test_finish_job_with_error():
    tracker, _ = make_tracker()
    tracker.start_job("bad.pdf", 512)
    result = tracker.finish_job("bad.pdf", 512, 0, "failed", error="OCR failed")

    assert result.status == "failed"
    assert result.error == "OCR failed"


def test_sequential_processing_order():
    tracker, _ = make_tracker()
    files = [("a.pdf", 100, 1), ("b.pdf", 200, 2), ("c.pdf", 300, 3)]

    for key, size, pages in files:
        tracker.start_job(key, size)
        tracker.finish_job(key, size, pages, "success")

    results = tracker.get_results()
    assert len(results) == 3
    assert [r.file_key for r in results] == ["a.pdf", "b.pdf", "c.pdf"]
    assert [r.page_count for r in results] == [1, 2, 3]


def test_finish_job_calculates_duration():
    tracker, _ = make_tracker()
    tracker.start_job("file.pdf", 1000)
    time.sleep(0.05)
    result = tracker.finish_job("file.pdf", 1000, 3, "success")

    assert result.duration > 0
    assert result.duration < 5.0  # reasonable upper bound


def test_get_results_returns_copy():
    tracker, _ = make_tracker()
    tracker.start_job("x.pdf", 100)
    tracker.finish_job("x.pdf", 100, 1, "success")

    results = tracker.get_results()
    results.clear()

    # Original list should be unaffected
    assert len(tracker.get_results()) == 1


def test_finish_job_logs_info():
    tracker, logger = make_tracker()
    tracker.start_job("file.pdf", 500)
    tracker.finish_job("file.pdf", 500, 4, "success")

    # info called twice: start + finish
    assert logger.info.call_count == 2
    finish_call_kwargs = logger.info.call_args[1]
    assert finish_call_kwargs.get("file_key") == "file.pdf"
    assert finish_call_kwargs.get("page_count") == 4
    assert finish_call_kwargs.get("status") == "success"
    assert "duration" in finish_call_kwargs
