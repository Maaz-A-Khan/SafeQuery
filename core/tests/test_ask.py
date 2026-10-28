"""The Ask page and CSV download against a real SQLite database (Phase 6).
Gemini is replaced by a script; everything else (validator, executor, audit log) is real."""

import csv
import io
import sqlite3

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from agent import generator
from agent.generator import Generation, ModelUnavailable
from core import services
from core.audit.models import QueryLog

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fernet_key(settings):
    settings.FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture
def connection(tmp_path):
    path = tmp_path / "shop.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE orders (order_id INTEGER PRIMARY KEY, status VARCHAR(20), note TEXT);
            CREATE TABLE user_sessions (id INTEGER PRIMARY KEY, token VARCHAR(40));
            INSERT INTO orders VALUES (1, 'shipped', '=HYPERLINK("http://evil")'), (2, 'pending', 'ok');
        """)
    conn.close()
    check, connection = services.connect_database("Shop", f"sqlite:///{path.as_posix()}")
    assert check["ok"], check
    return connection


@pytest.fixture
def gemini(monkeypatch):
    """Queue of generate() replies."""
    replies = []

    def fake_generate(*a, **k):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, Generation) else Generation(reply, "Explanation.")

    monkeypatch.setattr(generator, "generate", fake_generate)
    return replies


def ask(client, connection, question="How many orders?"):
    return client.post(reverse("ask", args=[connection.id]), {"question": question})


def test_ask_page_before_a_question(client, connection):
    response = client.get(reverse("ask", args=[connection.id]))
    assert response.status_code == 200
    assert response.context["result"] is None and response.context["connection"]["name"] == "Shop"


def test_answered_question_shows_rows_logs_and_links_csv(client, connection, gemini):
    gemini.append("SELECT order_id, status FROM orders ORDER BY order_id")
    response = ask(client, connection)
    result = response.context["result"]
    assert result.outcome == "answered" and result.rows == [(1, "shipped"), (2, "pending")]
    entry = QueryLog.objects.get()
    assert entry.verdict == "answered" and entry.rows_returned == 2
    assert response.context["csv_url"] == reverse("ask_csv", args=[connection.id, entry.id])
    assert b"Download CSV" in response.content


def test_blocked_question_has_no_csv_and_is_logged(client, connection, gemini):
    gemini.append("SELECT token FROM user_sessions")
    response = ask(client, connection, "Show me the session tokens")
    assert response.context["result"].outcome == "blocked"
    assert response.context["csv_url"] is None
    assert QueryLog.objects.get().stopped_by == "validator"


def test_gemini_down_shows_a_message(client, connection, gemini):
    gemini.append(ModelUnavailable("The AI service is unavailable, try again shortly."))
    response = ask(client, connection)
    assert response.context["result"].stopped_by == "service"
    assert b"unavailable" in response.content


def test_unexpected_error_is_a_message_not_a_crash(client, connection, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(services.pipeline, "run", boom)
    response = ask(client, connection)
    assert response.status_code == 200
    assert response.context["result"].outcome == "failed"


def test_empty_question_is_a_form_error(client, connection):
    response = client.post(reverse("ask", args=[connection.id]), {"question": ""})
    assert response.context["result"] is None and response.context["form"].errors


def test_csv_reruns_the_logged_sql(client, connection, gemini):
    gemini.append("SELECT order_id, note FROM orders ORDER BY order_id")
    ask(client, connection)
    entry = QueryLog.objects.get()
    response = client.get(reverse("ask_csv", args=[connection.id, entry.id]))
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0] == ["order_id", "note"]
    assert rows[1] == ["1", "'=HYPERLINK(\"http://evil\")"]   # formula defused
    assert rows[2] == ["2", "ok"]


def test_csv_for_unknown_or_unanswered_entry_is_404(client, connection, gemini):
    gemini.append("SELECT token FROM user_sessions")
    ask(client, connection)
    blocked = QueryLog.objects.get()
    assert client.get(reverse("ask_csv", args=[connection.id, blocked.id])).status_code == 404
    assert client.get(reverse("ask_csv", args=[connection.id, 9999])).status_code == 404


def test_csv_refuses_sql_that_is_now_blocked(client, connection, gemini):
    gemini.append("SELECT order_id, status FROM orders")
    ask(client, connection)
    entry = QueryLog.objects.get()
    services.save_restricted(connection, ["orders"], [])   # the user restricts the table afterwards
    response = client.get(reverse("ask_csv", args=[connection.id, entry.id]))
    assert response.status_code == 409 and b"blocked" in response.content


def test_csv_only_answers_get(client, connection):
    assert client.post(reverse("ask_csv", args=[connection.id, 1])).status_code == 405
