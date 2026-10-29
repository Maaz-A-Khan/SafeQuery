"""R8 Allowed functions only. Owner: Afraz.

Tricky: uppercase PG_SLEEP; query_to_xml hides a table from the tree; set_config
turns read-only mode off from inside a SELECT.
"""

import pytest


BLOCKED = [
    'SELECT *, pg_sleep(60) FROM customers',
    'SELECT PG_SLEEP(5) FROM customers',
    "SELECT query_to_xml('select * from auth_user', true, true, '')",
    "SELECT set_config('default_transaction_read_only', 'off', false)",
    'SELECT evil.upper(name) FROM customers',
    'SELECT pg_catalog.pg_sleep(1)',
]

ALLOWED = [
    'SELECT UPPER(name), COUNT(*) FROM customers GROUP BY 1',
    'SELECT ROUND(AVG(total), 2) FROM orders',
    'SELECT name, ROW_NUMBER() OVER (ORDER BY name) FROM customers',
    "SELECT STRING_AGG(name, ', ') FROM customers",
    'SELECT id, LAG(total) OVER (ORDER BY created_at) FROM orders',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R8" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R8" not in check(sql).rule_ids
