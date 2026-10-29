"""Audit log fixes from the Phase 3 review: stopped_by, from_cache, flags, Log pages, admin."""

import pytest
from django.urls import reverse

from agent.types import Attempt, Outcome, Result, RuleHit, StoppedBy, Verdict
from core.audit.models import QueryLog
from core.audit.service import _count_tables, log_request
from core.models import DatabaseConnection

pytestmark = pytest.mark.django_db

SIX_TABLES = "SELECT 1 FROM a JOIN b ON 1=1 JOIN c ON 1=1 JOIN d ON 1=1 JOIN e ON 1=1 JOIN f ON 1=1"
R3 = RuleHit("R3", "Read-only statement", "block", "This system can only read data, not change it.")


@pytest.fixture
def conn():
    return DatabaseConnection.objects.create(name="Shop", url_encrypted=b"x", dialect="postgresql")


def blocked(sql="DROP TABLE invoice") -> Result:
    return Result("drop it", Outcome.BLOCKED, StoppedBy.VALIDATOR, message="Blocked.",
                  attempts=[Attempt(1, sql, verdict=Verdict(False, sql, (R3,)))])


def answered(rows: int, **kw) -> Result:
    return Result("q", Outcome.ANSWERED, StoppedBy.NONE, sql="SELECT 1",
                  attempts=[Attempt(1, "SELECT 1", verdict=Verdict(True, "SELECT 1"))],
                  rows=[(1,)] * rows, **kw)


def test_stopped_by_and_from_cache_are_stored(conn):
    log_request(conn.id, Result("weather?", Outcome.FAILED, StoppedBy.MODEL, attempts=[Attempt(1, None)]))
    log_request(conn.id, answered(2, from_cache=True))
    model, cached = QueryLog.objects.order_by("id")
    assert (model.stopped_by, model.from_cache) == ("model", False)
    assert (cached.stopped_by, cached.from_cache) == ("none", True)


def test_blocked_query_keeps_its_sql_and_is_flagged_for_many_tables(conn):
    log_request(conn.id, blocked(SIX_TABLES))
    row = QueryLog.objects.get()
    assert row.final_sql == SIX_TABLES
    assert "many_tables" in row.anomaly_flags
    assert row.rules_fired == ["R3"]


def test_service_failure_logs_zero_attempts(conn):
    log_request(conn.id, Result("q", Outcome.FAILED, StoppedBy.SERVICE, message="AI unavailable"))
    row = QueryLog.objects.get()
    assert (row.attempt_count, row.stopped_by, row.final_sql) == (0, "service", "")


def test_connection_string_is_never_stored(conn):
    log_request(conn.id, answered(1))
    stored = str(QueryLog.objects.values().get())
    assert "postgresql://" not in stored and "url_encrypted" not in stored


@pytest.mark.parametrize("sql,dialect,count", [
    ("SELECT `a`.x FROM `a` JOIN `b` ON 1=1", "mysql", 2),
    ("WITH t AS (SELECT 1 FROM a) SELECT * FROM t JOIN b ON 1=1", "postgresql", 2),
    ("SELECT 1 FROM s1.orders JOIN s2.orders ON 1=1", "postgresql", 2),
    ("SELECT 1 FROM a; SELECT 1 FROM b", "sqlite", 2),
    ("not sql at all (", "postgresql", 0),
])
def test_count_tables(sql, dialect, count):
    assert _count_tables(sql, dialect) == count


def test_no_row_spike_after_empty_results(conn):
    for _ in range(3):
        log_request(conn.id, answered(0))
    log_request(conn.id, answered(3))
    assert "row_spike" not in QueryLog.objects.order_by("id").last().anomaly_flags


def test_repeated_blocks_flags_the_third_and_later(conn):
    for _ in range(4):
        log_request(conn.id, blocked())
    flags = [("repeated_blocks" in r.anomaly_flags) for r in QueryLog.objects.order_by("id")]
    assert flags == [False, False, True, True]


# --- Log pages -----------------------------------------------------------------------


def test_log_filters_by_verdict_and_rule(admin_client, conn):
    log_request(conn.id, blocked())
    log_request(conn.id, answered(1))
    by_verdict = admin_client.get(reverse("log"), {"verdict": "blocked"}).context["entries"]
    by_rule = admin_client.get(reverse("log"), {"rule": "R3"}).context["entries"]
    everything = admin_client.get(reverse("log"), {"verdict": "nonsense"}).context["entries"]
    assert [e["verdict"] for e in by_verdict] == ["blocked"]
    assert [e["rules_fired"] for e in by_rule] == [["R3"]]
    assert len(everything) == 2


def test_log_shows_r11_as_a_rewrite_not_a_block(admin_client, conn):
    log_request(conn.id, blocked())
    log_request(conn.id, answered(1))
    QueryLog.objects.filter(verdict="answered").update(rules_fired=["R11"])
    response = admin_client.get(reverse("log"))
    by_verdict = {e["verdict"]: e for e in response.context["entries"]}
    assert (by_verdict["answered"]["blocked_by"], by_verdict["answered"]["limit_added"]) == ([], True)
    assert (by_verdict["blocked"]["blocked_by"], by_verdict["blocked"]["limit_added"]) == (["R3"], False)
    assert b"LIMIT added" in response.content


def test_log_detail_shows_every_attempt(admin_client, conn):
    log_request(conn.id, blocked())
    entry = admin_client.get(reverse("log_detail", args=[QueryLog.objects.get().id])).context["entry"]
    assert entry["stopped_by"] == "validator"
    assert entry["attempts"][0]["verdict"] == "BLOCK"
    assert entry["attempts"][0]["messages"] == [R3.message]


def test_audit_log_is_read_only_in_admin(admin_client, conn):
    log_request(conn.id, answered(1))
    row = QueryLog.objects.get()
    assert admin_client.get(reverse("admin:core_querylog_changelist"), {"rule": "R3"}).status_code == 200
    assert admin_client.get(reverse("admin:core_querylog_add")).status_code == 403
    assert admin_client.post(reverse("admin:core_querylog_change", args=[row.id]), {"question": "edited"}).status_code == 403
    assert QueryLog.objects.get().question == "q"
