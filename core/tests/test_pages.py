"""Every page renders its sample states; the Log page is superuser-only."""

import pytest
from django.urls import reverse

from core import sample_context


def test_root_redirects_to_connect(client):
    assert client.get("/").url == reverse("connect")


@pytest.mark.parametrize("state", ["default", "empty", "success", "refused", "error"])
def test_connect_states(client, state):
    assert client.get(reverse("connect"), {"state": state}).status_code == 200


def test_schema_sample_page(client):
    assert client.get(reverse("schema", args=[1]), {"state": "default"}).status_code == 200


@pytest.mark.parametrize("state", ["default", *sample_context.ASK_STATES])
def test_ask_states(client, state):
    assert client.get(reverse("ask", args=[1]), {"state": state}).status_code == 200


@pytest.mark.parametrize("name,args", [("log", []), ("log_detail", [1])])
def test_log_pages_send_anonymous_users_to_login(client, name, args):
    response = client.get(reverse(name, args=args))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_log_pages_refuse_staff_who_are_not_superusers(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("staff", password="x", is_staff=True))
    assert client.get(reverse("log")).status_code == 302


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["default", "empty"])
def test_log_pages_render_for_superusers(admin_client, state):
    assert admin_client.get(reverse("log"), {"state": state}).status_code == 200
    assert admin_client.get(reverse("log_detail", args=[1]), {"state": state}).status_code == 200


@pytest.mark.parametrize("addr", ["192.168.1.20", "10.0.0.5"])
def test_requests_from_other_machines_are_refused(client, addr):
    response = client.get(reverse("connect"), REMOTE_ADDR=addr, HTTP_HOST="localhost")
    assert response.status_code == 403


@pytest.mark.django_db
def test_ipv6_loopback_is_allowed(client):
    assert client.get(reverse("connect"), REMOTE_ADDR="::1").status_code == 200


@pytest.mark.parametrize("state,expected", [
    ("answered", ["CLEARED", "Iron Maiden", "ran on the read-only account"]),
    ("corrected", ["Corrected after 1 database error", "column ar.artist_name does not exist"]),
    ("blocked", ["REFUSED", "RULES R3 · R4", "This system can only read data, not change it."]),
    ("failed", ["FAILED", "column &quot;revenue&quot; does not exist"]),
    ("cannot_answer", ["NO ANSWER", "no weather data"]),
    ("unavailable", ["UNAVAILABLE", "No answer from Gemini", "per-minute free-tier limit"]),
])
def test_ask_states_show_their_verdict(client, state, expected):
    html = client.get(reverse("ask", args=[1]), {"state": state}).content.decode()
    for text in expected:
        assert text in html, text


@pytest.mark.parametrize("state,expected", [
    ("refused", ["REFUSED", "public.invoice · public.customer", "GRANT SELECT ON ALL TABLES"]),
    ("success", ["CLEARED", "The account is read-only."]),
    ("error", ["Could not connect to the database.", "Connection refused"]),
    ("empty", ["No connections yet.", "Don't connect a database whose column values are confidential."]),
])
def test_connect_states_show_their_check(client, state, expected):
    html = client.get(reverse("connect"), {"state": state}).content.decode()
    for text in expected:
        assert text in html, text


@pytest.mark.django_db
def test_log_link_only_for_superusers(client, admin_client):
    assert 'href="/log/"' not in client.get(reverse("connect")).content.decode()
    assert 'href="/log/"' in admin_client.get(reverse("connect")).content.decode()


def test_schema_sample_marks_withheld_names(client):
    html = client.get(reverse("schema", args=[1]), {"state": "default"}).content.decode()
    assert "WITHHELD" in html
    assert 'value="user_credentials.password_hash" checked' in html
    assert 'name="action" value="refresh"' in html
