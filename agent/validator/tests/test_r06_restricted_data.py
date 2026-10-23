"""R6 Restricted tables and columns. Owner: Afraz.

Tricky: a restricted table only inside a subquery; a restricted column used only in
WHERE; SELECT * and c.* over a table with a restricted column; `authors` must be ALLOWED
(whole-word matching: "auth" matches auth_user, not authors).
"""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 2: R6 not implemented yet")

BLOCKED = [
    'SELECT email, password_hash FROM auth_user',
    'SELECT name FROM customers WHERE email IN (SELECT email FROM auth_user)',
    'SELECT name FROM customers WHERE password_hash IS NULL',
    'SELECT * FROM customers',
    'SELECT c.* FROM customers c JOIN orders o ON o.customer_id = c.id',
]

ALLOWED = [
    'SELECT name FROM customers',
    "SELECT 'auth_user' AS note FROM customers",
    'SELECT name FROM authors',
    'SELECT * FROM orders',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R6" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R6" not in check(sql).rule_ids
