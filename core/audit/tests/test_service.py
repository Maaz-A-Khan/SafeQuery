import pytest

from agent.types import Attempt, Outcome, Result, StoppedBy
from core.audit.models import QueryCache, QueryLog
from core.audit.service import (
    cache_lookup,
    cache_save,
    log_request,
    normalise_question,
)
from core.models import DatabaseConnection

pytestmark = pytest.mark.django_db


@pytest.fixture
def conn():
    return DatabaseConnection.objects.create(
        name="test", url_encrypted=b"x", dialect="sqlite"
    )


def make_result(**kw):
    defaults = dict(
        question="Top 5 products",
        outcome=Outcome.ANSWERED,
        stopped_by=StoppedBy.NONE,
        sql="SELECT 1",
        attempts=[Attempt(number=1, sql="SELECT 1")],
        rows=[(1,), (2,)],
        exec_ms=5,
    )
    defaults.update(kw)
    return Result(**defaults)


def test_log_request_creates_row(conn):
    log_request(conn.id, make_result())
    row = QueryLog.objects.get()
    assert row.verdict == "answered"
    assert row.question == "Top 5 products"
    assert row.rows_returned == 2
    assert row.attempt_count == 1


def test_log_request_does_not_store_rows(conn):
    log_request(conn.id, make_result(rows=[("secret-data",)]))
    row = QueryLog.objects.get()
    assert "secret-data" not in str(row.attempts_json)
    assert "secret-data" not in row.final_sql


def test_many_tables_flag(conn):
    sql = "SELECT * FROM a JOIN b ON 1=1 JOIN c ON 1=1 JOIN d ON 1=1 JOIN e ON 1=1 JOIN f ON 1=1"
    log_request(conn.id, make_result(sql=sql))
    assert "many_tables" in QueryLog.objects.get().anomaly_flags


def test_third_block_flag(conn):
    blocked = make_result(
        outcome=Outcome.BLOCKED, stopped_by=StoppedBy.VALIDATOR, sql=None, rows=[]
    )
    for _ in range(3):
        log_request(conn.id, blocked)
    flags = [r.anomaly_flags for r in QueryLog.objects.order_by("id")]
    assert "repeated_blocks" not in flags[0]
    assert "repeated_blocks" not in flags[1]
    assert "repeated_blocks" in flags[2]


def test_many_rows_flag(conn):
    for _ in range(3):
        log_request(conn.id, make_result(rows=[(1,)] * 2))
    log_request(conn.id, make_result(rows=[(1,)] * 100))
    assert "row_spike" in QueryLog.objects.order_by("id").last().anomaly_flags


def test_normalise_question():
    assert normalise_question("  Top  5   PRODUCTS ") == "top 5 products"


def test_cache_miss_then_hit(conn):
    assert cache_lookup(conn.id, "Top 5", "hash1") is None
    cache_save(conn.id, "Top 5", "hash1", "SELECT 1")
    assert cache_lookup(conn.id, "  top   5 ", "hash1") == "SELECT 1"


def test_cache_miss_when_schema_changes(conn):
    cache_save(conn.id, "Top 5", "hash1", "SELECT 1")
    assert cache_lookup(conn.id, "Top 5", "hash2") is None


def test_cache_save_twice_updates(conn):
    cache_save(conn.id, "q", "h", "SELECT 1")
    cache_save(conn.id, "q", "h", "SELECT 2")
    assert QueryCache.objects.count() == 1
    assert cache_lookup(conn.id, "q", "h") == "SELECT 2"
def test_failed_log_write_does_not_raise(conn, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(QueryLog.objects, "create", boom)
    log_request(conn.id, make_result())  # must not raise