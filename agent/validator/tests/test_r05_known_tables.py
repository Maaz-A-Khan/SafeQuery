"""R5 Known tables. Owner: Afraz.

Tricky: a CTE named like a missing table must be ALLOWED.
"""

import pytest


BLOCKED = [
    'SELECT * FROM order_history',
    'SELECT * FROM orders JOIN refunds ON refunds.order_id = orders.id',
]

ALLOWED = [
    'SELECT * FROM orders',
    'WITH order_history AS (SELECT * FROM orders) SELECT * FROM order_history',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R5" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R5" not in check(sql).rule_ids
