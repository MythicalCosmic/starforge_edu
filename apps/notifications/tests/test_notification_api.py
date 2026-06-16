"""Notification API endpoint matrix (DoD #10).

Feed is own-rows-only; unread-count / read / read-all operate on own rows;
preferences bulk upsert; templates CRUD (notifications:write); announcements
(notifications:write). Cross-tenant lives in test_cross_tenant_day3.py.
"""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from apps.notifications.models import (
    Channel,
    EventType,
    Notification,
)
from core.permissions import Role

pytestmark = pytest.mark.django_db

FEED_URL = "/api/v1/notifications/"
UNREAD_URL = "/api/v1/notifications/unread-count/"
READ_ALL_URL = "/api/v1/notifications/read-all/"
PREFS_URL = "/api/v1/notifications/preferences/"
TEMPLATES_URL = "/api/v1/notifications/templates/"
ANNOUNCE_URL = "/api/v1/notifications/announcements/"


def _make_notif(tenant, user, **kw):
    with schema_context(tenant.schema_name):
        return Notification.objects.create(
            user=user,
            event_type=kw.get("event_type", EventType.ATTENDANCE_ABSENT),
            title=kw.get("title", "t"),
            body=kw.get("body", "b"),
        )


# ---------------------------------------------------------------------------
# Feed — own rows only
# ---------------------------------------------------------------------------
def test_feed_returns_only_own_rows(tenant_a, user_in, as_user):
    mine = user_in(tenant_a, roles=[Role.PARENT])
    other = user_in(tenant_a, roles=[Role.PARENT])
    _make_notif(tenant_a, mine, title="mine")
    _make_notif(tenant_a, other, title="theirs")
    client = as_user(tenant_a, mine)
    resp = client.get(FEED_URL)
    assert resp.status_code == 200
    body = resp.json()
    titles = [r["title"] for r in body["results"]]
    assert titles == ["mine"]
    assert set(body) == {"results", "next", "previous"}  # cursor pagination shape


def test_feed_anonymous_denied(tenant_a, client_for):
    assert client_for(tenant_a).get(FEED_URL).status_code == 401


@pytest.mark.parametrize("role", [Role.DIRECTOR, Role.PARENT])
def test_feed_allowed_roles(tenant_a, as_role, role):
    client, _ = as_role(role, tenant_a)
    assert client.get(FEED_URL).status_code == 200


# ---------------------------------------------------------------------------
# unread-count / read / read-all
# ---------------------------------------------------------------------------
def test_unread_count_and_read_all(tenant_a, user_in, as_user):
    user = user_in(tenant_a, roles=[Role.PARENT])
    _make_notif(tenant_a, user)
    _make_notif(tenant_a, user)
    client = as_user(tenant_a, user)

    assert client.get(UNREAD_URL).json()["count"] == 2
    assert client.post(READ_ALL_URL).json()["updated"] == 2
    assert client.get(UNREAD_URL).json()["count"] == 0


def test_read_one_only_affects_own_unread(tenant_a, user_in, as_user):
    user = user_in(tenant_a, roles=[Role.PARENT])
    notif = _make_notif(tenant_a, user)
    client = as_user(tenant_a, user)
    resp = client.post(f"{FEED_URL}{notif.pk}/read/")
    assert resp.status_code == 200
    assert resp.json()["read"] is True
    with schema_context(tenant_a.schema_name):
        notif.refresh_from_db()
        assert notif.read_at is not None


def test_cannot_read_another_users_notification(tenant_a, user_in, as_user):
    mine = user_in(tenant_a, roles=[Role.PARENT])
    other = user_in(tenant_a, roles=[Role.PARENT])
    theirs = _make_notif(tenant_a, other)
    client = as_user(tenant_a, mine)
    # get_queryset scopes to own rows -> 404 on someone else's pk.
    resp = client.post(f"{FEED_URL}{theirs.pk}/read/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Preferences bulk upsert
# ---------------------------------------------------------------------------
def test_preferences_bulk_upsert_roundtrip(tenant_a, user_in, as_user):
    user = user_in(tenant_a, roles=[Role.PARENT])
    client = as_user(tenant_a, user)
    payload = {
        "preferences": [
            {"event_type": EventType.PAYMENTS_PAYMENT_COMPLETED, "channel": Channel.SMS, "enabled": False}
        ]
    }
    resp = client.put(PREFS_URL, payload, format="json")
    assert resp.status_code == 200
    assert resp.json()[0]["enabled"] is False
    # GET reflects it
    got = client.get(PREFS_URL).json()
    assert any(r["channel"] == "sms" and r["enabled"] is False for r in got)


# ---------------------------------------------------------------------------
# Templates CRUD — notifications:write (director ok; parent denied)
# ---------------------------------------------------------------------------
def test_template_create_director_ok(tenant_a, as_role):
    client, _ = as_role(Role.DIRECTOR, tenant_a)
    resp = client.post(
        TEMPLATES_URL,
        {
            "event_type": EventType.ATTENDANCE_LATE,
            "channel": Channel.IN_APP,
            "locale": "en",
            "subject": "Late",
            "body": "Late: $lesson_id",
        },
        format="json",
    )
    assert resp.status_code == 201


def test_template_create_parent_denied(tenant_a, as_role):
    client, _ = as_role(Role.PARENT, tenant_a)
    resp = client.post(
        TEMPLATES_URL,
        {"event_type": EventType.ATTENDANCE_LATE, "channel": Channel.IN_APP, "locale": "en", "body": "x"},
        format="json",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_template_list_director_ok(tenant_a, as_role):
    client, _ = as_role(Role.DIRECTOR, tenant_a)
    assert client.get(TEMPLATES_URL).status_code == 200


# ---------------------------------------------------------------------------
# Announcements — notifications:write
# ---------------------------------------------------------------------------
def test_announce_cohort_director_ok(tenant_a, as_role):
    from apps.cohorts.tests.factories import CohortFactory, CohortMembershipFactory

    client, _ = as_role(Role.DIRECTOR, tenant_a)
    with schema_context(tenant_a.schema_name):
        cohort = CohortFactory()
        CohortMembershipFactory(cohort=cohort)
        CohortMembershipFactory(cohort=cohort)
    resp = client.post(
        ANNOUNCE_URL,
        {"cohort": cohort.pk, "title": "Picnic", "body": "Friday picnic"},
        format="json",
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["recipients"] == 2
    with schema_context(tenant_a.schema_name):
        # one Notification per member, deduped per (announcement, user)
        assert Notification.objects.filter(event_type=EventType.COHORTS_ANNOUNCEMENT).count() == 2


def test_announce_cohort_parent_denied(tenant_a, as_role):
    client, _ = as_role(Role.PARENT, tenant_a)
    resp = client.post(ANNOUNCE_URL, {"cohort": 1, "title": "x", "body": "y"}, format="json")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Query budget (own-rows feed must not scale with rows)
# ---------------------------------------------------------------------------
def test_feed_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    user = user_in(tenant_a, roles=[Role.PARENT])
    with schema_context(tenant_a.schema_name):
        Notification.objects.bulk_create(
            [
                Notification(user=user, event_type=EventType.ATTENDANCE_ABSENT, title=f"n{i}")
                for i in range(40)
            ]
        )
    client = as_user(tenant_a, user)
    with django_assert_max_num_queries(8):
        client.get(FEED_URL)
