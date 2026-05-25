"""
Job persistence layer using aiosqlite (SQLite async).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import aiosqlite

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    file_key     TEXT NOT NULL,
    file_size    INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending',
    submitted_at TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    page_count   INTEGER,
    error        TEXT,
    target_key   TEXT,
    lang         TEXT,
    arabic_bidi_fix TEXT,
    backend      TEXT
);
"""

_ALLOWED_UPDATE_FIELDS = {"status", "started_at", "completed_at", "page_count", "error", "target_key", "lang", "arabic_bidi_fix", "backend"}


@dataclass
class JobRecord:
    job_id: str
    file_key: str
    file_size: int
    status: str
    submitted_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    page_count: Optional[int]
    error: Optional[str]
    target_key: Optional[str]
    lang: Optional[str]
    arabic_bidi_fix: Optional[str]
    backend: Optional[str]


def _row_to_record(row: aiosqlite.Row) -> JobRecord:
    keys = row.keys()
    return JobRecord(
        job_id=row["job_id"],
        file_key=row["file_key"],
        file_size=row["file_size"],
        status=row["status"],
        submitted_at=row["submitted_at"],
        started_at=row["started_at"] if "started_at" in keys else None,
        completed_at=row["completed_at"],
        page_count=row["page_count"],
        error=row["error"],
        target_key=row["target_key"],
        lang=row["lang"] if "lang" in keys else None,
        arabic_bidi_fix=row["arabic_bidi_fix"] if "arabic_bidi_fix" in keys else None,
        backend=row["backend"] if "backend" in keys else None,
    )


class JobStore:
    """Async SQLite-backed job store.

    Uses a single persistent connection so that in-memory databases
    (``db_path=':memory:'``) work correctly across multiple method calls.
    Call ``await store.init_db()`` before any other method.
    """

    def __init__(self, db_path: str = "jobs.db") -> None:
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def _conn(self) -> aiosqlite.Connection:
        """Return the open connection, opening it if necessary."""
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
        return self._db

    async def close(self) -> None:
        """Close the underlying database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def init_db(self) -> None:
        """Create the jobs table if it does not exist, and migrate existing schema."""
        db = await self._conn()
        await db.execute(_CREATE_TABLE_SQL)
        for col in ("started_at TEXT", "lang TEXT", "arabic_bidi_fix TEXT", "backend TEXT"):
            try:
                await db.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except Exception:
                pass
        await db.commit()

    async def create_job(
        self,
        job_id: str,
        file_key: str,
        file_size: int,
        submitted_at: str,
        lang: Optional[str] = None,
        arabic_bidi_fix: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> JobRecord:
        """Insert a new job record with status='pending' and return it."""
        db = await self._conn()
        await db.execute(
            """
            INSERT INTO jobs (job_id, file_key, file_size, status, submitted_at, lang, arabic_bidi_fix, backend)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (job_id, file_key, file_size, submitted_at, lang, arabic_bidi_fix, backend),
        )
        await db.commit()

        return JobRecord(
            job_id=job_id,
            file_key=file_key,
            file_size=file_size,
            status="pending",
            submitted_at=submitted_at,
            started_at=None,
            completed_at=None,
            page_count=None,
            error=None,
            target_key=None,
            lang=lang,
            arabic_bidi_fix=arabic_bidi_fix,
            backend=backend,
        )

    async def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Return the JobRecord for the given job_id, or None if not found."""
        db = await self._conn()
        async with db.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_record(row) if row else None

    async def list_jobs(self) -> list[JobRecord]:
        """Return all jobs ordered by submitted_at descending."""
        db = await self._conn()
        async with db.execute(
            "SELECT * FROM jobs ORDER BY submitted_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_record(r) for r in rows]

    async def update_job(self, job_id: str, **kwargs) -> None:
        """Update allowed fields on a job record.

        Accepted keyword arguments: status, completed_at, page_count, error, target_key.
        Unknown keys are silently ignored.
        """
        fields = {k: v for k, v in kwargs.items() if k in _ALLOWED_UPDATE_FIELDS}
        if not fields:
            return

        set_clause = ", ".join(f"{col} = ?" for col in fields)
        values = list(fields.values()) + [job_id]

        db = await self._conn()
        await db.execute(
            f"UPDATE jobs SET {set_clause} WHERE job_id = ?",
            values,
        )
        await db.commit()

    async def get_running_job_for_key(self, file_key: str) -> Optional[JobRecord]:
        """Return a running job for the given file_key, or None."""
        db = await self._conn()
        async with db.execute(
            "SELECT * FROM jobs WHERE file_key = ? AND status = 'running' LIMIT 1",
            (file_key,),
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_record(row) if row else None

    async def get_latest_job_for_keys(self, file_keys: list[str]) -> dict[str, "JobRecord"]:
        """Return the latest job for each file_key in the list. Returns {file_key: JobRecord}."""
        if not file_keys:
            return {}
        placeholders = ",".join("?" * len(file_keys))
        db = await self._conn()
        # 取每个 file_key 最新提交的任务
        async with db.execute(
            f"""
            SELECT * FROM jobs
            WHERE file_key IN ({placeholders})
            AND submitted_at = (
                SELECT MAX(submitted_at) FROM jobs j2 WHERE j2.file_key = jobs.file_key
            )
            """,
            file_keys,
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["file_key"]: _row_to_record(row) for row in rows}

    async def list_pending_and_running(self) -> list[JobRecord]:
        """Return all jobs with status pending or running, ordered by submitted_at."""
        db = await self._conn()
        async with db.execute(
            "SELECT * FROM jobs WHERE status IN ('pending', 'running') ORDER BY submitted_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_record(r) for r in rows]

    async def delete_jobs(self, job_ids: list[str]) -> int:
        """Delete jobs by job_id list. Returns number of deleted rows."""
        if not job_ids:
            return 0
        placeholders = ",".join("?" * len(job_ids))
        db = await self._conn()
        cursor = await db.execute(
            f"DELETE FROM jobs WHERE job_id IN ({placeholders})", job_ids
        )
        await db.commit()
        return cursor.rowcount
