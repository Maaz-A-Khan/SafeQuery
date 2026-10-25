"""Audit log and query cache. Owner: Sunil (Phase 3).
These four functions are the interface `core.services` calls. Keep the
signatures; fill in the bodies.
"""
from __future__ import annotations
import json
import statistics
from dataclasses import asdict
from datetime import timedelta
import sqlglot
from django.utils import timezone
from sqlglot import exp
from agent.types import Result
from core.audit.models import QueryCache, QueryLog
import logging
logger = logging.getLogger(__name__)


#Anomaly flag helpers

def _count_tables(sql: str | None) -> int:
    """Distinct real tables in the SQL (CTE names excluded)."""
    if not sql:
        return 0
    try:
        tree = sqlglot.parse_one(sql)
    except Exception:
        return 0
    cte_names = {c.alias for c in tree.find_all(exp.CTE)}
    tables = {t.name for t in tree.find_all(exp.Table) if t.name not in cte_names}
    return len(tables)

def _many_rows(connection_id: int, rows_returned: int | None) -> bool:
    """True if rows are more than 5x the median for this connection."""
    if not rows_returned:
        return False
    past = list(
        QueryLog.objects.filter(connection_id=connection_id, rows_returned__isnull=False)
        .values_list("rows_returned", flat=True)[:200]
    )
    if len(past) < 3:  # not enough history to judge
        return False
    return rows_returned > 5 * statistics.median(past)


def _third_block(connection_id: int) -> bool:
    """True if this blocked request is the 3rd block in the last 10 minutes."""
    since = timezone.now() - timedelta(minutes=10)
    earlier = QueryLog.objects.filter(
        connection_id=connection_id, verdict="blocked", created_at__gte=since
    ).count()
    return earlier >= 2  # two earlier blocks + this one = third


def log_request(connection_id: int, result: Result) -> None:
    """Write one `QueryLog` row per question (FR-L1).

    Never stores `result.rows` or a connection string (FR-L2).
    A failed write is logged and swallowed so it never stops the answer.
    """
    try:
        attempts = [json.loads(json.dumps(asdict(a))) for a in result.attempts]

        flags = []
        if _count_tables(result.sql) > 5:
            flags.append("many_tables")
        if _many_rows(connection_id, result.rows_returned):
            flags.append("row_spike")
        if result.outcome.value == "blocked" and _third_block(connection_id):
            flags.append("repeated_blocks")

        QueryLog.objects.create(
            connection_id=connection_id,
            question=result.question,
            plan_json=result.plan or None,
            final_sql=result.sql or "",
            attempts_json=attempts,
            verdict=result.outcome.value,
            rules_fired=result.rules_fired,
            attempt_count=result.attempt_count,
            rows_returned=result.rows_returned,
            exec_ms=result.exec_ms,
            anomaly_flags=flags,
        )
    except Exception:
        logger.exception("Could not write audit log row")
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