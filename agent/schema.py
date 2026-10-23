"""Introspection, sample values, DDL rendering. Owner: Maaz (Phase 5)."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from agent.config import AgentConfig, ValidatorConfig
from agent.types import Schema


def introspect(engine: Engine, config: AgentConfig) -> Schema:
    """Tables (default schema only), columns, types and keys (FR-C6), the default
    restricted tables and columns (FR-C8), and low-cardinality sample values,
    skipping restricted ones (FR-C7)."""
    raise NotImplementedError("Phase 5")


def name_words(name: str) -> list[str]:
    """Split a name into lower-case words on "_" and case changes:
    "auth_user" -> ["auth", "user"], "UserCredentials" -> ["user", "credentials"]."""
    raise NotImplementedError("Phase 5")


def default_restricted(schema: Schema, config: ValidatorConfig) -> tuple[set[str], set[str]]:
    """(restricted tables, restricted "table.column" names): a name is restricted when
    one of its words equals a pattern, singular or plural (FR-C8)."""
    raise NotImplementedError("Phase 5")


def render_ddl(schema: Schema) -> str:
    """The schema as CREATE TABLE statements, sample values in comments, for the prompt.
    Restricted tables and columns are left out."""
    raise NotImplementedError("Phase 5")
