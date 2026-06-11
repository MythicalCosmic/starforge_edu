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


def test_teacher_can_read_but_not_patch_settings(as_role):
    """D1-LB-3 acceptance: teacher GET 200, PATCH 403."""
    client, _ = as_role(Role.TEACHER)
    assert client.get(URL).status_code == 200
    resp = client.patch(URL, {"late_threshold_minutes": 5}, format="json")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_settings_rejects_pattern_without_counter(as_role):
    client, _ = as_role(Role.DIRECTOR)
    resp = client.patch(URL, {"student_id_pattern": "STU-{YYYY}"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_id_pattern"


def test_settings_rejects_overlong_pattern(as_role):
    client, _ = as_role(Role.DIRECTOR)
    pattern = "X" * 30 + "-{NNNNN}"  # renders to 36 chars > the 32-char column
    resp = client.patch(URL, {"student_id_pattern": pattern}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_id_pattern"


@pytest.mark.parametrize(
    "payload",
    [
        {"allowed_file_types": "pdf"},  # string, not a list
        {"allowed_file_types": ["not a slug!"]},
        {"otp_channel_prefs": []},  # list, not a dict
        {"otp_channel_prefs": {"pigeon": True}},  # unknown channel
        {"otp_channel_prefs": {"sms": "maybe"}},  # non-boolean value
    ],
)
def test_settings_rejects_malformed_json_knobs(as_role, payload):
    client, _ = as_role(Role.DIRECTOR)
    resp = client.patch(URL, payload, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_settings_accepts_valid_json_knobs(as_role):
    client, _ = as_role(Role.DIRECTOR)
    resp = client.patch(
        URL,
        {"allowed_file_types": ["pdf", "docx"], "otp_channel_prefs": {"sms": True, "email": False}},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed_file_types"] == ["pdf", "docx"]
    assert body["otp_channel_prefs"] == {"sms": True, "email": False}
