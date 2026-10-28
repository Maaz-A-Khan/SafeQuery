"""Runs approved SQL: row cap, error capture, EXPLAIN for R10. Owner: Maaz (Phase 6).

The engine comes from `agent.connection.open_engine`, which already makes every
connection read-only and enforces the 5-second timeout on the database side.

SQL goes to the DB-API cursor with no parameters, so the driver never reads
`%` or `:name` inside it as placeholders (psycopg rejects `LIKE 'A%'` otherwise).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.engine import Engine

from agent.config import ExecutorConfig
from agent.types import Dialect


class ExecutionError(RuntimeError):
    """The database rejected or stopped the query; the message is fed to the correction prompt."""


@dataclass
class Execution:
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    exec_ms: int


def _error_text(exc: BaseException, timeout_s: float) -> str:
    """The driver's own message, first line only, never the SQL or parameters."""
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    lowered = message.lower()
    if ("statement timeout" in lowered or "canceling statement" in lowered   # PostgreSQL
            or "maximum statement execution time" in lowered                  # MySQL / MariaDB
            or lowered == "interrupted"):                                     # SQLite progress handler
        return f"The query took longer than {timeout_s:g} seconds and was stopped."
    return message


def _run(engine: Engine, sql: str, timeout_s: float, fetch: Callable) -> tuple[list[str], list]:
    with engine.connect() as conn:
        fairy = conn.connection
        fairy.info["started"] = time.monotonic()   # SQLite's progress handler measures from here
        cursor = fairy.dbapi_connection.cursor()
        try:
            cursor.execute(sql)
            columns = [d[0] for d in cursor.description or ()]
            rows = fetch(cursor) if cursor.description else []
        finally:
            cursor.close()
            fairy.info.pop("started", None)
            conn.rollback()   # read-only anyway; leaves no transaction open
    return columns, rows


def execute(engine: Engine, sql: str, config: ExecutorConfig) -> Execution:
    """Run validated SQL and fetch at most `config.row_cap` rows (NFR-P4)."""
    started = time.perf_counter()
    try:
        columns, rows = _run(engine, sql, config.statement_timeout_s,
                             lambda cur: cur.fetchmany(config.row_cap + 1))
    except Exception as exc:
        raise ExecutionError(_error_text(exc, config.statement_timeout_s)) from exc
    exec_ms = int((time.perf_counter() - started) * 1000)
    truncated = len(rows) > config.row_cap
    return Execution(columns, [tuple(r) for r in rows[: config.row_cap]], truncated, exec_ms)


def explainer(engine: Engine, dialect: Dialect, config: ExecutorConfig) -> Callable[[str], object] | None:
    """The `explain` callable R10 needs: runs EXPLAIN (never executes the query) and
    returns the plan. None for SQLite, which has no cost estimate."""
    if dialect == Dialect.SQLITE:
        return None
    prefix = "EXPLAIN (FORMAT JSON) " if dialect == Dialect.POSTGRESQL else "EXPLAIN FORMAT=JSON "

    def explain(sql: str):
        _, rows = _run(engine, prefix + sql, config.statement_timeout_s, lambda cur: cur.fetchall())
        plan = rows[0][0] if rows else None
        return json.loads(plan) if isinstance(plan, (str, bytes)) else plan

    return explain
