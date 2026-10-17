"""R11 Row limit (rewrite). Owner: Afraz.

Tricky: an existing LIMIT 5000 must be lowered to 1000. R11 never blocks.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 2: R11 not implemented yet")

REWRITTEN = [
    ("SELECT * FROM orders", 1000),
    ("SELECT * FROM orders LIMIT 5000", 1000),
    ("SELECT id FROM orders UNION SELECT id FROM customers", 1000),
]

UNCHANGED = [
    "SELECT * FROM orders LIMIT 10",
    "SELECT * FROM orders LIMIT 1000",
]


@pytest.mark.parametrize("sql,limit", REWRITTEN)
def test_adds_or_lowers_limit(check, sql, limit):
    verdict = check(sql)
    assert verdict.allowed
    assert "R11" in verdict.rule_ids
    assert f"LIMIT {limit}" in verdict.sql.upper()


@pytest.mark.parametrize("sql", UNCHANGED)
def test_leaves_small_limits_alone(check, sql):
    verdict = check(sql)
    assert verdict.allowed
    assert "R11" not in verdict.rule_ids
