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
