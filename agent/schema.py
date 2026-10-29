"""Introspection, sample values, DDL rendering. Owner: Maaz (Phase 5)."""

from __future__ import annotations

import logging
import re

from sqlalchemy import column, func, inspect, select, table
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.types import String

from agent.config import AgentConfig, ValidatorConfig
from agent.types import Column, Dialect, ForeignKey, Schema, Table

logger = logging.getLogger(__name__)

SAMPLE_VALUE_MAX_LENGTH = 100   # a column with longer values gets no samples (keeps the prompt short)

_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def introspect(engine: Engine, config: AgentConfig, previous: Schema | None = None) -> Schema:
    """Tables (default schema only), columns, types and keys (FR-C6), the default
    restricted tables and columns (FR-C8), and low-cardinality sample values,
    skipping restricted ones (FR-C7).

    On a refresh, pass the previous schema: tables and columns it already knew keep
    the user's restricted choices; only new ones get the defaults."""
    schema = _read_structure(engine)
    tables, columns = default_restricted(schema, config.validator)
    if previous is not None:
        tables, columns = _carry_over(schema, previous, tables, columns)
    schema.restricted_tables, schema.restricted_columns = tables, columns
    _add_samples(engine, schema, config.sample_values_max_distinct)
    return schema


def _read_structure(engine: Engine) -> Schema:
    insp = inspect(engine)
    dialect = Dialect(engine.dialect.name if engine.dialect.name != "mariadb" else "mysql")
    tables = {}
    for name in sorted(insp.get_table_names()):   # tables only; views are not read
        pk = set(insp.get_pk_constraint(name).get("constrained_columns") or ())
        cols = tuple(
            Column(c["name"], _type_name(c["type"]), bool(c.get("nullable", True)), c["name"] in pk)
            for c in insp.get_columns(name)
        )
        fks = tuple(
            ForeignKey(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            for fk in insp.get_foreign_keys(name)
            if fk.get("referred_table") and fk.get("constrained_columns")
        )
        tables[name] = Table(name, cols, fks)
    return Schema(dialect, tables)


def _type_name(type_) -> str:
    try:
        return str(type_)
    except Exception:   # some types cannot render without a dialect
        return type(type_).__name__.upper()


def _carry_over(schema: Schema, previous: Schema, tables: set[str], columns: set[str]) -> tuple[set[str], set[str]]:
    new_tables = {t for t in tables if t not in previous.tables}
    new_tables |= {t for t in previous.restricted_tables if t in schema.tables}
    new_columns = set()
    for t in schema.tables.values():
        known = {c.name for c in previous.tables[t.name].columns} if t.name in previous.tables else set()
        for c in t.columns:
            key = f"{t.name}.{c.name}"
            if c.name in known:
                if key in previous.restricted_columns:
                    new_columns.add(key)
            elif key in columns:
                new_columns.add(key)
    return new_tables, new_columns


def _add_samples(engine: Engine, schema: Schema, max_distinct: int) -> None:
    """Replace each table with a copy whose short text columns carry their distinct
    values. Restricted tables and columns are never queried."""
    for name, t in schema.tables.items():
        if name in schema.restricted_tables:
            continue
        restricted = schema.restricted_columns_of(name)
        cols = []
        for c in t.columns:
            values = ()
            if c.name not in restricted and _is_text(c.type):
                values = _distinct_values(engine, name, c.name, max_distinct)
            cols.append(Column(c.name, c.type, c.nullable, c.primary_key, values))
        schema.tables[name] = Table(name, tuple(cols), t.foreign_keys)


def _is_text(type_name: str) -> bool:
    return bool(re.search(r"CHAR|TEXT|STRING|ENUM|CLOB", type_name, re.IGNORECASE))


def _distinct_values(engine: Engine, table_name: str, column_name: str, max_distinct: int) -> tuple[str, ...]:
    """The column's values if it looks like a category: at most `max_distinct` of them,
    and at least half the rows share their value with another row. A column whose
    values are mostly different (names, phone numbers in a small table) is per-row
    data, not a category, so it gets none (D-029)."""
    col = column(column_name, String)
    query = (select(col, func.count()).select_from(table(table_name)).where(col.is_not(None))
             .group_by(col).limit(max_distinct + 1))
    try:
        with engine.connect() as conn:
            rows = [(str(v), n) for v, n in conn.execute(query)]
    except SQLAlchemyError as exc:   # e.g. the timeout on a huge table: no samples for this column
        logger.warning("Skipped sample values for %s.%s: %s", table_name, column_name, type(exc).__name__)
        return ()
    repeated = sum(n for _, n in rows if n > 1)
    if (len(rows) > max_distinct or repeated * 2 < sum(n for _, n in rows)
            or any(len(v) > SAMPLE_VALUE_MAX_LENGTH for v, _ in rows)):
        return ()
    return tuple(sorted(v for v, _ in rows))


def name_words(name: str) -> list[str]:
    """Split a name into lower-case words on "_" and case changes:
    "auth_user" -> ["auth", "user"], "UserCredentials" -> ["user", "credentials"]."""
    return [w.lower() for w in _WORD.findall(name)]


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    words = set(name_words(name))
    return any(w in words for p in patterns for w in (p, p + "s", p + "es"))


def default_restricted(schema: Schema, config: ValidatorConfig) -> tuple[set[str], set[str]]:
    """(restricted tables, restricted "table.column" names): a name is restricted when
    one of its words equals a pattern, singular or plural (FR-C8)."""
    tables = {name for name in schema.tables if _matches(name, config.restricted_table_patterns)}
    columns = {
        f"{t.name}.{c.name}"
        for t in schema.tables.values()
        for c in t.columns
        if _matches(c.name, config.restricted_column_patterns)
    }
    return tables, columns


def _ident(name: str, dialect: Dialect) -> str:
    """Quote a name only where the dialect needs it, so the prompt shows how to write it."""
    plain = r"[a-z_][a-z0-9_]*" if dialect == Dialect.POSTGRESQL else r"[A-Za-z_][A-Za-z0-9_]*"
    if re.fullmatch(plain, name):
        return name
    if dialect == Dialect.MYSQL:
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_ddl(schema: Schema) -> str:
    """The schema as CREATE TABLE statements, sample values in comments, for the prompt.
    Restricted tables and columns are left out."""
    d = schema.dialect
    statements = []
    for name, t in schema.tables.items():
        if name in schema.restricted_tables:
            continue
        hidden = schema.restricted_columns_of(name)
        cols = [c for c in t.columns if c.name not in hidden]
        pk = [c.name for c in cols if c.primary_key]
        inline_fk = {}
        table_fks = []
        for fk in t.foreign_keys:
            if (fk.ref_table in schema.restricted_tables or set(fk.columns) & hidden
                    or set(fk.ref_columns) & schema.restricted_columns_of(fk.ref_table)):
                continue
            ref = f"{_ident(fk.ref_table, d)}({', '.join(_ident(c, d) for c in fk.ref_columns)})"
            if len(fk.columns) == 1:
                inline_fk[fk.columns[0]] = ref
            else:
                table_fks.append(f"FOREIGN KEY ({', '.join(_ident(c, d) for c in fk.columns)}) REFERENCES {ref}")

        lines = []   # (definition, comment)
        for c in cols:
            parts = [_ident(c.name, d), c.type]
            if not c.nullable:
                parts.append("NOT NULL")
            if c.primary_key and len(pk) == 1:
                parts.append("PRIMARY KEY")
            if c.name in inline_fk:
                parts.append(f"REFERENCES {inline_fk[c.name]}")
            comment = f"-- e.g. {', '.join(_literal(v) for v in c.sample_values)}" if c.sample_values else ""
            lines.append((" ".join(parts), comment))
        if len(pk) > 1:
            lines.append((f"PRIMARY KEY ({', '.join(_ident(c, d) for c in pk)})", ""))
        lines += [(fk, "") for fk in table_fks]

        body = []
        for i, (definition, comment) in enumerate(lines):
            sep = "," if i < len(lines) - 1 else ""
            body.append(f"  {definition}{sep}" + (f" {comment}" if comment else ""))
        statements.append(f"CREATE TABLE {_ident(name, d)} (\n" + "\n".join(body) + "\n);")
    return "\n\n".join(statements)
