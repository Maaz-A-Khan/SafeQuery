"""The one call views make to answer a question. Owner: Maaz.

Keeps Django on this side: loads the connection, hands a plain `Target` to the
Django-free pipeline, then writes the audit log.
"""

from __future__ import annotations

import logging

from django.conf import settings

from agent import pipeline
from agent.types import Result, Target
from core.audit import service as audit

logger = logging.getLogger(__name__)


class ConnectionCache:
    """`agent.types.QueryCache` bound to one connection."""

    def __init__(self, connection_id: int):
        self.connection_id = connection_id

    def lookup(self, question: str, schema_hash: str) -> str | None:
        return audit.cache_lookup(self.connection_id, question, schema_hash)

    def save(self, question: str, schema_hash: str, sql: str) -> None:
        audit.cache_save(self.connection_id, question, schema_hash, sql)


def load_target(connection_id: int) -> Target:
    """Decrypt the URL and load the latest SchemaSnapshot."""
    raise NotImplementedError("Phase 5")


def answer_question(connection_id: int, question: str) -> Result:
    config = settings.SAFEQUERY
    cache = ConnectionCache(connection_id) if config.switches.cache else None
    result = pipeline.run(load_target(connection_id), question, config, cache)
    try:
        audit.log_request(connection_id, result)
    except Exception:
        logger.exception("Audit log write failed")  # never blocks the answer (NFR-R3)
    return result
