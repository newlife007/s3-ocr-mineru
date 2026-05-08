import time
from dataclasses import dataclass, field
from typing import Optional

from src.logger import StructuredLogger


@dataclass
class JobResult:
    file_key: str
    file_size: int
    page_count: int
    duration: float
    status: str  # "success", "failed", or "skipped"
    error: Optional[str] = None


class JobTracker:
    def __init__(self, logger: StructuredLogger):
        self._logger = logger
        self._results: list[JobResult] = []
        self._start_time: Optional[float] = None

    def start_job(self, file_key: str, file_size: int) -> None:
        self._start_time = time.monotonic()
        self._logger.info("Starting job", file_key=file_key, file_size=file_size)

    def finish_job(
        self,
        file_key: str,
        file_size: int,
        page_count: int,
        status: str,
        error: Optional[str] = None,
    ) -> JobResult:
        start = self._start_time if self._start_time is not None else time.monotonic()
        duration = time.monotonic() - start

        result = JobResult(
            file_key=file_key,
            file_size=file_size,
            page_count=page_count,
            duration=duration,
            status=status,
            error=error,
        )
        self._results.append(result)

        self._logger.info(
            "Finished job",
            file_key=file_key,
            page_count=page_count,
            duration=f"{duration:.2f}",
            status=status,
        )
        return result

    def get_results(self) -> list[JobResult]:
        return list(self._results)
