"""Limits and lists, kept out of code (FR-V9).

`safequery/settings.py` builds the live `AgentConfig`; tests and the benchmark
construct their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidatorConfig:
    max_joins: int = 6                          # R9
    max_cost_postgres: float = 100_000          # R10
    max_rows_examined_mysql: int = 1_000_000    # R10
    row_limit: int = 1000                       # R11
    # R6 default restricted lists, matched against whole words of a name split on
    # "_" and case changes, singular or plural: "auth" matches auth_user, not authors.
    restricted_table_patterns: tuple[str, ...] = (
        "user", "auth", "password", "token", "credential", "session",
    )
    restricted_column_patterns: tuple[str, ...] = (
        "password", "passwd", "hash", "secret", "token", "ssn",
    )
    system_schemas: tuple[str, ...] = (         # R7
        "information_schema", "pg_catalog", "mysql", "performance_schema", "sys",
    )
    system_tables: tuple[str, ...] = ("sqlite_master", "sqlite_schema")  # R7
    # R8 is an ALLOW list: any function not listed is blocked (fails closed, NFR-S3).
    # A deny list misses functions such as query_to_xml() and set_config(), which
    # run SQL or change settings from inside a SELECT. Lower-case SQL names.
    # Every name here is a pure, read-only built-in; schema-qualified calls are
    # always blocked. sqlglot types common functions (exp.Count, exp.Upper, ...) and
    # puts unknown ones in exp.Anonymous; see rules._ALIASES for spelling differences.
    allowed_functions: frozenset[str] = frozenset({
        # aggregates
        "count", "sum", "avg", "min", "max", "string_agg", "group_concat",
        "stddev", "variance", "percentile_cont", "percentile_disc",
        # window functions
        "row_number", "rank", "dense_rank", "ntile", "percent_rank", "cume_dist",
        "lag", "lead", "first_value", "last_value",
        # null handling and comparison
        "coalesce", "nullif", "ifnull", "greatest", "least",
        # text
        "upper", "lower", "trim", "ltrim", "rtrim", "length", "char_length",
        "substring", "substr", "concat", "concat_ws", "replace", "left", "right",
        "position", "initcap",
        # numbers
        "round", "abs", "floor", "ceil", "ceiling", "power", "sqrt", "sign",
        # dates
        "date_trunc", "extract", "date_part", "strftime", "date", "year", "month", "day",
        "to_char", "age", "julianday", "datediff",
        "now", "current_date", "current_timestamp",
        # types and conditionals
        "cast", "case", "if",
    })


@dataclass(frozen=True)
class ExecutorConfig:
    statement_timeout_s: float = 5.0   # FR-Q4, NFR-P3
    row_cap: int = 1000                # fetchmany(row_cap), NFR-P4


@dataclass(frozen=True)
class GeminiConfig:
    model: str = "gemini-3.6-flash"    # D-027
    temperature: float = 0.0
    max_attempts: int = 3              # FR-Q5, NFR-R2: per step
    max_plan_steps: int = 4            # FR-Q8
    max_step_values: int = 500         # values carried from one step to the next (D-028)
    request_timeout_s: float = 60.0    # a Gemini call that takes longer counts as unavailable
    api_key: str = field(default="", repr=False)   # GEMINI_API_KEY; repr=False keeps it out of logs


@dataclass(frozen=True)
class Switches:
    """Every safety layer, on by default. Turned off ONLY by the ablation run in
    `eval/`, against a throwaway database copy. Never off in the running app."""

    validator: bool = True
    privilege_check: bool = True
    readonly_session: bool = True
    cache: bool = True                 # off during benchmarks so every question hits Gemini


@dataclass(frozen=True)
class AgentConfig:
    validator: ValidatorConfig = field(default_factory=ValidatorConfig)
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    switches: Switches = field(default_factory=Switches)
    sample_values_max_distinct: int = 20   # FR-C7
    schema_linking_threshold: int = 20     # FR-C11 (stretch): above this many tables
