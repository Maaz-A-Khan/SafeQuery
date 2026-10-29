"""Audit log and query cache. Owner: Sunil (Phase 3).

`log_request`, `cache_lookup` and `cache_save` are the interface `core.services`
calls; keep their signatures.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import asdict
from datetime import timedelta

import sqlglot
from django.utils import timezone
from sqlglot import exp

from agent.types import Outcome, Result
from core.audit.models import QueryCache, QueryLog
from core.models import DatabaseConnection

logger = logging.getLogger(__name__)

MANY_TABLES = 5            # FR-L3: more than this many tables
ROW_SPIKE_FACTOR = 5       # FR-L3: more than this times the median row count
ROW_SPIKE_MIN_HISTORY = 3  # answered questions needed before judging a spike
ROW_SPIKE_HISTORY = 200    # most recent answered questions used for the median
BLOCK_WINDOW = timedelta(minutes=10)
BLOCKS_BEFORE_FLAG = 2     # two earlier blocks in the window: this one is the third

SQLGLOT_DIALECTS = {"postgresql": "postgres", "mysql": "mysql", "sqlite": "sqlite"}


# --- Anomaly flags (FR-L3) -------------------------------------------------------


def _count_tables(sql: str | None, dialect: str | None) -> int:
    """Distinct real tables across every statement in the SQL (CTE names excluded).
    Unparseable SQL counts as 0: a flag never stops the log write."""
    if not sql:
        return 0
    try:
        trees = [t for t in sqlglot.parse(sql, dialect=SQLGLOT_DIALECTS.get(dialect)) if t is not None]
    except Exception:
        return 0
    tables = set()
    for tree in trees:
        ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
        tables |= {(t.db, t.name) for t in tree.find_all(exp.Table) if t.name and t.name not in ctes}
    return len(tables)


def _row_spike(connection_id: int, rows_returned: int | None) -> bool:
    """More than 5x the median row count of this connection's recent answered
    questions. Empty results are left out of the median: otherwise a history of
    0-row answers makes every non-empty answer a spike."""
    if not rows_returned:
        return False
    past = list(
        QueryLog.objects.filter(connection_id=connection_id, rows_returned__gt=0)
        .order_by("-created_at")
        .values_list("rows_returned", flat=True)[:ROW_SPIKE_HISTORY]
    )
    if len(past) < ROW_SPIKE_MIN_HISTORY:
        return False
    return rows_returned > ROW_SPIKE_FACTOR * statistics.median(past)


def _repeated_block(connection_id: int) -> bool:
    """This block is the third (or later) on this connection within 10 minutes."""
    earlier = QueryLog.objects.filter(
        connection_id=connection_id,
        verdict=Outcome.BLOCKED.value,
        created_at__gte=timezone.now() - BLOCK_WINDOW,
    ).count()
    return earlier >= BLOCKS_BEFORE_FLAG


def anomaly_flags(connection_id: int, dialect: str | None, result: Result) -> list[str]:
    flags = []
    # Every attempt counts: a blocked query has no final SQL but is the one to flag.
    if any(_count_tables(sql, dialect) > MANY_TABLES for sql in [result.sql, *(a.sql for a in result.attempts)]):
        flags.append("many_tables")
    if _row_spike(connection_id, result.rows_returned):
        flags.append("row_spike")
    if result.outcome == Outcome.BLOCKED and _repeated_block(connection_id):
        flags.append("repeated_blocks")
    return flags


# --- Log (FR-L1, FR-L2) ------------------------------------------------------------


def _final_sql(result: Result) -> str:
    """The SQL that ran; if nothing ran, the last SQL generated."""
    if result.sql:
        return result.sql
    generated = [a.sql for a in result.attempts if a.sql]
    return generated[-1] if generated else ""


def log_request(connection_id: int, result: Result) -> int | None:
    """Write one `QueryLog` row per question (FR-L1) and return its id, or None if
    the write failed (the CSV link needs the id).

    Never stores `result.rows` or a connection string (FR-L2). A failed write is
    logged and swallowed so it never stops the answer (NFR-R3).
    """
    try:
        dialect = (
            DatabaseConnection.objects.filter(pk=connection_id).values_list("dialect", flat=True).first()
        )
        entry = QueryLog.objects.create(
            connection_id=connection_id,
            question=result.question,
            plan_json=result.plan or None,
            final_sql=_final_sql(result),
            # Attempts hold SQL, verdicts and errors only; json round trip turns tuples into lists.
            attempts_json=[json.loads(json.dumps(asdict(a))) for a in result.attempts],
            verdict=result.outcome.value,
            stopped_by=result.stopped_by.value,
            message=result.message,
            from_cache=result.from_cache,
            rules_fired=result.rules_fired,
            attempt_count=result.attempt_count,
            rows_returned=result.rows_returned,
            exec_ms=result.exec_ms,
            anomaly_flags=anomaly_flags(connection_id, dialect, result),
        )
        return entry.id
    except Exception:
        logger.exception("Could not write audit log row")
        return None


# --- Cache (FR-L4) -----------------------------------------------------------------


def normalise_question(question: str) -> str:
    """Cache key: lowercased, whitespace collapsed."""
    return " ".join(question.lower().split())


def cache_lookup(connection_id: int, question: str, schema_hash: str) -> str | None:
    """Stored SQL for this question on this exact schema, or None (FR-L4).
    The caller still validates it before it runs."""
    entry = QueryCache.objects.filter(
        connection_id=connection_id,
        question_normalised=normalise_question(question),
        schema_hash=schema_hash,
    ).first()
    return entry.sql if entry else None


def cache_save(connection_id: int, question: str, schema_hash: str, sql: str) -> None:
    """Called only for answered questions, never for blocked or failed ones."""
    QueryCache.objects.update_or_create(
        connection_id=connection_id,
        question_normalised=normalise_question(question),
        schema_hash=schema_hash,
        defaults={"sql": sql},
    )
