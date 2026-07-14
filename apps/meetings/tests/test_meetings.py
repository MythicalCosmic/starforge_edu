"""F3-5 — staff meetings: a manager schedules + invites staff; invitees RSVP; the
meeting is branch-scoped and surfaces on the invitee's upcoming list."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db

MEET = "/api/v1/meetings/"


def _setup(tenant, user_in, as_user):
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant.schema_name):
        branch = BranchFactory.create()
    t1 = user_in(tenant, roles=[Role.TEACHER], branch=branch)
    t2 = user_in(tenant, roles=[Role.TEACHER], branch=branch)
    return {
        "branch": branch,
        "manager": as_user(tenant, user_in(tenant, roles=[Role.HEAD_OF_DEPT], branch=branch)),
        "t1": t1,
        "t1c": as_user(tenant, t1),
        "t2": t2,
        "t2c": as_user(tenant, t2),
    }


def _meeting_body(s, **over):
    start = timezone.now() + timedelta(days=1)
    body = {
        "title": "Weekly sync",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
        "branch": s["branch"].id,
        "attendees": [s["t1"].id],
    }
    body.update(over)
    return body


def test_schedule_invite_and_rsvp(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    created = s["manager"].post(MEET, _meeting_body(s), format="json")
    assert created.status_code == 201, created.content
    mid = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "scheduled"
    assert len(created.json()["data"]["attendees"]) == 1
    assert created.json()["data"]["attendees"][0]["response"] == "invited"

    # the invited teacher accepts
    resp = s["t1c"].post(f"{MEET}{mid}/respond/", {"response": "accepted"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["attendees"][0]["response"] == "accepted"


def test_manager_cancels(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    mid = s["manager"].post(MEET, _meeting_body(s), format="json").json()["data"]["id"]
    cancelled = s["manager"].post(f"{MEET}{mid}/cancel/", {}, format="json")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    # a cancelled meeting can't be cancelled again
    assert s["manager"].post(f"{MEET}{mid}/cancel/", {}, format="json").status_code == 422


def test_cannot_schedule_for_another_branch(tenant_a, user_in, as_user):
    from apps.org.tests.factories import BranchFactory

    s = _setup(tenant_a, user_in, as_user)
    with schema_context(tenant_a.schema_name):
        other = BranchFactory.create()
    cross = s["manager"].post(MEET, _meeting_body(s, branch=other.id), format="json")
    assert cross.status_code == 403
    assert cross.json()["code"] == "branch_out_of_scope"
    # a non-director must name a branch (no centre-wide)
    wide = s["manager"].post(MEET, _meeting_body(s, branch=None), format="json")
    assert wide.status_code == 403
    assert wide.json()["code"] == "branch_required"


def test_invitee_sees_meeting_others_dont(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    mid = s["manager"].post(MEET, _meeting_body(s), format="json").json()["data"]["id"]
    # the invited teacher sees it; the uninvited teacher does not
    assert s["t1c"].get(MEET).json()["pagination"]["total"] == 1
    assert s["t2c"].get(MEET).json()["pagination"]["total"] == 0
    # ...and it shows on the invitee's upcoming list
    upcoming = s["t1c"].get(f"{MEET}upcoming/").json()["data"]
    assert [m["id"] for m in upcoming] == [mid]


def test_non_invitee_cannot_rsvp(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    mid = s["manager"].post(MEET, _meeting_body(s), format="json").json()["data"]["id"]
    # t2 wasn't invited -> the meeting isn't in their scope -> 404
    assert s["t2c"].post(f"{MEET}{mid}/respond/", {"response": "accepted"}, format="json").status_code == 404


def test_teacher_cannot_schedule(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    # a teacher holds no meeting:write
    assert s["t1c"].post(MEET, _meeting_body(s), format="json").status_code == 403


def test_manager_invitee_can_rsvp_a_centre_wide_meeting(tenant_a, user_in, as_user, as_role):
    # a director schedules a centre-wide (no branch) meeting and invites an HOD manager
    s = _setup(tenant_a, user_in, as_user)
    director, _ = as_role(Role.DIRECTOR)
    hod_user = user_in(tenant_a, roles=[Role.HEAD_OF_DEPT], branch=s["branch"])
    start = timezone.now() + timedelta(days=1)
    mid = director.post(
        MEET,
        {
            "title": "All-staff",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            "attendees": [hod_user.id],
        },
        format="json",
    ).json()["data"]["id"]
    hod = as_user(tenant_a, hod_user)
    # the HOD is an invitee (a meeting:write holder) — they must be able to open AND RSVP
    # it even though it has no branch, not just see it in /upcoming/
    assert hod.get(f"{MEET}{mid}/").status_code == 200
    assert hod.post(f"{MEET}{mid}/respond/", {"response": "accepted"}, format="json").status_code == 200


def test_invitee_cannot_cancel(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    mid = s["manager"].post(MEET, _meeting_body(s), format="json").json()["data"]["id"]
    # t1 is an in-scope invitee (sees the meeting) but holds no meeting:write -> can't cancel
    assert s["t1c"].post(f"{MEET}{mid}/cancel/", {}, format="json").status_code == 403


def test_invalid_datetime_is_400_not_500(tenant_a, user_in, as_user):
    """A well-formed-but-invalid datetime (parse_datetime RAISES ValueError, not None)
    must be a clean 400, never a 500."""
    s = _setup(tenant_a, user_in, as_user)
    r = s["manager"].post(MEET, _meeting_body(s, starts_at="2026-02-30T10:00:00"), format="json")
    assert r.status_code == 400
    assert "starts_at" in r.json()["errors"]


def test_student_cannot_be_invited(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    student = user_in(tenant_a, roles=[Role.STUDENT], branch=s["branch"])
    # meetings are staff coordination — a student id is rejected by the attendee filter
    r = s["manager"].post(MEET, _meeting_body(s, attendees=[student.id]), format="json")
    assert r.status_code == 400


def test_next_meeting_for_surfaces_soonest(tenant_a, user_in, as_user):
    from apps.meetings.services import next_meeting_for, schedule_meeting

    s = _setup(tenant_a, user_in, as_user)
    now = timezone.now()
    with schema_context(tenant_a.schema_name):
        schedule_meeting(
            title="Later",
            starts_at=now + timedelta(days=5),
            ends_at=now + timedelta(days=5, hours=1),
            attendees=[s["t1"]],
            created_by=None,
            branch=s["branch"],
        )
        schedule_meeting(
            title="Sooner",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
            attendees=[s["t1"]],
            created_by=None,
            branch=s["branch"],
        )
        nxt = next_meeting_for(s["t1"])
    assert nxt is not None
    assert nxt.title == "Sooner"  # the dashboard surfaces the soonest upcoming meeting


def test_rsvp_validation_and_read_only_impersonation_are_enforced(tenant_a, user_in, as_user, client_for):
    from core.session_auth import create_session

    s = _setup(tenant_a, user_in, as_user)
    mid = s["manager"].post(MEET, _meeting_body(s), format="json").json()["data"]["id"]
    invalid = s["t1c"].post(f"{MEET}{mid}/respond/", {"response": "maybe"}, format="json")
    assert invalid.status_code == 400
    assert "response" in invalid.json()["errors"]

    with schema_context(tenant_a.schema_name):
        session = create_session(s["t1"], read_only=True)
    read_only = client_for(tenant_a)
    read_only.credentials(HTTP_AUTHORIZATION=f"Bearer {session.key}")
    denied = read_only.post(f"{MEET}{mid}/respond/", {"response": "accepted"}, format="json")
    assert denied.status_code == 403
    assert denied.json()["code"] == "read_only_token"


def test_invited_manager_cannot_cancel_another_branch_or_centre_wide_meeting(
    tenant_a, user_in, as_user, as_role
):
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant_a.schema_name):
        branch_a = BranchFactory()
        branch_b = BranchFactory()
    hod_user = user_in(tenant_a, roles=[Role.HEAD_OF_DEPT], branch=branch_a)
    hod = as_user(tenant_a, hod_user)
    director, _ = as_role(Role.DIRECTOR)
    start = timezone.now() + timedelta(days=1)
    base = {
        "title": "Cross-scope",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
        "attendees": [hod_user.pk],
    }
    cross_id = director.post(MEET, {**base, "branch": branch_b.pk}, format="json").json()["data"]["id"]
    wide_id = director.post(MEET, base, format="json").json()["data"]["id"]

    cross = hod.post(f"{MEET}{cross_id}/cancel/", {}, format="json")
    assert cross.status_code == 403
    assert cross.json()["code"] == "branch_out_of_scope"
    wide = hod.post(f"{MEET}{wide_id}/cancel/", {}, format="json")
    assert wide.status_code == 403
    assert wide.json()["code"] == "branch_required"
    # Their invitation remains valid for RSVP even though cancellation is scoped.
    assert hod.post(f"{MEET}{wide_id}/respond/", {"response": "accepted"}, format="json").status_code == 200


def test_attendee_validation_precedes_cross_branch_scope_error(tenant_a, user_in, as_user):
    from apps.org.tests.factories import BranchFactory

    s = _setup(tenant_a, user_in, as_user)
    with schema_context(tenant_a.schema_name):
        foreign_branch = BranchFactory()
    response = s["manager"].post(
        MEET,
        _meeting_body(s, branch=foreign_branch.pk, attendees=[999_999_999]),
        format="json",
    )
    assert response.status_code == 400
    assert "attendees" in response.json()["errors"]


def test_meeting_filters_ordering_pagination_detail_and_head(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    first = s["manager"].post(MEET, _meeting_body(s, title="First"), format="json").json()["data"]
    second = (
        s["manager"]
        .post(
            MEET,
            _meeting_body(
                s,
                title="Second",
                starts_at=(timezone.now() + timedelta(days=2)).isoformat(),
                ends_at=(timezone.now() + timedelta(days=2, hours=1)).isoformat(),
            ),
            format="json",
        )
        .json()["data"]
    )
    s["manager"].post(f"{MEET}{second['id']}/cancel/", {}, format="json")

    filtered = s["manager"].get(
        f"{MEET}?status=cancelled&branch={s['branch'].pk}&ordering=-starts_at&page=1&page_size=1"
    )
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.json()["data"]] == [second["id"]]
    assert s["manager"].get(f"{MEET}?status=garbage").status_code == 400
    assert s["manager"].get(f"{MEET}?branch=garbage").status_code == 400
    assert s["manager"].get(f"{MEET}?branch=999999999").status_code == 400
    assert s["manager"].get(f"{MEET}?ordering=--starts_at").status_code == 200

    detail = s["manager"].get(f"{MEET}{first['id']}/")
    assert detail.status_code == 200
    assert detail.json()["data"]["title"] == "First"
    assert s["manager"].head(MEET).status_code == 200
    assert s["manager"].head(f"{MEET}{first['id']}/").status_code == 200
    assert s["t1c"].head(f"{MEET}upcoming/").status_code == 200


def test_meeting_text_fields_trim_and_blank_title_is_rejected(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    created = s["manager"].post(
        MEET,
        _meeting_body(s, title="  Weekly sync  ", agenda="  Agenda  ", location="  Room 1  "),
        format="json",
    )
    assert created.status_code == 201, created.content
    data = created.json()["data"]
    assert data["title"] == "Weekly sync"
    assert data["agenda"] == "Agenda"
    assert data["location"] == "Room 1"
    assert s["manager"].post(MEET, _meeting_body(s, title="   "), format="json").status_code == 400


def test_cancel_wins_before_late_rsvp(tenant_a, user_in, as_user):
    s = _setup(tenant_a, user_in, as_user)
    mid = s["manager"].post(MEET, _meeting_body(s), format="json").json()["data"]["id"]
    assert s["manager"].post(f"{MEET}{mid}/cancel/", {}, format="json").status_code == 200
    response = s["t1c"].post(f"{MEET}{mid}/respond/", {"response": "accepted"}, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "meeting_not_scheduled"
