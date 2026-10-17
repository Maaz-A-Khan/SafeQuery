"""Question → answer: generate, validate, execute, correct. Owner: Maaz (Phase 6).

Views do not call this directly: they call `core.services.answer_question`,
which loads the connection, calls `run`, and writes the audit log.
"""

from __future__ import annotations

from agent.config import AgentConfig
from agent.types import QueryCache, Result, Target


def run(
    target: Target,
    question: str,
    config: AgentConfig,
    cache: QueryCache | None = None,
) -> Result:
    """Answer one question. Every query, including corrections and cache hits,
    passes `agent.validator.validate` before it runs. Blocked queries are never
    retried; database errors are corrected up to `config.gemini.max_attempts`."""
    raise NotImplementedError("Phase 6")
