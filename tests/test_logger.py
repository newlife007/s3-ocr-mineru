import io
import json
import logging

import pytest

from src.logger import StructuredLogger


def capture_logger_output(logger: StructuredLogger) -> io.StringIO:
    """Replace the logger's handler stream with a StringIO buffer and return it."""
    buf = io.StringIO()
    handler = logger._logger.handlers[0]
    handler.stream = buf
    return buf


def parse_lines(buf: io.StringIO) -> list[dict]:
    buf.seek(0)
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


# ── Required fields ──────────────────────────────────────────────────────────

def test_info_contains_required_fields():
    logger = StructuredLogger("test_info")
    buf = capture_logger_output(logger)
    logger.info("hello")
    records = parse_lines(buf)
    assert len(records) == 1
    rec = records[0]
    assert rec["level"] == "INFO"
    assert rec["logger"] == "test_info"
    assert rec["message"] == "hello"
    assert "timestamp" in rec


def test_warning_contains_required_fields():
    logger = StructuredLogger("test_warning")
    buf = capture_logger_output(logger)
    logger.warning("watch out")
    records = parse_lines(buf)
    assert records[0]["level"] == "WARNING"


def test_error_contains_required_fields():
    logger = StructuredLogger("test_error")
    buf = capture_logger_output(logger)
    logger.error("oops")
    records = parse_lines(buf)
    assert records[0]["level"] == "ERROR"


def test_debug_contains_required_fields():
    logger = StructuredLogger("test_debug", level="DEBUG")
    buf = capture_logger_output(logger)
    logger.debug("verbose")
    records = parse_lines(buf)
    assert records[0]["level"] == "DEBUG"


# ── Extra kwargs are included ─────────────────────────────────────────────────

def test_extra_kwargs_included():
    logger = StructuredLogger("test_extra")
    buf = capture_logger_output(logger)
    logger.info("msg", file="report.pdf", size=1024)
    rec = parse_lines(buf)[0]
    assert rec["file"] == "report.pdf"
    assert rec["size"] == 1024


# ── exc_info includes traceback ───────────────────────────────────────────────

def test_error_exc_info_includes_traceback():
    logger = StructuredLogger("test_exc")
    buf = capture_logger_output(logger)
    try:
        raise ValueError("boom")
    except ValueError:
        logger.error("caught", exc_info=True)
    rec = parse_lines(buf)[0]
    assert "traceback" in rec
    assert "ValueError" in rec["traceback"]


def test_error_no_exc_info_no_traceback():
    logger = StructuredLogger("test_no_exc")
    buf = capture_logger_output(logger)
    logger.error("plain error")
    rec = parse_lines(buf)[0]
    assert "traceback" not in rec


# ── Level filtering ───────────────────────────────────────────────────────────

def test_warning_level_suppresses_info_and_debug():
    logger = StructuredLogger("test_filter_warn", level="WARNING")
    buf = capture_logger_output(logger)
    logger.debug("debug msg")
    logger.info("info msg")
    logger.warning("warn msg")
    records = parse_lines(buf)
    assert len(records) == 1
    assert records[0]["level"] == "WARNING"


def test_error_level_suppresses_warning_info_debug():
    logger = StructuredLogger("test_filter_error", level="ERROR")
    buf = capture_logger_output(logger)
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")
    records = parse_lines(buf)
    assert len(records) == 1
    assert records[0]["level"] == "ERROR"


def test_debug_level_allows_all():
    logger = StructuredLogger("test_filter_debug", level="DEBUG")
    buf = capture_logger_output(logger)
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")
    records = parse_lines(buf)
    assert len(records) == 4


# ── Each line is valid JSON ───────────────────────────────────────────────────

def test_each_line_is_valid_json():
    logger = StructuredLogger("test_json", level="DEBUG")
    buf = capture_logger_output(logger)
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")
    buf.seek(0)
    for line in buf.getvalue().splitlines():
        if line.strip():
            json.loads(line)  # must not raise
