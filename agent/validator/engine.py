"""The inference engine. Owner: Afraz.

Runs validator rules in four stages:

    PARSE -> TREE -> REWRITE -> COST

A block in PARSE or TREE ends validation at once: a blocked query is never
rewritten and never sent to the database, not even for EXPLAIN.

The engine fails closed: an unexpected exception always produces BLOCK.
"""

from __future__ import annotations

from typing import Callable

from sqlglot import exp, parse

from agent.config import ValidatorConfig
from agent.types import Dialect, RuleHit, Schema, Verdict

from .base import Rule, Stage, ValidationContext
from .rules import ALL_RULES


def _sqlglot_dialect(dialect: Dialect) -> str:
    return "postgres" if dialect == Dialect.POSTGRESQL else dialect.value


def _hits(rule: Rule, messages: list[str]) -> list[RuleHit]:
    return [
        RuleHit(rule_id=rule.id, rule_name=rule.name, action=rule.action, message=message)
        for message in messages
    ]


def _blocked(hits: list[RuleHit]) -> bool:
    return any(hit.action == "block" for hit in hits)


def _run_stage(stage: Stage, tree: exp.Expression | None, ctx: ValidationContext) -> list[RuleHit]:
    """Run every check-only rule of `stage`; all of them run, so every violation is reported."""
    hits: list[RuleHit] = []
    for rule in ALL_RULES:
        if rule.stage == stage:
            hits += _hits(rule, rule.check(tree, ctx))
    return hits


def validate(
    sql: str,
    schema: Schema,
    dialect: Dialect,
    *,
    config: ValidatorConfig | None = None,
    explain: Callable[[str], dict] | None = None,
) -> Verdict:
    """Validate SQL and return the rewritten SQL that may be executed.

    Contract:
    - Parse with sqlglot using ``dialect``.
    - Run rules stage by stage:
        PARSE -> TREE -> REWRITE -> COST
    - PARSE failures block immediately.
    - TREE rules all run so every violation is collected; any block stops here.
    - REWRITE applies R11 and updates the SQL.
    - COST runs against the rewritten SQL.
    - Any unexpected exception fails closed.
    """
    original_sql = sql
    hits: list[RuleHit] = []

    try:
        ctx = ValidationContext(
            sql=sql,
            dialect=dialect,
            schema=schema,
            config=config or ValidatorConfig(),
            explain=explain,
        )

        # PARSE
        try:
            parsed = parse(sql, read=_sqlglot_dialect(dialect))
            # Drop the empty statements sqlglot returns for stray semicolons and
            # trailing comments ("SELECT 1; -- done"), so R2 counts real statements only.
            ctx.statements = [s for s in parsed if s is not None and not isinstance(s, exp.Semicolon)]
        except Exception as exc:
            ctx.parse_error = str(exc)
            ctx.statements = []

        hits += _run_stage(Stage.PARSE, None, ctx)
        if _blocked(hits):
            return Verdict(allowed=False, sql=original_sql, hits=tuple(hits))

        # TREE: R2 guarantees exactly one statement.
        tree = ctx.statements[0]
        hits += _run_stage(Stage.TREE, tree, ctx)
        if _blocked(hits):
            return Verdict(allowed=False, sql=original_sql, hits=tuple(hits))

        # REWRITE: R11 adds or lowers the LIMIT.
        for rule in ALL_RULES:
            if rule.stage == Stage.REWRITE:
                tree, messages = rule.apply(tree, ctx)
                hits += _hits(rule, messages)
        # The SQL that runs is generated from the validated tree, never the raw input,
        # and without comments: MySQL executes `/*! ... */` comments as SQL.
        ctx.sql = tree.sql(dialect=_sqlglot_dialect(dialect), comments=False)

        # COST: R10 prices ctx.sql, so the LIMIT is part of the estimate.
        hits += _run_stage(Stage.COST, tree, ctx)
        if _blocked(hits):
            return Verdict(allowed=False, sql=original_sql, hits=tuple(hits))

        return Verdict(allowed=True, sql=ctx.sql, hits=tuple(hits))

    except Exception as exc:
        # Fail closed: never allow a query the validator could not finish checking.
        hits.append(
            RuleHit(
                rule_id="ENGINE",
                rule_name="Validator engine",
                action="block",
                message=f"The query could not be checked ({type(exc).__name__}), so it was not run.",
            )
        )
        return Verdict(allowed=False, sql=original_sql, hits=tuple(hits))
