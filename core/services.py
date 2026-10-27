"""What views call into the agent for. Owner: Maaz.

Keeps Django on this side: loads the connection, hands plain values to the
Django-free `agent` package, then writes the results (snapshots, audit log).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agent import pipeline
from agent.connection import (
    UnsupportedDatabase, check_privileges, decrypt_url, encrypt_url, open_engine, safe_error,
)
from agent.schema import introspect
from agent.types import Column, Dialect, Result, Schema, Table, Target
from core.audit import service as audit
from core.models import DatabaseConnection, SchemaSnapshot

logger = logging.getLogger(__name__)


class ConnectionCache:
    """`agent.types.QueryCache` bound to one connection."""

    def __init__(self, connection_id: int):
        self.connection_id = connection_id

    def lookup(self, question: str, schema_hash: str) -> str | None:
        return audit.cache_lookup(self.connection_id, question, schema_hash)

    def save(self, question: str, schema_hash: str, sql: str) -> None:
        audit.cache_save(self.connection_id, question, schema_hash, sql)


# --- Connect (FR-C1 to FR-C8) ---------------------------------------------------


def _check(ok: bool, message: str, error: str = "", writable_tables=(), grant_sql: str = "") -> dict:
    """The `check` dictionary of the Connect page (see sample_context.connect)."""
    return {"ok": ok, "message": message, "error": error,
            "writable_tables": list(writable_tables), "grant_sql": grant_sql}


def connect_database(name: str, url: str) -> tuple[dict, DatabaseConnection | None]:
    """Run every check on a pasted connection string and, if it passes, save the
    connection (URL encrypted) and its first schema snapshot. Returns the Connect
    page's `check` and the new connection, or None if it was refused."""
    config = settings.SAFEQUERY
    if not settings.FERNET_KEY:
        return _check(False, "FERNET_KEY is missing from .env, so the connection cannot be stored safely."), None
    try:
        engine = open_engine(url, config)
    except UnsupportedDatabase as exc:
        return _check(False, str(exc)), None
    except Exception as exc:   # e.g. a driver that is not installed
        return _check(False, "Could not open this connection string.", safe_error(exc, url)), None

    try:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            return _check(False, "Could not connect to the database.", safe_error(exc, url)), None

        dialect = _dialect_of(engine)
        readonly_verified = False
        if config.switches.privilege_check:
            try:
                report = check_privileges(engine)
            except SQLAlchemyError as exc:   # fail closed: an unreadable answer is a refusal
                return _check(False, "Could not check what this account may do, so it was refused.",
                              safe_error(exc, url)), None
            if not report.readonly:
                reasons = f" ({'; '.join(report.reasons)})" if report.reasons else ""
                return _check(False, f"This account can change data, so it was refused{reasons}.",
                              writable_tables=report.writable_tables, grant_sql=report.grant_sql), None
            readonly_verified = True

        try:
            schema = introspect(engine, config)
        except SQLAlchemyError as exc:
            return _check(False, "Connected, but could not read the database structure.",
                          safe_error(exc, url)), None
    finally:
        engine.dispose()

    with transaction.atomic():
        connection = DatabaseConnection.objects.create(
            name=name, url_encrypted=encrypt_url(url, settings.FERNET_KEY),
            dialect=dialect.value, readonly_verified=readonly_verified,
        )
        save_snapshot(connection, schema)
    what = "The file is opened read-only." if dialect == Dialect.SQLITE else "The account is read-only."
    return _check(True, f"Connected to {name}. {what}"), connection


def _dialect_of(engine) -> Dialect:
    return Dialect.MYSQL if engine.dialect.name == "mariadb" else Dialect(engine.dialect.name)


def save_snapshot(connection: DatabaseConnection, schema: Schema) -> SchemaSnapshot:
    return SchemaSnapshot.objects.create(
        connection=connection,
        schema_json=schema.to_json(),
        restricted_tables=sorted(schema.restricted_tables),
        restricted_columns=sorted(schema.restricted_columns),
        table_count=len(schema.tables),
    )


# --- Schema page (FR-C8, FR-C9) -----------------------------------------------


def latest_schema(connection: DatabaseConnection) -> tuple[SchemaSnapshot, Schema]:
    snapshot = connection.snapshots.latest()
    return snapshot, Schema.from_json(snapshot.schema_json, snapshot.restricted_tables, snapshot.restricted_columns)


def refresh_schema(connection: DatabaseConnection) -> str | None:
    """Re-read the structure and sample values (Refresh button). The user's restricted
    choices are kept for tables and columns already known. Returns an error or None."""
    _, previous = latest_schema(connection)
    url = decrypt_url(connection.url_encrypted, settings.FERNET_KEY)
    try:
        engine = open_engine(url, settings.SAFEQUERY)
    except Exception as exc:
        return safe_error(exc, url)
    try:
        schema = introspect(engine, settings.SAFEQUERY, previous)
    except SQLAlchemyError as exc:
        return safe_error(exc, url)
    finally:
        engine.dispose()
    save_snapshot(connection, schema)
    return None


def save_restricted(connection: DatabaseConnection, tables: list[str], columns: list[str]) -> None:
    """Store the user's restricted tables and columns. Sample values of anything
    newly restricted are dropped, so they are never sent to Gemini or kept."""
    snapshot, schema = latest_schema(connection)
    schema.restricted_tables = {t for t in tables if t in schema.tables}
    schema.restricted_columns = {
        c for c in columns
        if "." in c and c.split(".", 1)[0] in schema.tables
        and c.split(".", 1)[1] in {col.name for col in schema.tables[c.split(".", 1)[0]].columns}
    }
    for name, t in schema.tables.items():
        hidden = schema.restricted_columns_of(name)
        if name in schema.restricted_tables or hidden:
            schema.tables[name] = Table(name, tuple(
                Column(c.name, c.type, c.nullable, c.primary_key,
                       () if name in schema.restricted_tables or c.name in hidden else c.sample_values)
                for c in t.columns
            ), t.foreign_keys)
    snapshot.schema_json = schema.to_json()
    snapshot.restricted_tables = sorted(schema.restricted_tables)
    snapshot.restricted_columns = sorted(schema.restricted_columns)
    snapshot.save()


# --- Ask -----------------------------------------------------------------------


def load_target(connection_id: int) -> Target:
    """Decrypt the URL and load the latest SchemaSnapshot."""
    connection = DatabaseConnection.objects.get(pk=connection_id)
    _, schema = latest_schema(connection)
    url = decrypt_url(connection.url_encrypted, settings.FERNET_KEY)
    return Target(connection.id, Dialect(connection.dialect), schema, url)


def answer_question(connection_id: int, question: str) -> Result:
    config = settings.SAFEQUERY
    cache = ConnectionCache(connection_id) if config.switches.cache else None
    result = pipeline.run(load_target(connection_id), question, config, cache)
    try:
        audit.log_request(connection_id, result)
    except Exception:
        logger.exception("Audit log write failed")  # never blocks the answer (NFR-R3)
    return result
