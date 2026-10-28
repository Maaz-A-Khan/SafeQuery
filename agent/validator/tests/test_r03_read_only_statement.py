"""R3 Read-only statement. Owner: Afraz."""

import pytest


BLOCKED = [
    "DELETE FROM orders WHERE status = 'cancelled'",
    "UPDATE orders SET status = 'shipped'",
    'DROP TABLE orders',
]

ALLOWED = [
    'WITH recent AS (SELECT * FROM orders) SELECT * FROM recent',
    'SELECT id FROM orders UNION SELECT id FROM customers',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R3" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R3" not in check(sql).rule_ids
