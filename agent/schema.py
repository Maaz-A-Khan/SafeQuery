"""Introspection, sample values, DDL rendering. Owner: Maaz (Phase 5)."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from agent.config import AgentConfig
from agent.types import Schema


def introspect(engine: Engine, config: AgentConfig) -> Schema:
    """Tables, columns, types, keys and low-cardinality sample values (FR-C6, FR-C7),
    with the default restricted list applied (FR-C8)."""
    raise NotImplementedError("Phase 5")


def default_restricted(table_names: set[str], patterns: tuple[str, ...]) -> set[str]:
    raise NotImplementedError("Phase 5")


def render_ddl(schema: Schema) -> str:
    """The schema as CREATE TABLE statements, sample values in comments, for the prompt."""
    raise NotImplementedError("Phase 5")
