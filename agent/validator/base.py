"""The `Rule` base class and the facts every rule sees. Owner: Afraz."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, ClassVar

from sqlglot import exp

from agent.config import ValidatorConfig
from agent.types import Dialect, Schema


class Stage(IntEnum):
    """Rules run stage by stage, in this order.

    PARSE   R1, R2   on the parse result; must pass before anything else
    TREE    R3 - R9  all run, every violation collected
    REWRITE R11      edits the tree (adds or lowers LIMIT), never blocks
    COST    R10      EXPLAINs the *rewritten* SQL, so the row limit is counted
                     in the cost estimate; the only rule that contacts the database
    """

    PARSE = 1
    TREE = 2
    REWRITE = 3
    COST = 4


@dataclass
class ValidationContext:
    """Working memory for one query."""

    sql: str
    dialect: Dialect
    schema: Schema
    config: ValidatorConfig
    statements: list[exp.Expression] = field(default_factory=list)  # every parsed statement (R2)
    parse_error: str | None = None                                   # set when sqlglot fails (R1)
    # Runs EXPLAIN without executing and returns the plan (R10). None skips R10,
    # as on SQLite or in unit tests.
    explain: Callable[[str], dict] | None = None

    @property
    def restricted_tables(self) -> set[str]:
        return self.schema.restricted_tables

    @property
    def restricted_columns(self) -> set[str]:
        """As "table.column"; see also `schema.restricted_columns_of(table)`."""
        return self.schema.restricted_columns


class Rule:
    """One production rule: IF `check` finds violations THEN `action`.

    Adding a rule means adding one subclass to `rules.ALL_RULES` (NFR-M1).
    """

    id: ClassVar[str]        # "R6"; stable, referenced by docs, tests and the log
    name: ClassVar[str]      # "Restricted tables"
    stage: ClassVar[Stage]
    action: ClassVar[str] = "block"   # "block" | "rewrite"

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        """Return one plain-language message per violation; an empty list means pass.

        `tree` is None for PARSE-stage rules, which read `ctx` instead.
        """
        raise NotImplementedError

    def apply(self, tree: exp.Expression, ctx: ValidationContext) -> tuple[exp.Expression, list[str]]:
        """REWRITE-stage rules only: return the edited tree and notes for the log."""
        raise NotImplementedError
