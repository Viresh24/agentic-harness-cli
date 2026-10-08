"""RunStore: run state and task results in SQLite, per-task artifacts in folders under HARNESS_HOME."""

import dataclasses
import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from agentic_harness.models import RunRecord, TaskResult

JSON_COLUMNS = {"task_ids", "config", "details"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    task_ids TEXT NOT NULL,
    status TEXT NOT NULL,
    config TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    pid INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS task_results (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    task_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL,
    passed INTEGER NOT NULL,
    score REAL NOT NULL,
    error TEXT,
    error_phase TEXT,
    duration REAL NOT NULL,
    agent_exit_status TEXT,
    started_at REAL,
    finished_at REAL,
    details TEXT NOT NULL,
    PRIMARY KEY (run_id, task_id)
);
"""


class RunStore:
    def __init__(self, root: Path | None = None):
        """Open (creating if needed) the store under root, defaulting to $HARNESS_HOME or ./runs."""
        self.root = Path(root or os.environ.get("HARNESS_HOME", "runs")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "harness.db"
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)

    def create_run(self, agent: str, benchmark: str, task_ids: list[str], config: dict | None = None) -> RunRecord:
        """Record a new queued run with one pending result per task."""
        run = RunRecord(uuid.uuid4().hex[:8], agent, benchmark, list(task_ids), config=config or {})
        with closing(self._connect()) as conn, conn:
            _insert(conn, "runs", _row(run))
            for seq, task_id in enumerate(task_ids):
                _insert(conn, "task_results", {"run_id": run.run_id, "seq": seq, **_row(TaskResult(task_id))})
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        """Look up a run by id."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunRecord.from_dict(_decode(row)) if row else None

    def update_run(self, run_id: str, **fields: Any) -> None:
        """Change fields of an existing run."""
        run = dataclasses.replace(self.get_run(run_id), **fields)  # TypeError on unknown fields
        row = _row(run)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                f"UPDATE runs SET {', '.join(f'{k} = ?' for k in row)} WHERE run_id = ?", [*row.values(), run_id]
            )

    def save_task_result(self, run_id: str, result: TaskResult) -> None:
        """Insert or replace one task's result, keeping its position in the run."""
        row = _row(result)
        cols = ", ".join(["run_id", "seq", *row])
        updates = ", ".join(f"{k} = excluded.{k}" for k in row)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                f"INSERT INTO task_results ({cols}) "
                f"VALUES (?, (SELECT COALESCE(MAX(seq) + 1, 0) FROM task_results WHERE run_id = ?), "
                f"{', '.join('?' * len(row))}) "
                f"ON CONFLICT (run_id, task_id) DO UPDATE SET {updates}",
                [run_id, run_id, *row.values()],
            )

    def get_task_results(self, run_id: str) -> list[TaskResult]:
        """All of a run's task results, in task order."""
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM task_results WHERE run_id = ? ORDER BY seq", (run_id,)).fetchall()
        return [TaskResult.from_dict(_decode(r)) for r in rows]

    def artifacts_dir(self, run_id: str, task_id: str | None = None) -> Path:
        """Folder for a run's (or one task's) artifacts, created on access."""
        path = self.root / run_id if task_id is None else self.root / run_id / "tasks" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _connect(self) -> sqlite3.Connection:
        # A fresh connection per call: the CLI and the background executor use the DB concurrently.
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _row(model: RunRecord | TaskResult) -> dict[str, Any]:
    return {k: json.dumps(v) if k in JSON_COLUMNS else v for k, v in model.to_dict().items()}


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    return {k: json.loads(row[k]) if k in JSON_COLUMNS else row[k] for k in row.keys()}


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
