"""The question loop end to end on SQLite, with Gemini replaced by a script (Phase 6)."""

from dataclasses import replace

import pytest

from agent import generator, pipeline
from agent.config import AgentConfig, Switches
from agent.connection import open_engine
from agent.generator import Generation, ModelUnavailable
from agent.schema import introspect
from agent.types import Outcome, StoppedBy, Target


class FakeGemini:
    """Scripted generate() replies; `plan=` puts a plan reply first. Records each call."""

    def __init__(self, monkeypatch, *, plan=None, sql=()):
        self.replies = ([Generation(None, "Needs steps.", steps=plan)] if plan else []) + list(sql)
        self.generate_calls = []
        monkeypatch.setattr(generator, "generate", self._generate)

    def _generate(self, question, ddl, dialect, config, **kw):
        self.generate_calls.append({"question": question, "ddl": ddl, **kw})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, Generation) else Generation(reply, f"Explains {reply}")


class MemoryCache:
    def __init__(self):
        self.store, self.lookups = {}, 0

    def lookup(self, question, schema_hash):
        self.lookups += 1
        return self.store.get((question, schema_hash))

    def save(self, question, schema_hash, sql):
        self.store[(question, schema_hash)] = sql


@pytest.fixture
def target(shop_url):
    engine = open_engine(shop_url, AgentConfig())
    try:
        schema = introspect(engine, AgentConfig())
    finally:
        engine.dispose()
    return Target(1, schema.dialect, schema, shop_url)


def run(target, question="q", config=AgentConfig(), cache=None):
    return pipeline.run(target, question, config, cache)


def test_answered_first_time(monkeypatch, target):
    gemini = FakeGemini(monkeypatch, sql=["SELECT name FROM artist ORDER BY name"])
    r = run(target, "Who are the artists?")
    assert r.outcome == Outcome.ANSWERED and r.stopped_by == StoppedBy.NONE
    assert r.columns == ["name"] and r.rows == [("AC/DC",), ("Accept",)]
    assert r.sql.endswith("LIMIT 1000") and r.rules_fired == ["R11"]
    assert r.attempt_count == 1 and r.explanation
    assert gemini.generate_calls[0]["question"] == "Who are the artists?"
    assert gemini.generate_calls[0]["allow_plan"] is True   # one call can plan or answer (D-038)


def test_prompt_schema_hides_restricted_tables_and_columns(monkeypatch, target):
    gemini = FakeGemini(monkeypatch, sql=["SELECT 1"])
    run(target)
    ddl = gemini.generate_calls[0]["ddl"]
    assert "artist" in ddl and "user_credentials" not in ddl and "api_token" not in ddl


def test_database_error_is_corrected(monkeypatch, target):
    gemini = FakeGemini(monkeypatch, sql=["SELECT nme FROM artist", "SELECT name FROM artist"])
    r = run(target)
    assert r.outcome == Outcome.ANSWERED and r.attempt_count == 2
    assert "no such column" in r.attempts[0].error
    retry = gemini.generate_calls[1]
    assert retry["failed_sql"] == "SELECT nme FROM artist" and "no such column" in retry["error"]


def test_gives_up_after_three_attempts(monkeypatch, target):
    gemini = FakeGemini(monkeypatch, sql=["SELECT a FROM artist", "SELECT b FROM artist", "SELECT c FROM artist"])
    r = run(target)
    assert r.outcome == Outcome.FAILED and r.stopped_by == StoppedBy.DATABASE
    assert r.attempt_count == 3 and len(gemini.generate_calls) == 3
    assert r.message.startswith("Couldn't answer this. Last error:")


@pytest.mark.parametrize("sql,rule", [
    ("DROP TABLE orders", "R3"),
    ("SELECT password_hash FROM user_credentials", "R6"),
    ("SELECT api_token FROM orders", "R6"),
])
def test_blocked_query_is_never_retried_or_run(monkeypatch, target, sql, rule):
    gemini = FakeGemini(monkeypatch, sql=[sql, "SELECT 1"])
    r = run(target)
    assert r.outcome == Outcome.BLOCKED and r.stopped_by == StoppedBy.VALIDATOR
    assert len(gemini.generate_calls) == 1 and rule in [h.rule_id for h in r.block_hits]
    assert r.rows == [] and r.sql is None


def test_model_says_it_cannot_answer(monkeypatch, target):
    FakeGemini(monkeypatch, sql=[Generation(None, "There is no weather data.")])
    r = run(target)
    assert r.outcome == Outcome.FAILED and r.stopped_by == StoppedBy.MODEL
    assert r.message == "There is no weather data."


def test_gemini_unavailable(monkeypatch, target):
    FakeGemini(monkeypatch, sql=[ModelUnavailable("The AI service is unavailable, try again shortly.")])
    r = run(target)
    assert r.outcome == Outcome.FAILED and r.stopped_by == StoppedBy.SERVICE
    assert "unavailable" in r.message


def test_unreachable_database_never_calls_gemini(monkeypatch, target, tmp_path):
    gemini = FakeGemini(monkeypatch, sql=["SELECT 1"])
    gone = replace(target, url=f"sqlite:///{(tmp_path / 'missing.db').as_posix()}")
    r = run(gone)
    assert r.outcome == Outcome.FAILED and r.stopped_by == StoppedBy.DATABASE
    assert gemini.generate_calls == []


def test_cache_saves_answers_and_reuses_them_without_gemini(monkeypatch, target):
    cache = MemoryCache()
    FakeGemini(monkeypatch, sql=["SELECT name FROM artist"])
    first = run(target, "artists", cache=cache)
    assert first.outcome == Outcome.ANSWERED and not first.from_cache and len(cache.store) == 1

    gemini = FakeGemini(monkeypatch, sql=[])
    second = run(target, "artists", cache=cache)
    assert second.outcome == Outcome.ANSWERED and second.from_cache
    assert second.rows == first.rows and gemini.generate_calls == []


def test_blocked_and_failed_answers_are_not_cached(monkeypatch, target):
    cache = MemoryCache()
    FakeGemini(monkeypatch, sql=["DROP TABLE orders"])
    run(target, cache=cache)
    FakeGemini(monkeypatch, sql=[Generation(None, "no")])
    run(target, cache=cache)
    assert cache.store == {}


def test_cached_sql_is_validated_again(monkeypatch, target):
    """Restricting a table after it was cached: the cached SQL is refused and Gemini is asked."""
    cache = MemoryCache()
    cache.store[("artists", target.schema.schema_hash())] = "SELECT password_hash FROM user_credentials"
    gemini = FakeGemini(monkeypatch, sql=["SELECT name FROM artist"])
    r = run(target, "artists", cache=cache)
    assert not r.from_cache and r.outcome == Outcome.ANSWERED and len(gemini.generate_calls) == 1


def test_two_step_question_passes_values_locally(monkeypatch, target):
    gemini = FakeGemini(monkeypatch, plan=["Which artists have albums?", "Their names"],
                        sql=["SELECT artist_id FROM album", "SELECT name FROM artist WHERE artist_id IN {step1}"])
    r = run(target, "Names of artists with albums")
    assert r.outcome == Outcome.ANSWERED and r.plan == ["Which artists have albums?", "Their names"]
    assert sorted(r.rows) == [("AC/DC",), ("Accept",)]
    assert "IN (1, 2)" in r.sql   # values inserted by SafeQuery, then validated
    later = gemini.generate_calls[2]
    assert later["allow_plan"] is False   # steps never plan again
    assert later["overall_question"] == "Names of artists with albums"
    assert later["earlier"][0].columns == ["artist_id"] and later["earlier"][0].row_count == 2
    assert "1, 2" not in str(later)   # values never reach Gemini (D-028)
    assert r.explanation.startswith("Step 1:")


def test_inserted_text_values_are_quoted_and_still_validated(monkeypatch, target):
    FakeGemini(monkeypatch, plan=["statuses", "orders with them"],
               sql=["SELECT status FROM orders WHERE status = 'shipped' LIMIT 1",
                    "SELECT order_id FROM orders WHERE status IN {step1} ORDER BY order_id"])
    r = run(target)
    assert r.outcome == Outcome.ANSWERED and r.rows == [(1,), (2,)]
    assert "IN ('shipped')" in r.sql


def test_a_blocked_step_stops_the_plan(monkeypatch, target):
    gemini = FakeGemini(monkeypatch, plan=["a", "b", "c"],
                        sql=["SELECT artist_id FROM album", "SELECT password_hash FROM user_credentials", "SELECT 1"])
    r = run(target)
    assert r.outcome == Outcome.BLOCKED and r.message.startswith("Step 2 of 3")
    assert len(gemini.generate_calls) == 3   # plan, step 1, step 2


def test_too_many_values_to_pass_on(monkeypatch, target):
    config = AgentConfig(gemini=replace(AgentConfig().gemini, max_step_values=2))
    FakeGemini(monkeypatch, plan=["orders", "statuses"], sql=["SELECT order_id FROM orders", "SELECT 1"])
    r = run(target, config=config)
    assert r.outcome == Outcome.FAILED and "more than 2 values" in r.message


def test_placeholder_for_a_step_that_has_not_run_is_corrected(monkeypatch, target):
    gemini = FakeGemini(monkeypatch, plan=["a", "b"],
                        sql=["SELECT artist_id FROM album", "SELECT name FROM artist WHERE artist_id IN {step7}",
                             "SELECT name FROM artist WHERE artist_id IN {step1}"])
    r = run(target)
    assert r.outcome == Outcome.ANSWERED and "step7" in gemini.generate_calls[3]["error"]


def test_multi_step_answers_are_not_cached(monkeypatch, target):
    cache = MemoryCache()
    FakeGemini(monkeypatch, plan=["a", "b"],
               sql=["SELECT artist_id FROM album", "SELECT name FROM artist WHERE artist_id IN {step1}"])
    assert run(target, cache=cache).outcome == Outcome.ANSWERED
    assert cache.store == {}


def test_validator_switch_off_lets_sql_through(monkeypatch, target):
    """Ablation run 2/3 only (D-017): the database layer still refuses the write."""
    off = AgentConfig(switches=Switches(validator=False))
    FakeGemini(monkeypatch, sql=["DELETE FROM orders", "DELETE FROM orders", "DELETE FROM orders"])
    r = run(target, config=off)
    assert r.outcome == Outcome.FAILED and r.stopped_by == StoppedBy.DATABASE
    assert "readonly" in r.attempts[0].error.lower() or "read-only" in r.attempts[0].error.lower()
