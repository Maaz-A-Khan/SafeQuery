"""Audit log and query cache. Owner: Sunil (Phase 3).

These four functions are the interface `core.services` calls. Keep the
signatures; fill in the bodies.
"""

from __future__ import annotations

from agent.types import Result


def log_request(connection_id: int, result: Result) -> None:
    """Write one `QueryLog` row per question (FR-L1).

    Everything needed is on `result`: question, plan, sql, attempts (each with
    its verdict and error), outcome, stopped_by, rules_fired, attempt_count,
    rows_returned, exec_ms. Also computes the anomaly flags (FR-L3).

    Never store `result.rows` or a connection string (FR-L2). The caller catches
    exceptions so a failed write never stops the answer (NFR-R3), but don't rely
    on that for expected cases.
    """
    # TODO(Sunil)


def normalise_question(question: str) -> str:
    """Cache key: lowercased, whitespace collapsed."""
    return " ".join(question.lower().split())


def cache_lookup(connection_id: int, question: str, schema_hash: str) -> str | None:
    """Stored SQL for this question on this exact schema, or None (FR-L4).
    The caller still validates it before it runs."""
    # TODO(Sunil)
    return None


def cache_save(connection_id: int, question: str, schema_hash: str, sql: str) -> None:
    """Called only for answered questions, never for blocked or failed ones."""
    # TODO(Sunil)
