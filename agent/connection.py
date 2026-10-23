"""Engine creation, privilege check, read-only mode, encryption. Owner: Maaz (Phase 5)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from agent.config import AgentConfig
from agent.types import Dialect


class UnsupportedDatabase(ValueError):
    """Raised for any dialect other than PostgreSQL, MySQL or SQLite (FR-C2)."""


@dataclass
class PrivilegeReport:
    readonly: bool
    writable_tables: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)   # e.g. "account is a superuser"
    grant_sql: str = ""                                # how to create a read-only user


def detect_dialect(url: str) -> Dialect:
    raise NotImplementedError("Phase 5")


def open_engine(url: str, config: AgentConfig) -> Engine:
    """Engine whose every connection is read-only (FR-C5), with the timeout enforced
    on the database side: PostgreSQL statement_timeout, MySQL max_execution_time,
    MariaDB max_statement_time, SQLite a progress handler. SQLite URLs are rewritten
    to read-only file mode (mode=ro)."""
    raise NotImplementedError("Phase 5")


def check_privileges(engine: Engine) -> PrivilegeReport:
    """Refuse accounts that can write (FR-C4). PostgreSQL: role flags, table- and
    column-level grants, CREATE on any schema. MySQL: SHOW GRANTS, including roles."""
    raise NotImplementedError("Phase 5")


def mask_url(url: str) -> str:
    """The URL with its password hidden, for error messages (FR-C3)."""
    raise NotImplementedError("Phase 5")


def encrypt_url(url: str, key: str) -> bytes:
    raise NotImplementedError("Phase 5")


def decrypt_url(token: bytes, key: str) -> str:
    raise NotImplementedError("Phase 5")
