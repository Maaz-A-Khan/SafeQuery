"""Dialect detection, read-only engines, the privilege check and credentials (Phase 5)."""

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from agent.config import AgentConfig, ExecutorConfig
from agent.connection import (
    UnsupportedDatabase, check_privileges, decrypt_url, detect_dialect, encrypt_url, mask_url,
    mysql_grant_problems, open_engine, safe_error,
)
from agent.types import Dialect

FAST = AgentConfig(executor=ExecutorConfig(statement_timeout_s=0.3))
SLOW_SQLITE = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT COUNT(*) FROM n"


@pytest.mark.parametrize("url,dialect", [
    ("postgresql://u:p@localhost/db", Dialect.POSTGRESQL),
    ("postgresql+psycopg://u:p@localhost:5432/db", Dialect.POSTGRESQL),
    ("mysql+pymysql://u:p@localhost/db", Dialect.MYSQL),
    ("mariadb://u:p@localhost/db", Dialect.MYSQL),
    ("sqlite:///C:/data/shop.db", Dialect.SQLITE),
])
def test_detect_dialect(url, dialect):
    assert detect_dialect(url) == dialect


@pytest.mark.parametrize("url", ["mssql+pyodbc://u:p@host/db", "oracle://u:p@host/db", "not a url", ""])
def test_unsupported_databases_are_rejected(url):
    with pytest.raises(UnsupportedDatabase, match="Supported databases"):
        detect_dialect(url)


def test_mask_url_hides_the_password():
    masked = mask_url("postgresql+psycopg://agent_ro:s3cret@localhost:5432/chinook")
    assert "s3cret" not in masked and "agent_ro" in masked and "chinook" in masked


def test_safe_error_removes_the_password():
    url = "postgresql://agent_ro:s3cret@localhost/chinook"
    assert "s3cret" not in safe_error(RuntimeError("login failed for s3cret"), url)


def test_encryption_round_trip():
    key = Fernet.generate_key().decode()
    token = encrypt_url("sqlite:///shop.db", key)
    assert b"shop" not in token
    assert decrypt_url(memoryview(token), key) == "sqlite:///shop.db"
    with pytest.raises(InvalidToken):
        decrypt_url(token, Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="FERNET_KEY"):
        encrypt_url("sqlite:///shop.db", "")


# --- SQLite ---------------------------------------------------------------------


def test_sqlite_is_opened_read_only(shop_url):
    engine = open_engine(shop_url, FAST)
    assert engine.url.query["mode"] == "ro"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar() == 5
        with pytest.raises(OperationalError, match="readonly"):
            conn.execute(text("DELETE FROM orders"))


def test_sqlite_write_mode_in_the_url_is_overridden(shop_db):
    engine = open_engine(f"sqlite:///file:{shop_db.as_posix()}?mode=rwc&uri=true", FAST)
    assert engine.url.query["mode"] == "ro"
    with engine.connect() as conn, pytest.raises(OperationalError):
        conn.execute(text("CREATE TABLE x (a INTEGER)"))


def test_sqlite_in_memory_is_rejected():
    with pytest.raises(UnsupportedDatabase):
        open_engine("sqlite://", FAST)


def test_sqlite_missing_file_fails_to_connect(tmp_path):
    engine = open_engine(f"sqlite:///{(tmp_path / 'nope.db').as_posix()}", FAST)
    with pytest.raises(OperationalError):
        engine.connect()


def test_sqlite_timeout_stops_a_runaway_query(shop_url):
    with open_engine(shop_url, FAST).connect() as conn, pytest.raises(OperationalError, match="interrupted"):
        conn.execute(text(SLOW_SQLITE)).scalar()


def test_sqlite_has_no_accounts_to_check(shop_url):
    assert check_privileges(open_engine(shop_url, FAST)).readonly


# --- MySQL grants (no server needed) ----------------------------------------------


def test_mysql_select_only_is_read_only():
    lines = ["GRANT USAGE ON *.* TO `agent_ro`@`localhost`",
             "GRANT SELECT ON `shop`.* TO `agent_ro`@`localhost`"]
    assert mysql_grant_problems(lines) == ([], [])


def test_mysql_write_and_admin_grants_are_reported():
    lines = [
        "GRANT SELECT, INSERT, UPDATE (`status`) ON `shop`.`orders` TO `app`@`%`",
        "GRANT FILE, PROCESS ON *.* TO `app`@`%`",
        "GRANT SYSTEM_VARIABLES_ADMIN ON *.* TO `app`@`%`",
        "GRANT ALL PRIVILEGES ON `crm`.* TO `app`@`%` WITH GRANT OPTION",
        "GRANT `reporting`@`%` TO `app`@`%`",
    ]
    writable, reasons = mysql_grant_problems(lines)
    assert writable == ["shop.orders", "crm.*"]
    assert reasons == ["has FILE, PROCESS on *.*", "has SYSTEM_VARIABLES_ADMIN on *.*"]


# --- PostgreSQL (the app database's own account, which can write) -----------------

needs_postgres = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


@needs_postgres
def test_postgres_sessions_are_read_only_with_a_timeout():
    with open_engine(os.environ["DATABASE_URL"], FAST).connect() as conn:
        assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "300ms"
        with pytest.raises(OperationalError, match="statement timeout"):
            conn.execute(text("SELECT pg_sleep(2)"))


@needs_postgres
def test_postgres_writable_account_is_refused():
    report = check_privileges(open_engine(os.environ["DATABASE_URL"], FAST))
    assert not report.readonly
    assert "account can create databases" in report.reasons   # the app role has CREATEDB for pytest
    assert "public.django_migrations" in report.writable_tables
    assert "GRANT SELECT ON ALL TABLES" in report.grant_sql


@pytest.mark.skipif(not os.environ.get("SAFEQUERY_TEST_RO_URL"),
                    reason="set SAFEQUERY_TEST_RO_URL to the agent_ro connection string")
def test_postgres_read_only_account_is_accepted():
    report = check_privileges(open_engine(os.environ["SAFEQUERY_TEST_RO_URL"], FAST))
    assert report.readonly, report
