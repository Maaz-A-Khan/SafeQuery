"""R4 No write nodes. Owner: Afraz.

Tricky: a DELETE inside a CTE, and SELECT ... INTO (parses as a Select, creates a table).
"""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 2: R4 not implemented yet")

BLOCKED = [
    'WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone',
    'SELECT * INTO orders_copy FROM orders',
]

ALLOWED = [
    'WITH totals AS (SELECT customer_id, SUM(total) AS t FROM orders GROUP BY customer_id) SELECT * FROM totals',
    'SELECT drop_date FROM shipments',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R4" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R4" not in check(sql).rule_ids
