"""The inference engine. Owner: Afraz.

Runs validator rules in four stages:

    PARSE -> TREE -> REWRITE -> COST

The engine fails closed: an unexpected exception always produces BLOCK.
"""

from __future__ import annotations

from typing import Callable

from sqlglot import parse

from agent.config import ValidatorConfig
from agent.types import Dialect, RuleHit, Schema, Verdict

from .base import Stage, ValidationContext
from .rules import ALL_RULES


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
    - TREE rules all run so every violation is collected.
    - REWRITE applies R11 and updates the SQL.
    - COST runs against the rewritten SQL.
    - Any unexpected exception fails closed.
    """

    original_sql = sql
    hits: list[RuleHit] = []

    # ------------------------------------------------------------------
    # Build configuration/context
    # ------------------------------------------------------------------
    try:
        if config is None:
            config = ValidatorConfig()

        ctx = ValidationContext(
            sql=sql,
            dialect=dialect,
            schema=schema,
            config=config,
            explain=explain,
        )

        # --------------------------------------------------------------
        # PARSE
        # --------------------------------------------------------------
        try:
            sqlglot_dialect = ("postgres" if dialect == Dialect.POSTGRESQL else dialect.value)
            statements = parse(sql, read=sqlglot_dialect)
            ctx.statements = statements
            ctx.parse_error = None
        except Exception as exc:
            ctx.parse_error = str(exc)
            ctx.statements = []

        # R1/R2 are the PARSE-stage rules.
        for rule in ALL_RULES:
            if rule.stage != Stage.PARSE:
                continue

            messages = rule.check(None, ctx)

            for message in messages:
                hits.append(
                    RuleHit(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        action=rule.action,
                        message=message,
                    )
                )

        # A parse failure blocks immediately. Do not attempt tree/rewrite
        # processing on a tree that does not exist.
        parse_blocks = [h for h in hits if h.action == "block"]

        if parse_blocks:
            return Verdict(
                allowed=False,
                sql=original_sql,
                hits=tuple(hits),
            )

        # --------------------------------------------------------------
        # TREE
        # --------------------------------------------------------------
        #
        # R2 guarantees a single statement. Therefore the first parsed
        # statement is the tree used by R3-R9.
        # --------------------------------------------------------------
        if not ctx.statements:
            # Defensive fail-closed behavior. Normally R1 catches this.
            hit = RuleHit(
                rule_id="R1",
                rule_name="Parseable",
                action="block",
                message="SQL could not be parsed.",
            )
            hits.append(hit)

            return Verdict(
                allowed=False,
                sql=original_sql,
                hits=tuple(hits),
            )

        tree = ctx.statements[0]

        tree_blocks_before = len([h for h in hits if h.action == "block"])

        for rule in ALL_RULES:
            if rule.stage != Stage.TREE:
                continue

            messages = rule.check(tree, ctx)

            for message in messages:
                hits.append(
                    RuleHit(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        action=rule.action,
                        message=message,
                    )
                )

        # --------------------------------------------------------------
        # REWRITE
        # --------------------------------------------------------------
        #
        # R11 never blocks. It edits the tree and therefore must run even
        # when a TREE rule has fired. This keeps the engine's stage
        # contract deterministic and allows COST to inspect rewritten SQL.
        # --------------------------------------------------------------
        for rule in ALL_RULES:
            if rule.stage != Stage.REWRITE:
                continue

            tree, messages = rule.apply(tree, ctx)

            for message in messages:
                hits.append(
                    RuleHit(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        action=rule.action,
                        message=message,
                    )
                )

        # Convert the rewritten AST back to SQL.
        sqlglot_dialect = ("postgres" if dialect == Dialect.POSTGRESQL else dialect.value)
        ctx.sql = tree.sql(dialect=sqlglot_dialect)

        # --------------------------------------------------------------
        # COST
        # --------------------------------------------------------------
        #
        # R10 sees ctx.sql AFTER R11 has applied the row limit.
        # --------------------------------------------------------------
        for rule in ALL_RULES:
            if rule.stage != Stage.COST:
                continue

            messages = rule.check(tree, ctx)

            for message in messages:
                hits.append(
                    RuleHit(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        action=rule.action,
                        message=message,
                    )
                )

        # --------------------------------------------------------------
        # FINAL VERDICT
        # --------------------------------------------------------------
        blocked = any(hit.action == "block" for hit in hits)

        return Verdict(
            allowed=not blocked,
            sql=ctx.sql if not blocked else original_sql,
            hits=tuple(hits),
        )

    except Exception as exc:
        # --------------------------------------------------------------
        # FAIL CLOSED
        # --------------------------------------------------------------
        #
        # Never allow a query when the validator itself encounters an
        # unexpected error.
        # --------------------------------------------------------------
        hits.append(
            RuleHit(
                rule_id="ENGINE",
                rule_name="Validator engine",
                action="block",
                message=f"Validator error: {exc!r}",
            )
        )

        return Verdict(
            allowed=False,
            sql=original_sql,
            hits=tuple(hits),
        )