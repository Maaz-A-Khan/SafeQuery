"""The knowledge base: rules R1 to R11, one class each. Owner: Afraz.

Each rule is specified in the "Validator Rule Base" note: what it protects
against, what it checks, an example it blocks and one it allows, and its message.
Phase 1 provides the skeletons only; every `check` is a TODO.
"""

from __future__ import annotations

from sqlglot import exp

from agent.validator.base import Rule, Stage, ValidationContext


# --- Structure --------------------------------------------------------------


class Parseable(Rule):
    id = "R1"
    name = "Parseable"
    stage = Stage.PARSE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): "The generated query could not be parsed." when ctx.parse_error is set
        raise NotImplementedError


class SingleStatement(Rule):
    id = "R2"
    name = "Single statement"
    stage = Stage.PARSE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): "Only one query can run at a time." unless len(ctx.statements) == 1
        raise NotImplementedError


# --- Read-only --------------------------------------------------------------


class ReadOnlyStatement(Rule):
    id = "R3"
    name = "Read-only statement"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): root is Select, a Union/Intersect/Except of selects, or a Select with a CTE
        raise NotImplementedError


class NoWriteNodes(Rule):
    id = "R4"
    name = "No write nodes"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): no Insert/Update/Delete/Merge/Drop/Create/Alter/TruncateTable/Grant/Command
        # anywhere. Also block exp.Into: `SELECT ... INTO newtable` parses as a Select.
        raise NotImplementedError


# --- Access -----------------------------------------------------------------


class KnownTables(Rule):
    id = "R5"
    name = "Known tables"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): every exp.Table is in ctx.schema, excluding the query's own CTE names
        raise NotImplementedError


class RestrictedTables(Rule):
    id = "R6"
    name = "Restricted tables"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): "Access to `x` is restricted." for every exp.Table in ctx.restricted
        raise NotImplementedError


class NoSystemCatalogs(Rule):
    id = "R7"
    name = "No system catalogs"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): ctx.config.system_schemas, ctx.config.system_tables, pg_-prefixed tables
        raise NotImplementedError


# --- Resource and side effects ----------------------------------------------


class AllowedFunctions(Rule):
    id = "R8"
    name = "Allowed functions only"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): block any function not in ctx.config.allowed_functions, and
        # SELECT ... INTO OUTFILE / DUMPFILE
        raise NotImplementedError


class JoinLimit(Rule):
    id = "R9"
    name = "Join limit"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): count exp.Join nodes (comma joins are Join nodes too) <= ctx.config.max_joins
        raise NotImplementedError


class RowLimit(Rule):
    id = "R11"
    name = "Row limit"
    stage = Stage.REWRITE
    action = "rewrite"

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): note when the outermost LIMIT is missing or above ctx.config.row_limit
        raise NotImplementedError

    def apply(self, tree: exp.Expression, ctx: ValidationContext) -> tuple[exp.Expression, list[str]]:
        # TODO(Afraz): add or lower LIMIT; the engine regenerates SQL in ctx.dialect
        raise NotImplementedError


class CostCeiling(Rule):
    id = "R10"
    name = "Cost ceiling"
    stage = Stage.COST

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        # TODO(Afraz): skip when ctx.explain is None; PostgreSQL total cost vs
        # max_cost_postgres, MySQL rows examined vs max_rows_examined_mysql
        raise NotImplementedError


# In evaluation order. The engine runs them stage by stage (see `Stage`).
ALL_RULES: list[Rule] = [
    Parseable(),
    SingleStatement(),
    ReadOnlyStatement(),
    NoWriteNodes(),
    KnownTables(),
    RestrictedTables(),
    NoSystemCatalogs(),
    AllowedFunctions(),
    JoinLimit(),
    RowLimit(),
    CostCeiling(),
]
