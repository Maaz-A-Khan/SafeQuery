"""R7 No system catalogs. Owner: Afraz."""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 2: R7 not implemented yet")

BLOCKED = [
    'SELECT usename, passwd FROM pg_catalog.pg_shadow',
    'SELECT table_name FROM information_schema.tables',
    'SELECT * FROM pg_user',
]

ALLOWED = [
    'SELECT * FROM orders',
    'SELECT name FROM customers',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R7" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R7" not in check(sql).rule_ids
