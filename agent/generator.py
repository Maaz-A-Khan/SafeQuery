"""Generation (with planning), correction and step prompts, Gemini client. Owner: Maaz (Phase 6).

Every prompt asks for JSON (see the "Prompt Design" note). The prompts ask for
safe SQL, but nothing relies on Gemini obeying: the validator checks whatever
comes back.

What leaves the machine: the question, the schema DDL (restricted tables and
columns already removed by `agent.schema.render_ddl`), earlier steps' questions
and column names, and database error text on a correction, with quoted values
removed (`scrub_values`). Never row data: not results (D-028), not sample values,
not values quoted in errors (D-046).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from agent.config import GeminiConfig
from agent.types import Dialect

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """Gemini outage, quota limit, network error or an unreadable reply (FR-Q10).
    Never retried automatically."""


@dataclass
class Generation:
    sql: str | None        # None when Gemini says the schema cannot answer, or returns a plan
    explanation: str
    steps: list[str] | None = None   # a plan, when one query cannot answer the question (FR-Q8)


@dataclass
class EarlierStep:
    """What a later step may know about an earlier one: never its values (D-028)."""

    number: int
    question: str
    columns: list[str]
    row_count: int


DIALECT_NAMES = {Dialect.POSTGRESQL: "PostgreSQL", Dialect.MYSQL: "MySQL", Dialect.SQLITE: "SQLite"}

GENERATION_PROMPT = """\
You are a SQL assistant for a {dialect} database.
Write ONE read-only SELECT query that answers the question.
Use only the tables and columns below.

Schema:
{schema_ddl}
{earlier}
Question: {question}

Reply with JSON only:
{{"sql": "<query>", "explanation": "<one sentence>"}}
If the question cannot be answered with this schema, set sql to null
and say why in explanation. Never substitute a different column or table for
one the question asks about: some are withheld, so if a column is not listed,
set sql to null and say which information is not available.{plan_option}"""

# Planning is offered only on the first call for the user's own question, so a
# simple question costs one Gemini call (free tier: 5 requests a minute, D-038).
PLAN_OPTION = """
Only if no single query can answer the question, reply instead with
{{"steps": ["<question 1>", "<question 2>"]}}: 2 to {max_steps} smaller questions
answered in order, where a later step can use the values of an earlier step's
first column. Almost every question needs one query, not steps."""

EARLIER_STEPS = """
This question is one step of a larger question:
{overall}

Earlier steps have already run. You cannot see their values, but you can use them:
write {{stepN}} where a parenthesised list of step N's first-column values belongs,
for example `WHERE customer_id IN {{step1}}`. SafeQuery inserts the values itself.
{steps}
"""

CORRECTION = """

Your previous query failed.
Query: {failed_sql}
Database error: {error}
Write a corrected query. Same JSON format."""

# A value the database quotes in an error can come from a row, e.g. PostgreSQL's
# `invalid input syntax for type integer: "Rock"` when a cast meets a stored value.
# Values follow a colon or the word "value"; names (`column "x" does not exist`,
# MySQL's `Unknown column 'x'`) do not, so the correction still sees them.
_QUOTED_VALUE = re.compile(r"""(:\s*|\bvalue\s+)(["'])(?:(?!\2).)*\2""", re.IGNORECASE)


def scrub_values(error: str) -> str:
    """The error's first line, with values the database quoted replaced by <value>."""
    first_line = error.strip().splitlines()[0] if error.strip() else ""
    return _QUOTED_VALUE.sub(lambda m: f"{m.group(1)}<value>", first_line)


# --- Calling Gemini ----------------------------------------------------------------


def _call(prompt: str, config: GeminiConfig) -> str:
    """One Gemini request in JSON mode; returns the reply text. Any failure is ModelUnavailable."""
    if not config.api_key:
        raise ModelUnavailable("GEMINI_API_KEY is missing from .env.")
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:   # pragma: no cover - google-genai is in requirements.txt
        raise ModelUnavailable("The google-genai package is not installed.") from exc

    try:
        client = genai.Client(
            api_key=config.api_key,
            http_options=types.HttpOptions(timeout=int(config.request_timeout_s * 1000)),
        )
        response = client.models.generate_content(
            model=config.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=config.temperature,
                response_mime_type="application/json",
            ),
        )
    except errors.APIError as exc:
        code = getattr(exc, "code", None)
        logger.warning("Gemini request failed (%s): %s", code, str(exc)[:300])
        if code == 429:
            raise ModelUnavailable(_quota_message(exc)) from exc
        if code == 404:
            raise ModelUnavailable(f"The Gemini model {config.model!r} is not available to this API key. "
                                   "Check GEMINI_MODEL in .env.") from exc
        if code in (400, 401, 403):
            raise ModelUnavailable("The AI service refused the request. Check GEMINI_API_KEY and GEMINI_MODEL.") from exc
        raise ModelUnavailable("The AI service is unavailable, try again shortly.") from exc
    except Exception as exc:   # network errors, timeouts
        logger.warning("Gemini request failed: %r", exc)
        raise ModelUnavailable("The AI service is unavailable, try again shortly.") from exc

    text = getattr(response, "text", None)
    if not text:
        raise ModelUnavailable("The AI service returned an empty answer.")
    return text


def _quota_message(exc) -> str:
    """Which free-tier limit a 429 hit: Google names the quota in the error details."""
    details = (getattr(exc, "details", None) or {}).get("error", {}).get("details", [])
    quota_ids = [v.get("quotaId", "") for d in details if isinstance(d, dict) for v in d.get("violations", [])]
    if any("PerDay" in q for q in quota_ids):
        return ("The AI service's daily free-tier limit was reached. "
                "It resets at midnight Pacific time (12 to 1 pm in Pakistan).")
    return "The AI service's per-minute free-tier limit was reached. Try again in a minute."


def _parse_json(text: str) -> dict:
    """The reply as a dict. Tolerates a ```json fence around it."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelUnavailable("The AI service returned an answer SafeQuery could not read.") from exc
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        raise ModelUnavailable("The AI service returned an answer SafeQuery could not read.")
    return data


# --- Prompts -----------------------------------------------------------------------


def _earlier_section(overall: str | None, earlier: list[EarlierStep]) -> str:
    if not earlier:
        return ""
    steps = "\n".join(
        f"Step {s.number}: {s.question} -> columns {', '.join(s.columns) or '(none)'}; "
        f"{s.row_count} row{'s' if s.row_count != 1 else ''}; first column available as {{step{s.number}}}"
        for s in earlier
    )
    return EARLIER_STEPS.format(overall=overall or "", steps=steps)


def generation_prompt(
    question: str,
    schema_ddl: str,
    dialect: Dialect,
    *,
    failed_sql: str | None = None,
    error: str | None = None,
    overall_question: str | None = None,
    earlier: list[EarlierStep] | None = None,
    allow_plan: bool = False,
    max_steps: int = 4,
) -> str:
    prompt = GENERATION_PROMPT.format(
        dialect=DIALECT_NAMES[dialect],
        schema_ddl=schema_ddl,
        earlier=_earlier_section(overall_question, earlier or []),
        question=question,
        plan_option=PLAN_OPTION.format(max_steps=max_steps) if allow_plan else "",
    )
    if failed_sql is not None:
        prompt += CORRECTION.format(failed_sql=failed_sql, error=scrub_values(error or ""))
    return prompt


def generate(
    question: str,
    schema_ddl: str,
    dialect: Dialect,
    config: GeminiConfig,
    *,
    failed_sql: str | None = None,
    error: str | None = None,
    overall_question: str | None = None,
    earlier: list[EarlierStep] | None = None,
    allow_plan: bool = False,
) -> Generation:
    """Generation prompt; with `failed_sql` and `error`, the correction prompt.
    For a later step of a plan, `earlier` describes the steps before it. With
    `allow_plan`, Gemini may answer with a plan (`steps`) instead of SQL."""
    prompt = generation_prompt(
        question, schema_ddl, dialect,
        failed_sql=failed_sql, error=error, overall_question=overall_question, earlier=earlier,
        allow_plan=allow_plan, max_steps=config.max_plan_steps,
    )
    data = _parse_json(_call(prompt, config))
    steps = data.get("steps") if allow_plan else None
    if isinstance(steps, list):
        steps = [str(x).strip() for x in steps if str(x).strip()][: config.max_plan_steps]
        if len(steps) >= 2:
            return Generation(sql=None, explanation=str(data.get("explanation") or "").strip(), steps=steps)
    sql = data.get("sql")
    if sql is not None and not isinstance(sql, str):
        raise ModelUnavailable("The AI service returned an answer SafeQuery could not read.")
    sql = sql.strip() if sql else None
    return Generation(sql=sql or None, explanation=str(data.get("explanation") or "").strip())
