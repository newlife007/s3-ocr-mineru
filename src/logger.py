import json
import logging
import sys
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    def __init__(self, logger_name: str):
        super().__init__()
        self.logger_name = logger_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": self.logger_name,
            "message": record.getMessage(),
        }
        # Merge any extra fields stored on the record
        extra = getattr(record, "_extra", {})
        payload.update(extra)

        if record.exc_info and record.exc_info[0] is not None:
            payload["traceback"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class StructuredLogger:
    def __init__(self, name: str, level: str = "INFO"):
        self.name = name
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        self._logger = logging.getLogger(f"structured.{name}")
        # Always reset level and handlers so each instance is independent
        self._logger.setLevel(numeric_level)
        self._logger.handlers.clear()
        handler = logging.StreamHandler()
        handler.setLevel(numeric_level)
        handler.setFormatter(_JsonFormatter(name))
        self._logger.addHandler(handler)
        # Prevent propagation to root logger
        self._logger.propagate = False

    def _log(self, level: int, message: str, exc_info: bool = False, **kwargs) -> None:
        exc = sys.exc_info() if exc_info else None
        record = self._logger.makeRecord(
            name=self._logger.name,
            level=level,
            fn="",
            lno=0,
            msg=message,
            args=(),
            exc_info=exc,
        )
        record._extra = kwargs  # type: ignore[attr-defined]
        self._logger.handle(record)

    def info(self, message: str, **kwargs) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, exc_info: bool = False, **kwargs) -> None:
        self._log(logging.ERROR, message, exc_info=exc_info, **kwargs)

    def debug(self, message: str, **kwargs) -> None:
        self._log(logging.DEBUG, message, **kwargs)
