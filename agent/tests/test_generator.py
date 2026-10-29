"""Prompts, reply parsing and Gemini failures (Phase 6). No real Gemini calls."""

import pytest

from agent import generator
from agent.config import GeminiConfig
from agent.generator import EarlierStep, ModelUnavailable
from agent.types import Dialect

CONFIG = GeminiConfig(api_key="test-key")
DDL = "CREATE TABLE artist (\n  artist_id INTEGER PRIMARY KEY,\n  name VARCHAR(120)\n);"


@pytest.fixture
def replies(monkeypatch):
    """Queue Gemini replies; records every prompt sent."""
    sent, queue = [], []

    def fake_call(prompt, config):
        sent.append(prompt)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(generator, "_call", fake_call)
    return sent, queue


def test_generation_prompt_has_dialect_schema_and_question(replies):
    sent, queue = replies
    queue.append('{"sql": "SELECT name FROM artist", "explanation": "Lists artists."}')
    g = generator.generate("Who are the artists?", DDL, Dialect.POSTGRESQL, CONFIG)
    assert g.sql == "SELECT name FROM artist" and g.explanation == "Lists artists."
    prompt = sent[0]
    assert "PostgreSQL" in prompt and DDL in prompt and "Question: Who are the artists?" in prompt
    assert '{"sql": "<query>", "explanation": "<one sentence>"}' in prompt
    assert "previous query failed" not in prompt


def test_correction_prompt_adds_failed_sql_and_error(replies):
    sent, queue = replies
    queue.append('{"sql": "SELECT name FROM artist", "explanation": "x"}')
    generator.generate("q", DDL, Dialect.SQLITE, CONFIG, failed_sql="SELECT nme FROM artist",
                       error="no such column: nme")
    assert "Your previous query failed." in sent[0]
    assert "Query: SELECT nme FROM artist" in sent[0] and "Database error: no such column: nme" in sent[0]


def test_null_sql_means_cannot_answer(replies):
    _, queue = replies
    queue.append('{"sql": null, "explanation": "There is no weather data."}')
    g = generator.generate("weather?", DDL, Dialect.MYSQL, CONFIG)
    assert g.sql is None and "weather" in g.explanation


@pytest.mark.parametrize("reply", ['```json\n{"sql": "SELECT 1", "explanation": "x"}\n```',
                                   '[{"sql": "SELECT 1", "explanation": "x"}]'])
def test_reply_wrappers_are_tolerated(replies, reply):
    replies[1].append(reply)
    assert generator.generate("q", DDL, Dialect.SQLITE, CONFIG).sql == "SELECT 1"


@pytest.mark.parametrize("reply", ["not json", "[1, 2]", '{"sql": 5, "explanation": "x"}'])
def test_unreadable_reply_is_unavailable(replies, reply):
    replies[1].append(reply)
    with pytest.raises(ModelUnavailable, match="could not read"):
        generator.generate("q", DDL, Dialect.SQLITE, CONFIG)


def test_earlier_steps_give_names_and_counts_never_values(replies):
    sent, queue = replies
    queue.append('{"sql": "SELECT 1", "explanation": "x"}')
    earlier = [EarlierStep(1, "Which artists have albums?", ["artist_id", "name"], 2)]
    generator.generate("Their album counts", DDL, Dialect.POSTGRESQL, CONFIG,
                       overall_question="Album counts of artists with albums", earlier=earlier)
    prompt = sent[0]
    assert "{step1}" in prompt and "artist_id, name" in prompt and "2 rows" in prompt
    assert "Album counts of artists with albums" in prompt


def test_missing_api_key_is_unavailable():
    with pytest.raises(ModelUnavailable, match="GEMINI_API_KEY"):
        generator._call("prompt", GeminiConfig(api_key=""))


def test_api_key_is_not_in_repr():
    assert "test-key" not in repr(CONFIG)


def test_plan_offered_only_when_allowed(replies):
    sent, queue = replies
    queue += ['{"sql": "SELECT 1", "explanation": "x"}'] * 2
    generator.generate("q", DDL, Dialect.SQLITE, CONFIG)
    generator.generate("q", DDL, Dialect.SQLITE, CONFIG, allow_plan=True)
    assert '"steps"' not in sent[0] and '"steps"' in sent[1]


def test_plan_reply_becomes_steps(replies):
    replies[1].append('{"steps": ["Which customers ordered in Q1?", "Which of them did not order in Q2?"]}')
    g = generator.generate("Q1 but not Q2", DDL, Dialect.POSTGRESQL, CONFIG, allow_plan=True)
    assert g.sql is None and g.steps == ["Which customers ordered in Q1?", "Which of them did not order in Q2?"]


def test_plan_reply_ignored_when_not_allowed(replies):
    replies[1].append('{"steps": ["a", "b"], "sql": null, "explanation": "needs steps"}')
    g = generator.generate("q", DDL, Dialect.SQLITE, CONFIG)
    assert g.steps is None and g.sql is None


@pytest.mark.parametrize("reply", ['{"steps": ["one step"], "sql": null, "explanation": "x"}', '{"steps": []}'])
def test_one_step_plan_is_not_a_plan(replies, reply):
    replies[1].append(reply)
    assert generator.generate("q", DDL, Dialect.SQLITE, CONFIG, allow_plan=True).steps is None


def test_plan_is_capped(replies):
    replies[1].append('{"steps": ["a", "b", "c", "d", "e", "f"]}')
    g = generator.generate("q", DDL, Dialect.SQLITE, CONFIG, allow_plan=True)
    assert len(g.steps) == CONFIG.max_plan_steps


class _FakeModels:
    def __init__(self, exc):
        self.exc = exc

    def generate_content(self, **kwargs):
        raise self.exc


@pytest.mark.parametrize("code,expected", [
    (429, "free-tier limit"),
    (404, "not available to this API key"),
    (403, "refused the request"),
    (503, "unavailable"),
])
def test_api_errors_become_clear_messages(monkeypatch, code, expected):
    from google import genai
    from google.genai import errors

    exc = errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})
    monkeypatch.setattr(genai, "Client", lambda **kw: type("C", (), {"models": _FakeModels(exc)})())
    with pytest.raises(ModelUnavailable, match=expected):
        generator._call("prompt", CONFIG)


def test_network_failure_is_unavailable(monkeypatch):
    from google import genai

    monkeypatch.setattr(genai, "Client", lambda **kw: type("C", (), {"models": _FakeModels(TimeoutError("slow"))})())
    with pytest.raises(ModelUnavailable, match="unavailable"):
        generator._call("prompt", CONFIG)


def test_daily_quota_is_told_apart_from_the_per_minute_one(monkeypatch):
    from google import genai
    from google.genai import errors

    def quota(quota_id):
        return errors.APIError(429, {"error": {"code": 429, "message": "x", "status": "RESOURCE_EXHAUSTED", "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]}]}})

    for quota_id, expected in [("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "daily free-tier limit"),
                               ("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "per-minute free-tier limit")]:
        monkeypatch.setattr(genai, "Client", lambda **kw: type("C", (), {"models": _FakeModels(quota(quota_id))})())
        with pytest.raises(ModelUnavailable, match=expected):
            generator._call("prompt", CONFIG)


def test_prompt_forbids_substituting_withheld_columns(replies):
    sent, queue = replies
    queue.append('{"sql": "SELECT 1", "explanation": "x"}')
    generator.generate("q", DDL, Dialect.SQLITE, CONFIG)
    assert "Never substitute a different column" in sent[0]


@pytest.mark.parametrize("error, sent", [
    ('invalid input syntax for type integer: "Rock"', "invalid input syntax for type integer: <value>"),
    ('value "99999999999" is out of range for type integer', "value <value> is out of range for type integer"),
    ("Truncated incorrect DOUBLE value: 'abc'", "Truncated incorrect DOUBLE value: <value>"),
    ('column "nme" does not exist', 'column "nme" does not exist'),
    ("Unknown column 'x' in 'field list'", "Unknown column 'x' in 'field list'"),
    ("no such column: nme", "no such column: nme"),
    ("syntax error\nDETAIL: Key (email)=(a@b.c)", "syntax error"),
])
def test_correction_prompt_never_carries_values_from_errors(error, sent):
    """A cast on a stored value quotes the row's value in the error (D-046)."""
    prompt = generator.generation_prompt("q", DDL, Dialect.POSTGRESQL, failed_sql="SELECT 1", error=error)
    assert f"Database error: {sent}\n" in prompt


def test_prompt_asks_for_no_sample_values():
    assert "sample" not in generator.generation_prompt("q", DDL, Dialect.POSTGRESQL)
