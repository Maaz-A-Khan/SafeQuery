"""Engine creation, privilege check, read-only mode, encryption. Owner: Maaz (Phase 5)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import ArgumentError

from agent.config import AgentConfig
from agent.types import Dialect

SUPPORTED = "PostgreSQL, MySQL (or MariaDB) and SQLite"

# Bare dialect names map to the drivers in requirements.txt; SQLAlchemy's own
# defaults (psycopg2, mysqlclient) are not installed.
DEFAULT_DRIVERS = {"postgresql": "postgresql+psycopg", "mysql": "mysql+pymysql", "mariadb": "mariadb+pymysql"}

SQLITE_PROGRESS_STEPS = 1000   # SQLite VM instructions between timeout checks
CONNECT_TIMEOUT_S = 10          # seconds to reach a PostgreSQL or MySQL server


class UnsupportedDatabase(ValueError):
    """Raised for any dialect other than PostgreSQL, MySQL or SQLite (FR-C2)."""


@dataclass
class PrivilegeReport:
    readonly: bool
    writable_tables: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)   # e.g. "account is a superuser"
    grant_sql: str = ""                                # how to create a read-only user


def _parse(url: str) -> URL:
    try:
        return make_url(url)
    except ArgumentError:
        raise UnsupportedDatabase(f"Not a connection string. Supported databases: {SUPPORTED}.") from None


def detect_dialect(url: str) -> Dialect:
    backend = _parse(url).get_backend_name()
    if backend == "postgresql":
        return Dialect.POSTGRESQL
    if backend in ("mysql", "mariadb"):
        return Dialect.MYSQL
    if backend == "sqlite":
        return Dialect.SQLITE
    raise UnsupportedDatabase(f"{backend} is not supported. Supported databases: {SUPPORTED}.")


def _readonly_sqlite_url(u: URL) -> URL:
    """sqlite:///shop.db -> sqlite:///file:shop.db?mode=ro&uri=true; any mode given is replaced."""
    path = u.database or ""
    if path.startswith("file:"):
        path = path[len("file:"):]
    else:
        path = quote(path, safe="/:\\")   # a URI filename: escape spaces, '?' and '#'
    if not path or path == ":memory:":
        raise UnsupportedDatabase("SQLite needs a database file, e.g. sqlite:///C:/data/shop.db.")
    return u.set(database=f"file:{path}", query={**u.query, "mode": "ro", "uri": "true"})


def open_engine(url: str, config: AgentConfig) -> Engine:
    """Engine whose every connection is read-only (FR-C5), with the timeout enforced
    on the database side: PostgreSQL statement_timeout, MySQL max_execution_time,
    MariaDB max_statement_time, SQLite a progress handler. SQLite URLs are rewritten
    to read-only file mode (mode=ro)."""
    dialect = detect_dialect(url)
    u = _parse(url)
    if u.drivername in DEFAULT_DRIVERS:
        u = u.set(drivername=DEFAULT_DRIVERS[u.drivername])
    if dialect == Dialect.SQLITE:
        u = _readonly_sqlite_url(u)

    # A server that never answers must not hang the Connect page.
    connect_args = {} if dialect == Dialect.SQLITE else {"connect_timeout": CONNECT_TIMEOUT_S}
    engine = create_engine(u, pool_pre_ping=dialect != Dialect.SQLITE, connect_args=connect_args)
    timeout_s = config.executor.statement_timeout_s
    readonly = config.switches.readonly_session

    if dialect == Dialect.SQLITE:
        _install_sqlite_guards(engine, timeout_s, readonly)
        return engine

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        if dialect == Dialect.POSTGRESQL:
            cur.execute(f"SET statement_timeout = {int(timeout_s * 1000)}")
            if readonly:
                cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        else:
            cur.execute("SELECT VERSION()")
            if "mariadb" in str(cur.fetchone()[0]).lower():
                cur.execute(f"SET SESSION max_statement_time = {timeout_s}")
            else:
                cur.execute(f"SET SESSION max_execution_time = {int(timeout_s * 1000)}")
            if readonly:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.close()
        dbapi_conn.commit()   # the driver opened a transaction for the SETs

    return engine


def _install_sqlite_guards(engine: Engine, timeout_s: float, readonly: bool) -> None:
    """query_only on top of mode=ro, and a progress handler that aborts any
    statement running longer than `timeout_s` (SQLite has no server-side timeout)."""

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_conn, record):
        if readonly:
            dbapi_conn.execute("PRAGMA query_only = ON")
        info = record.info

        def over_time() -> int:
            started = info.get("started")
            return 1 if started is not None and time.monotonic() - started > timeout_s else 0

        dbapi_conn.set_progress_handler(over_time, SQLITE_PROGRESS_STEPS)

    @event.listens_for(engine, "before_cursor_execute")
    def start_clock(conn, *_args):
        conn.connection.info["started"] = time.monotonic()   # covers execute and the fetches after it


# --- Privilege check (FR-C4) ---------------------------------------------------

PG_ROLE_FLAGS = text(
    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname = current_user"
)
PG_WRITABLE_TABLES = text("""
    SELECT n.nspname || '.' || c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND (has_table_privilege(c.oid, 'INSERT')
        OR has_table_privilege(c.oid, 'UPDATE')
        OR has_table_privilege(c.oid, 'DELETE')
        OR has_table_privilege(c.oid, 'TRUNCATE')
        OR has_any_column_privilege(c.oid, 'INSERT')
        OR has_any_column_privilege(c.oid, 'UPDATE'))
    ORDER BY 1
""")
PG_CREATE_SCHEMAS = text("""
    SELECT nspname FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema')
      AND nspname NOT LIKE 'pg\\_%'
      AND has_schema_privilege(oid, 'CREATE')
    ORDER BY 1
""")
PG_CREATE_IN_DATABASE = text("SELECT has_database_privilege(current_database(), 'CREATE')")

PG_GRANT_SQL = """\
CREATE USER agent_ro WITH PASSWORD '...';
GRANT CONNECT ON DATABASE {db} TO agent_ro;
GRANT USAGE ON SCHEMA public TO agent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_ro;
ALTER ROLE agent_ro SET default_transaction_read_only = on;"""

MYSQL_GRANT_SQL = """\
CREATE USER 'agent_ro'@'localhost' IDENTIFIED BY '...';
GRANT SELECT ON {db}.* TO 'agent_ro'@'localhost';"""

# MySQL privileges a read-only agent must not hold (see Connection and Schema Discovery).
MYSQL_WRITE_PRIVILEGES = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "INDEX", "ALL", "ALL PRIVILEGES"}
MYSQL_OTHER_PRIVILEGES = {"FILE", "EXECUTE", "CREATE ROUTINE", "ALTER ROUTINE", "TRIGGER", "EVENT", "SUPER", "PROCESS"}

_GRANT_ON = re.compile(r"^GRANT\s+(?P<privs>.+?)\s+ON\s+(?P<target>.+?)\s+TO\s+", re.IGNORECASE | re.DOTALL)
_GRANT_ROLES = re.compile(r"^GRANT\s+(?P<roles>.+?)\s+TO\s+", re.IGNORECASE | re.DOTALL)


def check_privileges(engine: Engine) -> PrivilegeReport:
    """Refuse accounts that can write (FR-C4). PostgreSQL: role flags, table- and
    column-level grants, CREATE on any schema. MySQL: SHOW GRANTS, including roles."""
    dialect = Dialect(engine.dialect.name if engine.dialect.name != "mariadb" else "mysql")
    if dialect == Dialect.SQLITE:
        return PrivilegeReport(readonly=True)   # no accounts; the file is opened mode=ro
    with engine.connect() as conn:
        if dialect == Dialect.POSTGRESQL:
            writable, reasons = _postgres_problems(conn)
            grant_sql = PG_GRANT_SQL.format(db=engine.url.database or "yourdb")
        else:
            writable, reasons = mysql_grant_problems(_mysql_grants(conn))
            grant_sql = MYSQL_GRANT_SQL.format(db=engine.url.database or "yourdb")
    readonly = not writable and not reasons
    return PrivilegeReport(readonly, writable, reasons, "" if readonly else grant_sql)


def _postgres_problems(conn) -> tuple[list[str], list[str]]:
    reasons = []
    flags = conn.execute(PG_ROLE_FLAGS).one()
    for flag, label in zip(flags, ("is a superuser", "can create databases", "can create roles",
                                   "has the replication privilege")):
        if flag:
            reasons.append(f"account {label}")
    writable = list(conn.execute(PG_WRITABLE_TABLES).scalars())
    for schema in conn.execute(PG_CREATE_SCHEMAS).scalars():
        reasons.append(f"can create objects in schema {schema}")
    if conn.execute(PG_CREATE_IN_DATABASE).scalar():
        reasons.append("can create schemas in this database")
    return writable, reasons


def _mysql_grants(conn) -> list[str]:
    """SHOW GRANTS for the account, plus the grants of every role it holds."""
    lines = list(conn.execute(text("SHOW GRANTS FOR CURRENT_USER()")).scalars())
    roles = []
    for line in lines:
        m = None if _GRANT_ON.match(line.strip()) else _GRANT_ROLES.match(line.strip())
        if m:
            roles += _split_list(m.group("roles"))
    if roles:
        try:   # MySQL 8
            lines += conn.execute(text(f"SHOW GRANTS FOR CURRENT_USER() USING {', '.join(roles)}")).scalars()
        except Exception:   # MariaDB has no USING; a role's grants are shown directly
            conn.rollback()
            for role in roles:
                lines += conn.execute(text(f"SHOW GRANTS FOR {role}")).scalars()
    return lines


def _split_list(s: str) -> list[str]:
    """Split on commas outside parentheses: "SELECT, UPDATE (a, b)" -> two items."""
    items, depth, current = [], 0, ""
    for ch in s:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            items.append(current.strip())
            current = ""
        else:
            current += ch
    return [i for i in [*items, current.strip()] if i]


def mysql_grant_problems(lines: list[str]) -> tuple[list[str], list[str]]:
    """(writable targets, other reasons) from SHOW GRANTS output. Role grant lines
    (no ON clause) are skipped here; their grants are fetched separately."""
    writable, reasons = [], []
    for line in lines:
        m = _GRANT_ON.match(line.strip())
        if not m:
            continue
        target = m.group("target").replace("`", "")
        privs = {re.sub(r"\s*\(.*\)$", "", p).upper() for p in _split_list(m.group("privs"))}
        if privs & MYSQL_WRITE_PRIVILEGES and target not in writable:
            writable.append(target)
        other = sorted(p for p in privs if p in MYSQL_OTHER_PRIVILEGES or p.endswith("_ADMIN"))
        if other:
            reasons.append(f"has {', '.join(other)} on {target}")
    return writable, reasons


# --- Credentials (FR-C3, FR-C12) -----------------------------------------------


def mask_url(url: str) -> str:
    """The URL with its password hidden, for error messages (FR-C3)."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except ArgumentError:
        return re.sub(r"(://[^:/@]*:)[^@]*@", r"\1***@", url)


def safe_error(exc: BaseException, url: str) -> str:
    """The driver's error message, with the password removed if it appears in it."""
    message = str(getattr(exc, "orig", None) or exc).strip()
    try:
        password = make_url(url).password
    except ArgumentError:
        password = None
    if password:
        message = message.replace(password, "***").replace(quote(password, safe=""), "***")
    return message


def encrypt_url(url: str, key: str) -> bytes:
    if not key:
        raise ValueError("FERNET_KEY is missing from .env.")
    return Fernet(key).encrypt(url.encode())


def decrypt_url(token: bytes, key: str) -> str:
    if not key:
        raise ValueError("FERNET_KEY is missing from .env.")
    return Fernet(key).decrypt(bytes(token)).decode()   # bytes(): Postgres returns a memoryview
