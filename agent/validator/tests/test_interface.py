"""Checks the Phase 1 interface. These pass now and must keep passing."""

from agent.types import Dialect, Verdict
from agent.validator.base import Rule, Stage
from agent.validator.rules import ALL_RULES


def test_every_rule_once():
    assert [r.id for r in ALL_RULES] == [
        "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R11", "R10",
    ]


def test_rules_are_fully_declared():
    for rule in ALL_RULES:
        assert isinstance(rule, Rule)
        assert rule.name
        assert rule.action in ("block", "rewrite")
        assert isinstance(rule.stage, Stage)


def test_row_limit_runs_before_cost_ceiling():
    stage = {r.id: r.stage for r in ALL_RULES}
    assert stage["R11"] < stage["R10"]
    assert all(stage[r] == Stage.PARSE for r in ("R1", "R2"))


def test_validate_returns_a_verdict(check):
    verdict = check("SELECT name FROM customers")
    assert isinstance(verdict, Verdict)
    assert verdict.label in ("ALLOW", "BLOCK")
    assert verdict.sql


def test_dialect_values_match_sqlalchemy_names():
    assert {d.value for d in Dialect} == {"postgresql", "mysql", "sqlite"}
