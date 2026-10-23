"""Generation and correction prompts, Gemini client. Owner: Maaz (Phase 6)."""

from __future__ import annotations

from dataclasses import dataclass

from agent.config import GeminiConfig
from agent.types import Dialect


class ModelUnavailable(RuntimeError):
    """Gemini outage, quota limit or network error (FR-Q10). Never retried automatically."""


@dataclass
class Generation:
    sql: str | None        # None when Gemini says the schema cannot answer the question
    explanation: str


def generate(
    question: str,
    schema_ddl: str,
    dialect: Dialect,
    config: GeminiConfig,
    *,
    failed_sql: str | None = None,
    error: str | None = None,
) -> Generation:
    """Generation prompt; with `failed_sql` and `error`, the correction prompt."""
    raise NotImplementedError("Phase 6")


def plan(question: str, table_names: list[str], dialect: Dialect, config: GeminiConfig) -> list[str]:
    """Planner prompt (FR-Q8): 1 to `config.max_plan_steps` sub-questions; one step
    whenever a single query can answer the question."""
    raise NotImplementedError("Phase 6")
