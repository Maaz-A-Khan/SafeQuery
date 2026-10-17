"""Runs approved SQL: timeout, row cap, error capture. Owner: Maaz (Phase 6)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from agent.config import ExecutorConfig


class ExecutionError(RuntimeError):
    """The database rejected the query; the message is fed to the correction prompt."""


@dataclass
class Execution:
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    exec_ms: int


def execute(engine: Engine, sql: str, config: ExecutorConfig) -> Execution:
    raise NotImplementedError("Phase 6")
