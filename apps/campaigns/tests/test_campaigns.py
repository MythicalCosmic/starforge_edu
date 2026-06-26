"""F10-1 — SMS campaigns: build against a student segment (freezing recipients +
phones), send once via the Eskiz client, and record who was contacted / who landed."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db

CAMPAIGNS = "/api/v1/campaigns/"


def _student(branch, *, status=None, cohort=None, with_phone=True):
    """A student in `branch`; with_phone gives them a primary guardian whose user
    carries a phone (the SMS target). Call inside schema_context."""
    from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
    from apps.students.models import StudentProfile
    from apps.students.tests.factories import StudentProfileFactory

    student = StudentProfileFactory.create(
        branch=branch, status=status or StudentProfile.Status.ACTIVE, current_cohort=cohort
    )
    if with_phone:
        parent = ParentProfileFactory.create()  # parent.user gets a unique phone
        GuardianFactory.create(parent=parent, student=student, is_primary=True)
    else:
        student.user.phone = None
        student.user.save(update_fields=["phone"])
    return student


def _branch(tenant):
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant.schema_name):
        return BranchFactory.create()


def test_create_and_send_campaign_texts_recipients(tenant_a, user_in, as_user, sms_outbox):
    branch = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        for _ in range(3):
            _student(branch)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))

    created = client.post(
        CAMPAIGNS, {"name": "Reminder", "message": "Class resumes Monday", "branch": branch.id}, format="json"
    )
    assert created.status_code == 201, created.content
    cid = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert created.json()["total"] == 3

    sent = client.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json")
    assert sent.status_code == 200, sent.content
    assert sent.json()["status"] == "sent"
    assert sent.json()["sent_count"] == 3

    assert len(sms_outbox) == 3
    assert all(m["text"] == "Class resumes Monday" for m in sms_outbox)
    recipients = client.get(f"{CAMPAIGNS}{cid}/recipients/").json()
    assert {r["status"] for r in recipients} == {"sent"}


def test_send_is_idempotent(tenant_a, user_in, as_user, sms_outbox):
    branch = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        _student(branch)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    cid = client.post(CAMPAIGNS, {"name": "x", "message": "hi", "branch": branch.id}, format="json").json()[
        "id"
    ]

    assert client.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json").status_code == 200
    again = client.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json")
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "campaign_already_sent"
    assert len(sms_outbox) == 1  # not re-blasted


def test_recipient_without_phone_is_skipped(tenant_a, user_in, as_user, sms_outbox):
    branch = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        _student(branch, with_phone=True)
        _student(branch, with_phone=False)  # no guardian, no own phone
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    cid = client.post(CAMPAIGNS, {"name": "x", "message": "hi", "branch": branch.id}, format="json").json()[
        "id"
    ]

    sent = client.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json").json()
    assert sent["total"] == 2
    assert sent["sent_count"] == 1
    assert sent["skipped_count"] == 1
    assert len(sms_outbox) == 1  # the phoneless student is never texted


def test_segment_filters_the_audience(tenant_a, user_in, as_user):
    from apps.students.models import StudentProfile

    branch = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        _student(branch, status=StudentProfile.Status.ACTIVE)
        _student(branch, status=StudentProfile.Status.ACTIVE)
        _student(branch, status=StudentProfile.Status.WITHDRAWN)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))

    body = client.post(
        CAMPAIGNS,
        {"name": "Active only", "message": "hi", "branch": branch.id, "segment": {"status": "active"}},
        format="json",
    ).json()
    assert body["total"] == 2  # the withdrawn student is excluded


def test_campaign_branch_scope(tenant_a, user_in, as_user):
    home = _branch(tenant_a)
    other = _branch(tenant_a)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=home))

    # another branch -> 403
    cross = client.post(CAMPAIGNS, {"name": "x", "message": "hi", "branch": other.id}, format="json")
    assert cross.status_code == 403
    assert cross.json()["error"]["code"] == "branch_out_of_scope"
    # centre-wide (no branch) is director-only
    wide = client.post(CAMPAIGNS, {"name": "x", "message": "hi"}, format="json")
    assert wide.status_code == 403
    assert wide.json()["error"]["code"] == "branch_required"


class _RaisingClient:
    def send(self, *, phone, text):
        raise RuntimeError("gateway down")


def test_failed_send_is_recorded(tenant_a, user_in, as_user, monkeypatch):
    branch = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        _student(branch)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    cid = client.post(CAMPAIGNS, {"name": "x", "message": "hi", "branch": branch.id}, format="json").json()[
        "id"
    ]

    monkeypatch.setattr("apps.campaigns.services.get_sms_client", lambda: _RaisingClient())
    body = client.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json").json()
    assert body["status"] == "failed"
    assert body["sent_count"] == 0
    assert body["failed_count"] == 1
    recip = client.get(f"{CAMPAIGNS}{cid}/recipients/").json()[0]
    assert recip["status"] == "failed"
    assert recip["error"]  # the failure reason is captured for the audit trail


def test_send_resumes_a_stuck_sending_campaign(tenant_a, user_in, as_user, sms_outbox):
    branch = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        _student(branch)
        _student(branch)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    cid = client.post(CAMPAIGNS, {"name": "x", "message": "hi", "branch": branch.id}, format="json").json()[
        "id"
    ]

    # simulate a crash mid-send: campaign stuck SENDING, one recipient already delivered
    with schema_context(tenant_a.schema_name):
        from apps.campaigns.models import Campaign, CampaignRecipient

        campaign = Campaign.objects.get(pk=cid)
        campaign.status = Campaign.Status.SENDING
        campaign.save(update_fields=["status"])
        done = campaign.recipients.first()
        done.status = CampaignRecipient.Status.SENT
        done.save(update_fields=["status"])

    body = client.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json").json()
    assert body["status"] == "sent"
    assert body["sent_count"] == 2  # finalized from the rows
    assert len(sms_outbox) == 1  # only the still-pending recipient was actually texted


def test_siblings_sharing_a_guardian_are_texted_once(tenant_a, user_in, as_user, sms_outbox):
    from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
    from apps.students.tests.factories import StudentProfileFactory

    branch = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        parent = ParentProfileFactory.create()  # one guardian for both children
        for _ in range(2):
            student = StudentProfileFactory.create(branch=branch)
            GuardianFactory.create(parent=parent, student=student, is_primary=True)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    cid = client.post(CAMPAIGNS, {"name": "x", "message": "hi", "branch": branch.id}, format="json").json()[
        "id"
    ]

    body = client.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json").json()
    assert body["total"] == 2
    assert body["sent_count"] == 2  # both children are covered...
    assert len(sms_outbox) == 1  # ...by a single SMS to the shared phone


def test_segment_cohort_must_not_be_a_bool(tenant_a, user_in, as_user):
    branch = _branch(tenant_a)
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    r = client.post(
        CAMPAIGNS,
        {"name": "x", "message": "hi", "branch": branch.id, "segment": {"cohort": True}},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "segment_cohort_invalid"


def test_cannot_touch_another_branchs_campaign(tenant_a, user_in, as_user):
    home = _branch(tenant_a)
    other = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        _student(other)
    other_reg = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=other))
    cid = other_reg.post(CAMPAIGNS, {"name": "x", "message": "hi", "branch": other.id}, format="json").json()[
        "id"
    ]

    home_reg = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=home))
    assert home_reg.get(f"{CAMPAIGNS}{cid}/").status_code == 404
    assert home_reg.post(f"{CAMPAIGNS}{cid}/send/", {}, format="json").status_code == 404
    assert home_reg.get(f"{CAMPAIGNS}{cid}/recipients/").status_code == 404


def test_director_can_run_a_centre_wide_campaign(tenant_a, as_role):
    b1 = _branch(tenant_a)
    b2 = _branch(tenant_a)
    with schema_context(tenant_a.schema_name):
        _student(b1)
        _student(b2)
    director, _ = as_role(Role.DIRECTOR)
    body = director.post(CAMPAIGNS, {"name": "All families", "message": "hi"}, format="json").json()
    assert body["total"] == 2  # no branch -> spans every branch's students


def test_role_without_campaign_is_denied(tenant_a, as_role):
    teacher, _ = as_role(Role.TEACHER)  # teachers hold no campaign permission
    assert teacher.get(CAMPAIGNS).status_code == 403
