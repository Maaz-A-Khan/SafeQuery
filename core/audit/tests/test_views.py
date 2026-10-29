import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_anonymous_is_redirected_to_login(client):
    r = client.get(reverse("log"))
    assert r.status_code == 302
    assert "login" in r.url


def test_normal_user_is_redirected(client):
    user = get_user_model().objects.create_user("bob", password="x")
    client.force_login(user)
    r = client.get(reverse("log"))
    assert r.status_code == 302


def test_superuser_can_open_log(client):
    admin = get_user_model().objects.create_superuser("root", password="x")
    client.force_login(admin)
    r = client.get(reverse("log"))
    assert r.status_code == 200