"""Connect and Schema pages with real databases (Phase 5)."""

import os
import sqlite3

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse
from sqlalchemy.engine import make_url

from core import services
from core.models import DatabaseConnection, SchemaSnapshot

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fernet_key(settings):
    settings.FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture
def shop_url(tmp_path):
    path = tmp_path / "shop.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE orders (order_id INTEGER PRIMARY KEY, status VARCHAR(20), customer_id INTEGER);
            CREATE TABLE user_sessions (id INTEGER PRIMARY KEY, token VARCHAR(40));
            INSERT INTO orders VALUES (1, 'shipped', 1), (2, 'shipped', 2), (3, 'pending', 1), (4, 'pending', 3);
        """)
    conn.close()
    return f"sqlite:///{path.as_posix()}"


def post_connect(client, name, url):
    return client.post(reverse("connect"), {"name": name, "url": url})


def test_connect_page_lists_saved_connections(client, shop_url):
    services.connect_database("Shop", shop_url)
    response = client.get(reverse("connect"))
    assert response.status_code == 200
    assert [c["name"] for c in response.context["connections"]] == ["Shop"]
    assert response.context["connections"][0]["table_count"] == 2
    assert response.context["check"] is None


def test_connecting_sqlite_saves_an_encrypted_connection_and_snapshot(client, shop_url):
    response = post_connect(client, "Shop", shop_url)
    check = response.context["check"]
    assert check["ok"], check
    connection = DatabaseConnection.objects.get()
    assert connection.dialect == "sqlite"
    assert shop_url.encode() not in bytes(connection.url_encrypted)
    snapshot = connection.snapshots.latest()
    assert snapshot.table_count == 2
    assert snapshot.restricted_tables == ["user_sessions"]
    assert services.load_target(connection.id).url == shop_url


def test_unsupported_database_is_rejected(client):
    check = post_connect(client, "X", "mssql+pyodbc://sa:pw@host/db").context["check"]
    assert not check["ok"] and "Supported databases" in check["message"]
    assert not DatabaseConnection.objects.exists()


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
def test_connection_failure_never_echoes_the_password(client):
    app = make_url(os.environ["DATABASE_URL"])
    url = app.set(drivername="postgresql+psycopg", username="nobody", password="hunter2")
    response = post_connect(client, "Bad", url.render_as_string(hide_password=False))
    check = response.context["check"]
    assert "nobody" in check["error"]
    assert not check["ok"] and check["message"] == "Could not connect to the database."
    assert "hunter2" not in response.content.decode()
    assert "hunter2" not in response.context["form"].data["url"]
    assert not DatabaseConnection.objects.exists()


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
def test_writable_postgres_account_is_refused(client):
    check = post_connect(client, "App DB", os.environ["DATABASE_URL"]).context["check"]
    assert not check["ok"] and "refused" in check["message"]
    assert "public.django_migrations" in check["writable_tables"]
    assert "GRANT SELECT" in check["grant_sql"]
    assert not DatabaseConnection.objects.exists()


@pytest.mark.skipif(not os.environ.get("SAFEQUERY_TEST_RO_URL"),
                    reason="set SAFEQUERY_TEST_RO_URL to the agent_ro connection string")
def test_chinook_read_only_account_connects(client):
    check = post_connect(client, "Chinook (Postgres)", os.environ["SAFEQUERY_TEST_RO_URL"]).context["check"]
    assert check["ok"], check
    assert DatabaseConnection.objects.get().readonly_verified


def test_schema_page_shows_the_snapshot(client, shop_url):
    _, connection = services.connect_database("Shop", shop_url)
    ctx = client.get(reverse("schema", args=[connection.id])).context
    tables = {t["name"]: t for t in ctx["tables"]}
    assert tables["user_sessions"]["restricted"]
    status = next(c for c in tables["orders"]["columns"] if c["name"] == "status")
    assert status["sample_values"] == ["pending", "shipped"]
    assert ctx["connection"]["name"] == "Shop"


def test_schema_page_saves_restricted_choices_and_drops_their_samples(client, shop_url):
    _, connection = services.connect_database("Shop", shop_url)
    response = client.post(reverse("schema", args=[connection.id]), {
        "action": "save", "restricted_tables": ["no_such_table"],
        "restricted_columns": ["orders.status", "orders.nope"],
    })
    assert response.status_code == 302
    snapshot, schema = services.latest_schema(connection)
    assert snapshot.restricted_tables == []
    assert snapshot.restricted_columns == ["orders.status"]
    assert next(c for c in schema.tables["orders"].columns if c.name == "status").sample_values == ()


def test_refresh_keeps_choices_and_adds_a_snapshot(client, shop_url):
    _, connection = services.connect_database("Shop", shop_url)
    services.save_restricted(connection, [], ["orders.customer_id"])
    client.post(reverse("schema", args=[connection.id]), {"action": "refresh"})
    assert SchemaSnapshot.objects.filter(connection=connection).count() == 2
    snapshot, _ = services.latest_schema(connection)
    assert snapshot.restricted_tables == []
    assert snapshot.restricted_columns == ["orders.customer_id"]


def test_unknown_connection_is_404(client):
    assert client.get(reverse("schema", args=[999])).status_code == 404
