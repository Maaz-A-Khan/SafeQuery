"""The engine: stage order, early stop on a block, fail closed. Owner: Afraz."""

from dataclasses import replace

import pytest

from agent.types import Dialect
from agent.validator import engine, validate
from agent.validator.rules import RestrictedData


class SpyExplain:
    """A fake EXPLAIN that records every SQL string sent to the 'database'."""

    def __init__(self, cost=10):
        self.cost, self.seen = cost, []

    def __call__(self, sql):
        self.seen.append(sql)
        return {"Plan": {"Total Cost": self.cost}}


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "SELECT *, pg_sleep(60) FROM orders",
    "SELECT * FROM auth_user",
    "SELECT * FROM order_history",
    "SELECT * FROM orders; DROP TABLE orders",
    "SELEC * FORM orders",
])
def test_blocked_queries_never_reach_explain(check, sql):
    spy = SpyExplain()
    assert not check(sql, explain=spy).allowed
    assert spy.seen == []


def test_blocked_query_is_not_rewritten(check):
    verdict = check("SELECT * FROM auth_user")
    assert "R11" not in verdict.rule_ids
    assert verdict.sql == "SELECT * FROM auth_user"


def test_allowed_query_is_explained_once_after_rewrite(check):
    spy = SpyExplain()
    verdict = check("SELECT name FROM customers", explain=spy)
    assert verdict.allowed
    assert spy.seen == [verdict.sql]
    assert "LIMIT 1000" in spy.seen[0]


def test_every_tree_violation_is_reported(check):
    verdict = check("WITH gone AS (DELETE FROM orders RETURNING *) SELECT *, pg_sleep(1) FROM auth_user")
    assert {"R4", "R6", "R8"} <= set(verdict.rule_ids)


def test_rule_crash_fails_closed(check, monkeypatch):
    def boom(self, tree, ctx):
        raise RuntimeError("bug in a rule")

    monkeypatch.setattr(RestrictedData, "check", boom)
    verdict = check("SELECT name FROM customers")
    assert not verdict.allowed
    assert verdict.rule_ids == ["ENGINE"]
    assert "bug in a rule" not in verdict.hits[0].message  # internals stay out of the UI


def test_explain_failure_fails_closed(check):
    def broken(sql):
        raise ConnectionError("server gone")

    verdict = check("SELECT name FROM customers", explain=broken)
    assert not verdict.allowed
    assert "R10" in verdict.rule_ids


def test_unticked_defaults_are_respected(shop_schema):
    """The user unticked everything on the Schema page (FR-C8): R6 must not re-add it."""
    open_schema = replace(shop_schema, restricted_tables=set(), restricted_columns=set())
    assert validate("SELECT id, email FROM auth_user", open_schema, Dialect.POSTGRESQL).allowed
    assert validate("SELECT password_hash FROM customers", open_schema, Dialect.POSTGRESQL).allowed


def test_executed_sql_is_generated_from_the_validated_tree(check):
    verdict = check("/* hello */ select name from customers -- bye")
    assert verdict.allowed
    assert "--" not in verdict.sql
    assert "/*" not in verdict.sql


@pytest.mark.parametrize("sql", [
    "SELECT name FROM customers /*!50000 UNION SELECT password_hash FROM customers */",
    "SELECT name /*!, password_hash */ FROM customers",
    "SELECT name FROM customers /*! WHERE SLEEP(5) */",
    "SELECT name FROM customers # comment",
])
def test_mysql_executable_comments_never_reach_the_database(check, sql):
    """MySQL runs the body of `/*! ... */` as SQL, so no comment may survive into the executed SQL."""
    verdict = check(sql, Dialect.MYSQL)
    assert "/*" not in verdict.sql and "#" not in verdict.sql
    assert "password_hash" not in verdict.sql and "SLEEP" not in verdict.sql.upper()


def test_default_config_is_used(shop_schema):
    assert engine.validate("SELECT name FROM customers", shop_schema, Dialect.POSTGRESQL).allowed
