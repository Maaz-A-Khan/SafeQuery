"""Question → answer: generate, validate, execute, correct. Owner: Maaz (Phase 6).

Views do not call this directly: they call `core.services.answer_question`,
which loads the connection, calls `run`, and writes the audit log.

Every SQL string that reaches the database, whether generated, corrected,
cached or carrying an earlier step's values, has passed `validate` first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import sqlglot
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from agent import generator
from agent.config import AgentConfig
from agent.connection import open_engine, safe_error
from agent.executor import Execution, ExecutionError, execute, explainer
from agent.generator import EarlierStep, ModelUnavailable
from agent.schema import render_ddl
from agent.types import Attempt, Dialect, Outcome, QueryCache, Result, StoppedBy, Target, Verdict
from agent.validator import validate

BLOCKED_MESSAGE = "This query was blocked and was not run."
SQLGLOT_DIALECTS = {Dialect.POSTGRESQL: "postgres", Dialect.MYSQL: "mysql", Dialect.SQLITE: "sqlite"}
_PLACEHOLDER = re.compile(r"\{step(\d+)\}")


@dataclass
class _Step:
    """The outcome of answering one question (or one step of a plan)."""

    attempts: list[Attempt] = field(default_factory=list)
    outcome: Outcome = Outcome.FAILED
    stopped_by: StoppedBy = StoppedBy.NONE
    message: str = ""
    sql: str | None = None
    explanation: str = ""
    execution: Execution | None = None
    plan: list[str] | None = None   # Gemini asked to split the question instead of writing SQL


class _Run:
    """Everything one question needs: the engine, the prompt context, the checks."""

    def __init__(self, target: Target, config: AgentConfig, engine: Engine):
        self.target, self.config, self.engine = target, config, engine
        self.dialect = target.dialect
        self.ddl = render_ddl(target.schema)
        self.explain = explainer(engine, target.dialect, config.executor)

    def check(self, sql: str) -> Verdict:
        if not self.config.switches.validator:   # ablation run only (D-017)
            return Verdict(allowed=True, sql=sql)
        return validate(sql, self.target.schema, self.dialect,
                        config=self.config.validator, explain=self.explain)

    def check_and_run(self, sql: str, attempt: Attempt, step: _Step) -> bool:
        """Validate, then execute if allowed. Returns True when rows came back."""
        attempt.verdict = verdict = self.check(sql)
        if not verdict.allowed:
            step.outcome, step.stopped_by, step.message = Outcome.BLOCKED, StoppedBy.VALIDATOR, BLOCKED_MESSAGE
            return False
        try:
            step.execution = execute(self.engine, verdict.sql, self.config.executor)
        except ExecutionError as exc:
            attempt.error = str(exc)
            return False
        attempt.exec_ms = step.execution.exec_ms
        step.outcome, step.stopped_by, step.sql = Outcome.ANSWERED, StoppedBy.NONE, verdict.sql
        return True

    def answer(self, question: str, *, overall: str | None = None, earlier: list[EarlierStep] | None = None,
               values: dict[int, list] | None = None, allow_plan: bool = False) -> _Step:
        """Generate, validate, execute; on a database error ask Gemini to correct it,
        up to `max_attempts` in all. A block is final: it is never retried. With
        `allow_plan`, the first reply may be a plan instead of SQL (D-038)."""
        step = _Step()
        failed_sql = error = None
        for number in range(1, self.config.gemini.max_attempts + 1):
            try:
                generation = generator.generate(
                    question, self.ddl, self.dialect, self.config.gemini,
                    failed_sql=failed_sql, error=error, overall_question=overall, earlier=earlier,
                    allow_plan=allow_plan and number == 1,
                )
            except ModelUnavailable as exc:
                step.stopped_by, step.message = StoppedBy.SERVICE, str(exc)
                return step
            if generation.steps:
                step.plan = generation.steps
                return step
            attempt = Attempt(number, generation.sql, generation.explanation)
            step.attempts.append(attempt)
            step.explanation = generation.explanation
            if generation.sql is None:
                step.stopped_by = StoppedBy.MODEL
                step.message = generation.explanation or "This question can't be answered from this database."
                return step
            try:
                sql = _insert_values(generation.sql, values or {}, self.dialect)
            except ValueError as exc:   # a placeholder for a step that does not exist
                attempt.error = str(exc)
                failed_sql, error = generation.sql, attempt.error
                continue
            if self.check_and_run(sql, attempt, step):
                return step
            if step.outcome == Outcome.BLOCKED:
                return step
            failed_sql, error = generation.sql, attempt.error
        step.stopped_by = StoppedBy.DATABASE
        step.message = f"Couldn't answer this. Last error: {step.attempts[-1].error}"
        return step


def _insert_values(sql: str, values: dict[int, list], dialect: Dialect) -> str:
    """Replace {stepN} with a parenthesised list of step N's first-column values,
    written as literals by sqlglot for this dialect. The result is validated after."""
    def literal(v) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float, Decimal)):
            return str(v)
        return sqlglot.exp.Literal.string(str(v)).sql(dialect=SQLGLOT_DIALECTS[dialect])

    def replace(m: re.Match) -> str:
        n = int(m.group(1))
        if n not in values:
            raise ValueError(f"{{step{n}}} refers to a step that has not run.")
        items = values[n]
        return "(" + (", ".join(literal(v) for v in items) if items else "NULL") + ")"

    return _PLACEHOLDER.sub(replace, sql)


def _result(question: str, step: _Step, attempts: list[Attempt], plan: list[str],
            explanation: str, from_cache: bool = False) -> Result:
    ex = step.execution
    return Result(
        question=question,
        outcome=step.outcome,
        stopped_by=step.stopped_by,
        message=step.message,
        sql=step.sql,
        explanation=explanation,
        columns=ex.columns if ex else [],
        rows=ex.rows if ex else [],
        truncated=ex.truncated if ex else False,
        attempts=attempts,
        plan=plan,
        from_cache=from_cache,
        exec_ms=ex.exec_ms if ex else None,
    )


def _from_cache(run: _Run, question: str, cache: QueryCache, schema_hash: str) -> Result | None:
    """Answer from stored SQL, re-validated. Anything but rows means: ignore the cache."""
    sql = cache.lookup(question, schema_hash)
    if not sql:
        return None
    step = _Step()
    attempt = Attempt(1, sql, "Reused from an earlier identical question.")
    if not run.check_and_run(sql, attempt, step):
        return None
    step.explanation = attempt.explanation
    return _result(question, step, [attempt], [], attempt.explanation, from_cache=True)


def _multi_step(run: _Run, question: str, steps: list[str]) -> Result:
    """Each step generated, validated and executed in turn. A later step uses an
    earlier step's first-column values through {stepN}, filled in here, so the
    values never go to Gemini (D-028). The answer is the last step's table."""
    attempts: list[Attempt] = []
    earlier: list[EarlierStep] = []
    values: dict[int, list] = {}
    explanations: list[str] = []
    step = _Step()
    for n, sub_question in enumerate(steps, start=1):
        step = run.answer(sub_question, overall=question, earlier=earlier, values=values)
        attempts += step.attempts
        if step.outcome != Outcome.ANSWERED:
            step.message = f"Step {n} of {len(steps)} ({sub_question}): {step.message}"
            return _result(question, step, attempts, steps, " ".join(explanations))
        ex = step.execution
        explanations.append(f"Step {n}: {step.explanation}".strip())
        first_column = [row[0] for row in ex.rows] if ex.columns else []
        if len(first_column) > run.config.gemini.max_step_values or ex.truncated:
            step.outcome, step.stopped_by = Outcome.FAILED, StoppedBy.DATABASE
            step.message = (f"Step {n} of {len(steps)} returned more than {run.config.gemini.max_step_values} "
                            "values to pass on. Ask a narrower question.")
            step.execution = None
            return _result(question, step, attempts, steps, " ".join(explanations))
        values[n] = first_column
        earlier.append(EarlierStep(n, sub_question, ex.columns, len(ex.rows)))
    return _result(question, step, attempts, steps, " ".join(explanations))


def run(
    target: Target,
    question: str,
    config: AgentConfig,
    cache: QueryCache | None = None,
) -> Result:
    """Answer one question. Every query, including corrections and cache hits,
    passes `agent.validator.validate` before it runs. Blocked queries are never
    retried; database errors are corrected up to `config.gemini.max_attempts`.
    A question no single query can answer comes back from Gemini as a plan of up to
    `config.gemini.max_plan_steps` steps, answered in turn. Only answered
    single-step questions are saved to `cache`."""
    try:
        engine = open_engine(target.url, config)
    except Exception as exc:
        return Result(question, Outcome.FAILED, StoppedBy.DATABASE,
                      message=f"Could not open the database: {safe_error(exc, target.url)}")
    try:
        try:   # NFR-R1: an unreachable database is a clear message, not a Gemini correction loop
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            return Result(question, Outcome.FAILED, StoppedBy.DATABASE,
                          message=f"Could not reach the database: {safe_error(exc, target.url)}")

        session = _Run(target, config, engine)
        schema_hash = target.schema.schema_hash()
        if cache is not None:
            cached = _from_cache(session, question, cache, schema_hash)
            if cached is not None:
                return cached

        step = session.answer(question, allow_plan=True)
        if step.plan:
            return _multi_step(session, question, step.plan)
        result = _result(question, step, step.attempts, [], step.explanation)
        if cache is not None and result.outcome == Outcome.ANSWERED and result.sql:
            cache.save(question, schema_hash, result.sql)
        return result
    finally:
        engine.dispose()
