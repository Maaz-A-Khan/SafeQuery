"""Running validated SQL: rows, row cap, errors, timeouts, EXPLAIN (Phase 6)."""

import os

import pytest

from agent.config import AgentConfig, ExecutorConfig
from agent.connection import open_engine
from agent.executor import ExecutionError, execute, explainer
from agent.types import Dialect

FAST = AgentConfig(executor=ExecutorConfig(statement_timeout_s=0.3, row_cap=3))


@pytest.fixture
def engine(shop_url):
    e = open_engine(shop_url, FAST)
    yield e
    e.dispose()


def test_rows_and_columns(engine):
    ex = execute(engine, "SELECT artist_id, name FROM artist ORDER BY artist_id", FAST.executor)
    assert ex.columns == ["artist_id", "name"]
    assert ex.rows == [(1, "AC/DC"), (2, "Accept")]
    assert not ex.truncated and ex.exec_ms >= 0


def test_row_cap_truncates(engine):
    ex = execute(engine, "SELECT order_id FROM orders ORDER BY order_id", FAST.executor)
    assert len(ex.rows) == 3 and ex.truncated


def test_percent_and_colon_in_strings_are_not_placeholders(engine):
    ex = execute(engine, "SELECT 'a%b', '10:30', ':x' FROM artist WHERE name LIKE 'A%' LIMIT 1", FAST.executor)
    assert ex.rows == [("a%b", "10:30", ":x")]


def test_database_error_is_an_execution_error(engine):
    with pytest.raises(ExecutionError, match="no such column"):
        execute(engine, "SELECT nme FROM artist", FAST.executor)


def test_sqlite_timeout_is_explained(engine):
    slow = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT COUNT(*) FROM n"
    with pytest.raises(ExecutionError, match="longer than 0.3 seconds"):
        execute(engine, slow, FAST.executor)


def test_writes_are_refused_by_the_database(engine):
    """Even if a write got past the validator, the read-only connection refuses it."""
    with pytest.raises(ExecutionError):
        execute(engine, "DELETE FROM orders", FAST.executor)
    assert len(execute(engine, "SELECT order_id FROM orders", AgentConfig().executor).rows) == 5


def test_engine_is_usable_after_an_error(engine):
    with pytest.raises(ExecutionError):
        execute(engine, "SELECT nope", FAST.executor)
    assert execute(engine, "SELECT 1", FAST.executor).rows == [(1,)]


def test_no_explain_for_sqlite(engine):
    assert explainer(engine, Dialect.SQLITE, FAST.executor) is None


@pytest.mark.skipif(not os.environ.get("SAFEQUERY_TEST_RO_URL"), reason="set SAFEQUERY_TEST_RO_URL to the agent_ro connection string")
def test_postgres_explain_and_percent():
    e = open_engine(os.environ["SAFEQUERY_TEST_RO_URL"], AgentConfig())
    try:
        plan = explainer(e, Dialect.POSTGRESQL, AgentConfig().executor)("SELECT name FROM artist LIMIT 1000")
        assert plan[0]["Plan"]["Total Cost"] > 0
        ex = execute(e, "SELECT name FROM artist WHERE name LIKE 'A%' ORDER BY name LIMIT 1", AgentConfig().executor)
        assert ex.rows and ex.rows[0][0].startswith("A")
    finally:
        e.dispose()
