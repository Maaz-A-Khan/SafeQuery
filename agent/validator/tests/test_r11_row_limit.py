"""R11 Row limit (rewrite). Owner: Afraz.

Tricky: an existing LIMIT 5000 must be lowered to 1000, but a smaller LIMIT is
the user's answer ("top 5") and must be kept exactly. R11 never blocks.
"""

import pytest

from agent.types import Dialect

REWRITTEN = [
    ("SELECT * FROM orders", "LIMIT 1000"),
    ("SELECT * FROM orders LIMIT 5000", "LIMIT 1000"),
    ("SELECT id FROM orders UNION SELECT id FROM customers", "LIMIT 1000"),
    ("SELECT * FROM orders LIMIT ALL", "LIMIT 1000"),
    ("SELECT * FROM orders FETCH FIRST 5000 ROWS ONLY", "LIMIT 1000"),
    ("SELECT * FROM orders LIMIT 5000 OFFSET 20", "LIMIT 1000 OFFSET 20"),
]

UNCHANGED = [
    ("SELECT * FROM orders LIMIT 10", "LIMIT 10"),
    ("SELECT * FROM orders LIMIT 1000", "LIMIT 1000"),
    ("SELECT name FROM customers ORDER BY name LIMIT 5", "LIMIT 5"),
    ("SELECT * FROM orders LIMIT 10 OFFSET 20", "LIMIT 10 OFFSET 20"),
    ("SELECT * FROM orders FETCH FIRST 3 ROWS ONLY", "FETCH FIRST 3 ROWS ONLY"),
]


@pytest.mark.parametrize("sql,expected", REWRITTEN)
def test_adds_or_lowers_limit(check, sql, expected):
    verdict = check(sql)
    assert verdict.allowed
    assert "R11" in verdict.rule_ids
    assert expected in verdict.sql.upper()


@pytest.mark.parametrize("sql,expected", UNCHANGED)
def test_keeps_limits_within_the_cap(check, sql, expected):
    verdict = check(sql)
    assert verdict.allowed
    assert "R11" not in verdict.rule_ids
    assert expected in verdict.sql.upper()
    assert "LIMIT 1000" not in verdict.sql.upper() or expected == "LIMIT 1000"


def test_mysql_offset_comma_form_is_kept(check):
    verdict = check("SELECT name FROM customers LIMIT 10, 5", Dialect.MYSQL)
    assert "R11" not in verdict.rule_ids
    assert "LIMIT 5 OFFSET 10" in verdict.sql.upper()
