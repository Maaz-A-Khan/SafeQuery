"""The knowledge base: rules R1 to R11, one class each. Owner: Afraz.

Each rule answers one question about the query and returns plain-language
messages; an empty list means the rule passes. Adding a rule means adding one
subclass and listing it in `ALL_RULES` (NFR-M1).

sqlglot node names have shifted between releases (Alter/AlterTable,
Union/SetOperation, ...), so node classes are looked up by name with
`_node_classes`, which silently skips names the installed version lacks.
"""

from __future__ import annotations

import re

from sqlglot import exp

from agent.types import Dialect
from agent.validator.base import Rule, Stage, ValidationContext

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _node_classes(*names: str) -> tuple[type, ...]:
    """The classes in `sqlglot.exp` that exist in the installed version."""
    found = (getattr(exp, name, None) for name in names)
    return tuple(c for c in found if isinstance(c, type))


# Union, Intersect and Except. `SetOperation` is the base class in new releases,
# `Union` is the base in old ones; listing both works for either.
_SET_OPERATIONS = _node_classes("SetOperation", "Union")


def _is_query(node: exp.Expression | None) -> bool:
    """True for a SELECT, a UNION/INTERSECT/EXCEPT of queries, or a bracketed query.

    A CTE (`WITH x AS (...) SELECT ...`) is a Select with a CTE attached, so it
    passes here; anything hidden inside the CTE is caught by R4.
    """
    if node is None:
        return False
    if isinstance(node, exp.Select):
        return True
    if isinstance(node, exp.Subquery):
        return _is_query(node.this)
    if isinstance(node, _SET_OPERATIONS):
        return _is_query(node.this) and _is_query(node.args.get("expression"))
    return False


def _cte_names(tree: exp.Expression) -> set[str]:
    return {cte.alias.lower() for cte in tree.find_all(exp.CTE) if cte.alias}


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


# --- Restricted names (R6) --------------------------------------------------

# The restricted lists on the schema are the source of truth: `agent.schema`
# pre-ticks the pattern defaults when it reads the database, and the user may
# untick or add names on the Schema page (FR-C8). R6 must not re-add defaults
# the user removed.


def _restricted_tables(ctx: ValidationContext) -> set[str]:
    """Restricted tables, lower-cased."""
    return {n.lower() for n in ctx.restricted_tables}


def _restricted_columns(ctx: ValidationContext) -> dict[str, set[str]]:
    """Lower-cased table -> restricted column names."""
    pairs = set(ctx.restricted_columns)
    by_table: dict[str, set[str]] = {}
    for pair in pairs:
        table, _, column = pair.partition(".")
        if column:
            by_table.setdefault(table.lower(), set()).add(column.lower())
    return by_table


# --- Structure --------------------------------------------------------------

class Parseable(Rule):
    id = "R1"
    name = "Parseable"
    stage = Stage.PARSE

    def check(
        self,
        tree: exp.Expression | None,
        ctx: ValidationContext,
    ) -> list[str]:
        if ctx.parse_error:
            return ["The generated query could not be parsed."]
        if not ctx.statements:
            return ["The generated query is empty."]

        # sqlglot can sometimes recover malformed SQL such as
        # "SELEC * FORM orders" as an ALIAS expression.
        # Treat that as a parse failure so R1 catches it.
        if ctx.statements:
            root = ctx.statements[0]
            if isinstance(root, exp.Alias):
                return ["The generated query could not be parsed."]

        return []
    
class SingleStatement(Rule):
    id = "R2"
    name = "Single statement"
    stage = Stage.PARSE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if ctx.parse_error or not ctx.statements:
            return []  # R1 already explains this
        if len(ctx.statements) != 1:
            return ["Only one query can run at a time."]
        return []


# --- Read-only --------------------------------------------------------------


class ReadOnlyStatement(Rule):
    id = "R3"
    name = "Read-only statement"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if _is_query(tree):
            return []
        kind = type(tree).__name__.upper() if tree is not None else "empty"
        return [f"Only read-only SELECT queries are allowed (found a {kind} statement)."]


# Statements that write, change structure or privileges, or run administrative
# commands. `Command` is sqlglot's fallback for statements it cannot parse
# (VACUUM, CALL, ...), so unknown statements are blocked too.
_WRITE_NODES = _node_classes(
    "Insert", "Update", "Delete", "Merge", "Drop", "Create",
    "Alter", "AlterTable", "TruncateTable", "Truncate",
    "Grant", "Revoke", "Command", "Set", "Pragma", "Copy",
    "LoadData", "Attach", "Detach", "Analyze", "Comment", "Kill",
)
_INTO = _node_classes("Into")
# SELECT ... FOR UPDATE / FOR SHARE / LOCK IN SHARE MODE: reads that lock rows.
_LOCK = _node_classes("Lock")


class NoWriteNodes(Rule):
    """Why R4 exists next to R3: R3 only looks at the ROOT of the statement.

    `SELECT * INTO newtable FROM t` parses as a Select, so R3 passes it, yet it
    creates a table. And `WITH d AS (DELETE ... RETURNING *) SELECT * FROM d`
    is a Select whose CTE deletes rows. R4 searches the WHOLE tree, so a write
    cannot hide below a harmless-looking root.
    """

    id = "R4"
    name = "No write nodes"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if tree is None:
            return []
        messages: list[str] = []
        seen: set[str] = set()
        for node in tree.find_all(*_WRITE_NODES, *_INTO, *_LOCK):
            kind = type(node).__name__
            if kind in seen:
                continue
            seen.add(kind)
            if _INTO and isinstance(node, _INTO):
                messages.append(
                    "`SELECT ... INTO` creates a new table, so it is not allowed."
                )
            elif _LOCK and isinstance(node, _LOCK):
                messages.append(
                    "`FOR UPDATE` and `FOR SHARE` lock rows, so they are not allowed."
                )
            else:
                messages.append(
                    f"The `{kind.upper()}` operation is not allowed; only reading data is."
                )
        return messages


# --- Access -----------------------------------------------------------------

_DEFAULT_SCHEMAS = {"public", "main"}  # a qualifier that still means "this database"


class KnownTables(Rule):
    id = "R5"
    name = "Known tables"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if tree is None:
            return []
        known = {n.lower() for n in ctx.schema.tables}
        ctes = _cte_names(tree)
        system = {s.lower() for s in ctx.config.system_schemas}
        messages: list[str] = []
        for table in tree.find_all(exp.Table):
            name = table.name
            if not name:
                continue  # a table-valued function; R8 judges the function itself
            db = (table.db or "").lower()
            if db in system:
                continue  # R7 reports system catalogs
            if db and db not in _DEFAULT_SCHEMAS:
                label = f"{table.db}.{name}"
            elif not db and name.lower() in ctes:
                continue
            elif name.lower() in known:
                continue
            else:
                label = name
            message = f"Table `{label}` does not exist in this database."
            if message not in messages:
                messages.append(message)
        return messages


class RestrictedData(Rule):
    id = "R6"
    name = "Restricted tables and columns"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if tree is None:
            return []
        restricted_tables = _restricted_tables(ctx)
        restricted_cols = _restricted_columns(ctx)
        real_names = {n.lower(): n for n in ctx.schema.tables}
        messages: list[str] = []

        def add(message: str) -> None:
            if message not in messages:
                messages.append(message)

        tables = [t for t in tree.find_all(exp.Table) if t.name]

        # alias or table name (lower) -> real tables it can refer to in this query
        lookup: dict[str, set[str]] = {}
        for table in tables:
            real = table.name.lower()
            if real not in real_names:
                continue  # a CTE name or an unknown table (R5)
            lookup.setdefault(real, set()).add(real)
            alias = (table.alias or "").lower()
            if alias:
                lookup.setdefault(alias, set()).add(real)
        in_query = {real for reals in lookup.values() for real in reals}

        # 1. restricted tables
        for table in tables:
            if table.name.lower() in restricted_tables:
                add(f"Access to `{real_names.get(table.name.lower(), table.name)}` is restricted.")

        # 1b. `FROM customers AS c(a, b, c, w)` renames columns by position, so
        # `w` would read password_hash without ever naming it.
        for table in tables:
            real = table.name.lower()
            alias = table.args.get("alias")
            if real in real_names and restricted_cols.get(real) and alias is not None and alias.args.get("columns"):
                add(
                    f"Renaming the columns of `{real_names[real]}` is not allowed because it has "
                    "restricted columns."
                )

        # 2. restricted columns, named explicitly
        for col in tree.find_all(exp.Column):
            if isinstance(col.this, exp.Star):
                continue  # handled in step 3
            cname = col.name.lower()
            qualifier = (col.table or "").lower()
            if qualifier and qualifier in lookup:
                candidates = lookup[qualifier]
            else:
                # Unqualified, or qualified by a CTE/subquery alias: be strict and
                # check every real table in the query.
                candidates = in_query
            for real in sorted(candidates):
                if cname in restricted_cols.get(real, ()):
                    add(f"Access to `{real_names[real]}.{col.name}` is restricted.")
            # `SELECT c FROM customers c` returns the whole row in PostgreSQL.
            if not qualifier:
                for real in sorted(lookup.get(cname, ())):
                    if restricted_cols.get(real):
                        add(
                            f"Selecting `{col.name}` as a whole row would expose "
                            f"restricted columns of `{real_names[real]}`."
                        )

        # 2b. JOIN ... USING (col) and NATURAL JOIN compare columns without naming
        # them as Column nodes, so a restricted column could be probed through
        # the join condition.
        for join in tree.find_all(exp.Join):
            for ident in join.args.get("using") or []:
                cname = ident.name.lower()
                for real in sorted(in_query):
                    if cname in restricted_cols.get(real, ()):
                        add(f"Access to `{real_names[real]}.{ident.name}` is restricted.")
            if str(join.args.get("method") or "").upper() == "NATURAL":
                for real in sorted(in_query):
                    if restricted_cols.get(real):
                        add(
                            f"`NATURAL JOIN` compares every same-named column, including "
                            f"restricted columns of `{real_names[real]}`. Join with `ON` instead."
                        )

        # 3. SELECT * and t.* over tables that have restricted columns
        for star in tree.find_all(exp.Star):
            parent = star.parent
            if isinstance(parent, exp.Count):
                continue  # COUNT(*) reads no column values
            if isinstance(parent, exp.Column):
                targets = set(lookup.get((parent.table or "").lower(), ()))
            else:
                select = star.find_ancestor(exp.Select)
                if select is None:
                    continue
                targets = {
                    t.name.lower()
                    for t in select.find_all(exp.Table)
                    if t.name
                    and t.name.lower() in real_names
                    and t.find_ancestor(exp.Select) is select  # this SELECT's own FROM/JOINs
                }
            for real in sorted(targets):
                cols = restricted_cols.get(real)
                if cols:
                    listed = ", ".join(f"`{c}`" for c in sorted(cols))
                    add(
                        f"`SELECT *` on `{real_names[real]}` would expose restricted "
                        f"columns ({listed}). Name the columns you need instead."
                    )
        return messages


_SESSION_PARAMETERS = _node_classes("SessionParameter")
_SESSION_KEYWORDS = {
    "user", "current_user", "session_user", "current_role", "system_user",
    "current_catalog", "current_schema",
}


class NoSystemCatalogs(Rule):
    id = "R7"
    name = "No system catalogs"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if tree is None:
            return []
        schemas = {s.lower() for s in ctx.config.system_schemas}
        tables = {t.lower() for t in ctx.config.system_tables}
        messages: list[str] = []
        for table in tree.find_all(exp.Table):
            name = (table.name or "").lower()
            db = (table.db or "").lower()
            catalog = (table.catalog or "").lower()
            if db in schemas or catalog in schemas:
                label = f"{db or catalog}.{name}" if name else (db or catalog)
            elif name and (name in tables or name.startswith(("pg_", "sqlite_"))):
                label = name
            else:
                continue
            message = f"System catalog `{label}` cannot be queried."
            if message not in messages:
                messages.append(message)

        # Server variables (MySQL `@@version`, `@@datadir`) describe the server, not the data.
        for param in tree.find_all(*_SESSION_PARAMETERS):
            message = f"Server variable `@@{param.name}` cannot be read."
            if message not in messages:
                messages.append(message)

        # A bare `user` / `session_user` in PostgreSQL is the login name, not a
        # column, unless a table in the query really has a column of that name.
        in_query = {t.name.lower() for t in tree.find_all(exp.Table) if t.name}
        real_columns = {
            c.name.lower()
            for name, table in ctx.schema.tables.items()
            if name.lower() in in_query
            for c in table.columns
        }
        for col in tree.find_all(exp.Column):
            ident = col.this
            if (
                isinstance(ident, exp.Identifier)
                and not ident.quoted
                and not col.table
                and ident.name.lower() in _SESSION_KEYWORDS
                and ident.name.lower() not in real_columns
            ):
                message = f"`{ident.name}` reveals the database login and cannot be queried."
                if message not in messages:
                    messages.append(message)
        return messages


# --- Resource and side effects ----------------------------------------------

# sqlglot types common functions (exp.Count, exp.Round, ...) and names do not
# always match the SQL spelling (DATE_TRUNC -> TimestampTrunc, STRFTIME ->
# TimeToStr). This maps an allowed SQL name to the node names it may appear as.
_ALIASES: dict[str, frozenset[str]] = {
    "date_trunc": frozenset({"timestamp_trunc", "datetime_trunc"}),
    "strftime": frozenset({"time_to_str", "ts_or_ds_to_timestamp"}),
    "year": frozenset({"ts_or_ds_to_date"}),
    "month": frozenset({"ts_or_ds_to_date"}),
    "day": frozenset({"ts_or_ds_to_date"}),
    "to_char": frozenset({"time_to_str"}),
    "position": frozenset({"str_position", "strpos"}),
    "substr": frozenset({"substring"}),
    "now": frozenset({"current_timestamp"}),
    "date": frozenset({"ts_or_ds_to_date"}),
    "date_part": frozenset({"extract"}),
    "ceil": frozenset({"ceiling"}),
    "ceiling": frozenset({"ceil"}),
    "char_length": frozenset({"length"}),
    "ifnull": frozenset({"coalesce"}),
    "ltrim": frozenset({"trim"}),
    "rtrim": frozenset({"trim"}),
    "string_agg": frozenset({"group_concat"}),
    "stddev": frozenset({"stddev_samp"}),
    "variance": frozenset({"variance_samp"}),
    "power": frozenset({"pow"}),
}

# Syntax that sqlglot represents as a function node but that is not a function call.
# `Connector` is AND, OR and XOR, which sqlglot 30 makes `Func` subclasses; without
# it every WHERE with two conditions was blocked. Their operands are still checked.
_STRUCTURAL = _node_classes("Exists", "Any", "All", "Array", "Connector")
_ANONYMOUS = _node_classes("Anonymous", "AnonymousAggFunc")

_OUTFILE = re.compile(r"\binto\s+(outfile|dumpfile)\b", re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _allowed_names(ctx: ValidationContext) -> set[str]:
    allowed = {f.lower() for f in ctx.config.allowed_functions}
    for name in list(allowed):
        allowed |= _ALIASES.get(name, frozenset())
    return allowed


def _function_names(node: exp.Expression) -> tuple[str, set[str]]:
    """(name to show the user, every name this node may be allowed under)."""
    if isinstance(node, _ANONYMOUS):
        name = str(node.name).lower()
        return name, {name}
    names: set[str] = set()
    try:
        listed = [n.lower() for n in type(node).sql_names()]
    except Exception:  # an unusual node without sql_names()
        listed = []
    names.update(listed)
    snake = _camel_to_snake(type(node).__name__)
    names.add(snake)
    if isinstance(node, exp.Cast):  # TryCast and friends
        names.add("cast")
    return (listed[0] if listed else snake), names


class AllowedFunctions(Rule):
    id = "R8"
    name = "Allowed functions only"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if tree is None:
            return []
        allowed = _allowed_names(ctx)
        messages: list[str] = []
        for node in tree.find_all(exp.Func):
            if _STRUCTURAL and isinstance(node, _STRUCTURAL):
                continue
            shown, names = _function_names(node)
            # `evil.upper(x)` parses as the built-in UPPER under a Dot, but the
            # database would call whatever `upper` lives in schema `evil`.
            parent = node.parent
            if isinstance(parent, exp.Dot) and parent.expression is node:
                message = (
                    f"The schema-qualified function `{parent.this.sql()}.{shown}` is not allowed; "
                    "only built-in functions may be called."
                )
            elif names & allowed:
                continue
            else:
                message = f"The function `{shown}` is not on the allowed list."
            if message not in messages:
                messages.append(message)
        # SELECT ... INTO OUTFILE / DUMPFILE writes a file on the database server.
        if _OUTFILE.search(_STRING_LITERAL.sub("''", ctx.sql)):
            messages.append("`INTO OUTFILE` and `INTO DUMPFILE` write files and are not allowed.")
        return messages


class JoinLimit(Rule):
    id = "R9"
    name = "Join limit"
    stage = Stage.TREE

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if tree is None:
            return []
        joins = sum(1 for _ in tree.find_all(exp.Join))  # comma joins count too
        if joins > ctx.config.max_joins:
            return [f"The query uses {joins} joins; the limit is {ctx.config.max_joins}."]
        return []


_UNBOUNDED = -1  # a LIMIT that is not a plain number (LIMIT ALL, a parameter, ...)


def _outermost(tree: exp.Expression) -> exp.Expression:
    """Unwrap `(SELECT ...)` so the LIMIT goes on the query itself."""
    node = tree
    while (
        isinstance(node, exp.Subquery)
        and node.this is not None
        and not any(node.args.get(k) for k in ("limit", "order", "offset"))
    ):
        node = node.this
    return node


def _limit_value(node: exp.Expression) -> int | None:
    """None if there is no LIMIT, _UNBOUNDED if it is not a plain number."""
    limit = node.args.get("limit")
    if limit is None:
        return None
    if isinstance(limit, exp.Limit):
        count = limit.args.get("expression")
        if count is None:
            return _UNBOUNDED
    else:  # exp.Fetch: FETCH FIRST n ROWS ONLY
        count = limit.args.get("count")
        if count is None:
            return 1
    if isinstance(count, exp.Literal) and not count.is_string:
        try:
            return int(count.name)
        except ValueError:
            return _UNBOUNDED
    return _UNBOUNDED


class RowLimit(Rule):
    id = "R11"
    name = "Row limit"
    stage = Stage.REWRITE
    action = "rewrite"

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if tree is None:
            return []
        root = _outermost(tree)
        if not isinstance(root, (exp.Select, exp.Subquery, *_SET_OPERATIONS)):
            return []
        current = _limit_value(root)
        n = ctx.config.row_limit
        if current is None:
            return [f"No row limit was set, so LIMIT {n} was added."]
        if current == _UNBOUNDED or current > n:
            return [f"The row limit was lowered to {n}."]
        return []

    def apply(self, tree: exp.Expression, ctx: ValidationContext) -> tuple[exp.Expression, list[str]]:
        notes = self.check(tree, ctx)
        if not notes:
            return tree, []  # a LIMIT of `row_limit` or less is the user's answer: keep it
        n = ctx.config.row_limit
        new_root = _outermost(tree.copy())
        limit = new_root.args.get("limit")
        if isinstance(limit, exp.Limit):
            limit.set("expression", exp.Literal.number(n))  # keeps any OFFSET
        else:  # no limit, or a FETCH clause
            new_root.set("limit", exp.Limit(expression=exp.Literal.number(n)))
        return new_root, notes


# --- Cost (the only rule that contacts the database) -------------------------


def _as_number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pg_total_cost(plan) -> float | None:
    """PostgreSQL `EXPLAIN (FORMAT JSON)`: [{"Plan": {"Total Cost": ...}}].

    Also accepts the unwrapped {"Plan": {...}}, the inner plan node, or a
    normalised {"total_cost": ...}.
    """
    node = plan
    if isinstance(node, (list, tuple)) and node:
        node = node[0]
    if isinstance(node, dict) and "Plan" in node:
        node = node["Plan"]
    if isinstance(node, dict):
        for key in ("Total Cost", "total_cost"):
            if key in node:
                return _as_number(node[key])
    return None


def _mysql_rows_examined(plan) -> float | None:
    """MySQL `EXPLAIN FORMAT=JSON` (sum of rows_examined_per_scan), classic
    EXPLAIN rows (sum of "rows"), or a normalised {"rows_examined": ...}."""
    if isinstance(plan, dict) and "rows_examined" in plan:
        return _as_number(plan["rows_examined"])
    total = 0.0
    found = False

    def walk(obj) -> None:
        nonlocal total, found
        if isinstance(obj, dict):
            if "rows_examined_per_scan" in obj:
                value = _as_number(obj["rows_examined_per_scan"])
                if value is not None:
                    total += value
                    found = True
            elif "select_type" in obj and "rows" in obj:
                value = _as_number(obj["rows"])
                if value is not None:
                    total += value
                    found = True
            for child in obj.values():
                if isinstance(child, (dict, list, tuple)):
                    walk(child)
        elif isinstance(obj, (list, tuple)):
            for child in obj:
                walk(child)

    walk(plan)
    return total if found else None


class CostCeiling(Rule):
    id = "R10"
    name = "Cost ceiling"
    stage = Stage.COST

    def check(self, tree: exp.Expression | None, ctx: ValidationContext) -> list[str]:
        if ctx.explain is None or ctx.dialect == Dialect.SQLITE:
            return []  # SQLite has no cost estimate; unit tests pass no explain
        try:
            # ctx.sql is the SQL after R11's rewrite, so its LIMIT is in the estimate.
            plan = ctx.explain(ctx.sql)
        except Exception as exc:  # fail closed: an unpriced query does not run
            detail = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else ""
            return [
                "The query's cost could not be estimated, so it was not run"
                + (f" ({type(exc).__name__}: {detail})." if detail else ".")
            ]

        if ctx.dialect == Dialect.POSTGRESQL:
            cost = _pg_total_cost(plan)
            if cost is None:
                return ["The query's cost could not be read from the database plan, so it was not run."]
            limit = ctx.config.max_cost_postgres
            if cost > limit:
                return [
                    f"The estimated cost ({cost:,.0f}) is above the ceiling ({limit:,.0f}). "
                    "Add filters or use fewer joins."
                ]
        elif ctx.dialect == Dialect.MYSQL:
            rows = _mysql_rows_examined(plan)
            if rows is None:
                return ["The query's cost could not be read from the database plan, so it was not run."]
            limit = ctx.config.max_rows_examined_mysql
            if rows > limit:
                return [
                    f"The query would examine about {rows:,.0f} rows; the ceiling is {limit:,.0f}. "
                    "Add filters or use fewer joins."
                ]
        return []


# In evaluation order. The engine runs them stage by stage (see `Stage`).
ALL_RULES: list[Rule] = [
    Parseable(),
    SingleStatement(),
    ReadOnlyStatement(),
    NoWriteNodes(),
    KnownTables(),
    RestrictedData(),
    NoSystemCatalogs(),
    AllowedFunctions(),
    JoinLimit(),
    RowLimit(),
    CostCeiling(),
]
