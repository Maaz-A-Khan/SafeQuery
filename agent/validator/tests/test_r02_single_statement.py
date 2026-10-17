"""R2 Single statement. Owner: Afraz.

Tricky: a second statement after a comment is blocked; a trailing semicolon is allowed.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 2: R2 not implemented yet")

BLOCKED = [
    'SELECT * FROM orders; DROP TABLE orders',
    'SELECT * FROM orders; -- harmless\nDELETE FROM orders',
]

ALLOWED = [
    'SELECT * FROM orders',
    'SELECT * FROM orders;',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R2" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R2" not in check(sql).rule_ids
