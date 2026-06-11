import pytest

from core.permissions import Role

pytestmark = pytest.mark.django_db

URL = "/api/v1/org/settings/"


def test_director_can_read_and_patch_settings(as_role):
    client, _ = as_role(Role.DIRECTOR)
    assert client.get(URL).status_code == 200
    resp = client.patch(URL, {"late_threshold_minutes": 20}, format="json")
    assert resp.status_code == 200
    assert resp.json()["late_threshold_minutes"] == 20


def test_teacher_cannot_patch_settings(as_role):
    client, _ = as_role(Role.TEACHER)
    resp = client.patch(URL, {"late_threshold_minutes": 5}, format="json")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
