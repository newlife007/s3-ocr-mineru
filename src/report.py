from dataclasses import dataclass
from typing import List

from src.job_tracker import JobResult


@dataclass
class SummaryReport:
    total: int
    success: int
    failed: int
    skipped: int
    jobs: List[JobResult]


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


class ReportGenerator:
    def generate(self, results: List[JobResult]) -> SummaryReport:
        success = sum(1 for r in results if r.status == "success")
        failed = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped")
        return SummaryReport(
            total=len(results),
            success=success,
            failed=failed,
            skipped=skipped,
            jobs=results,
        )

    def format_text(self, report: SummaryReport) -> str:
        lines = [
            "=" * 60,
            "OCR Processing Summary",
            "=" * 60,
            f"Total:   {report.total}",
            f"Success: {report.success}",
            f"Failed:  {report.failed}",
            f"Skipped: {report.skipped}",
            "",
            "-" * 60,
            f"{'File':<30} {'Size':>8} {'Pages':>6} {'Duration':>10} {'Status'}",
            "-" * 60,
        ]

        for job in report.jobs:
            size_str = _format_size(job.file_size)
            duration_str = f"{job.duration:.2f}s"
            file_key = job.file_key
            if len(file_key) > 28:
                file_key = "..." + file_key[-25:]
            lines.append(
                f"{file_key:<30} {size_str:>8} {job.page_count:>6} {duration_str:>10} {job.status}"
            )
            if job.error:
                lines.append(f"  Error: {job.error}")

        lines.append("=" * 60)
        return "\n".join(lines)
