import pytest
from src.job_tracker import JobResult
from src.report import ReportGenerator, SummaryReport


def make_job(status: str, error: str = None) -> JobResult:
    return JobResult(
        file_key=f"docs/file_{status}.pdf",
        file_size=1024 * 1024,
        page_count=5,
        duration=3.45,
        status=status,
        error=error,
    )


@pytest.fixture
def generator():
    return ReportGenerator()


def test_generate_counts_correctly(generator):
    results = [
        make_job("success"),
        make_job("success"),
        make_job("failed", error="timeout"),
        make_job("skipped"),
    ]
    report = generator.generate(results)
    assert report.success == 2
    assert report.failed == 1
    assert report.skipped == 1


def test_generate_total_equals_sum(generator):
    results = [
        make_job("success"),
        make_job("failed"),
        make_job("skipped"),
        make_job("success"),
    ]
    report = generator.generate(results)
    assert report.total == report.success + report.failed + report.skipped


def test_format_text_contains_summary(generator):
    results = [make_job("success"), make_job("failed", error="err"), make_job("skipped")]
    report = generator.generate(results)
    text = generator.format_text(report)
    assert "Total:   3" in text
    assert "Success: 1" in text
    assert "Failed:  1" in text
    assert "Skipped: 1" in text


def test_format_text_contains_file_details(generator):
    job = JobResult(
        file_key="docs/report.pdf",
        file_size=2 * 1024 * 1024,
        page_count=10,
        duration=3.45,
        status="success",
    )
    report = generator.generate([job])
    text = generator.format_text(report)
    assert "docs/report.pdf" in text
    assert "3.45s" in text
    assert "success" in text
    assert "10" in text
    # human-readable size
    assert "MB" in text or "KB" in text or "GB" in text


def test_generate_empty_results(generator):
    report = generator.generate([])
    assert report.total == 0
    assert report.success == 0
    assert report.failed == 0
    assert report.skipped == 0
    assert report.jobs == []
    text = generator.format_text(report)
    assert "Total:   0" in text
