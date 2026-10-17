"""R6 Restricted tables. Owner: Afraz.

Tricky: a restricted table referenced only inside a subquery.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 2: R6 not implemented yet")

BLOCKED = [
    'SELECT email, password_hash FROM auth_user',
    'SELECT name FROM customers WHERE email IN (SELECT email FROM auth_user)',
]

ALLOWED = [
    'SELECT name FROM customers',
    "SELECT 'auth_user' AS note FROM customers",
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R6" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R6" not in check(sql).rule_ids
