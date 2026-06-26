"""F15-2 — custom achievements: global (manager) / group (teacher) creation, the
teacher→manager global-approval flow, granting (with guards), the student/parent
wall, branch scope, and grants privacy."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db

ACH = "/api/v1/achievements/"


def _rows(body):
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _teacher_in_branch(tenant, user_in, as_user, branch):
    return as_user(tenant, user_in(tenant, roles=[Role.TEACHER], branch=branch))


def test_global_create_grant_and_student_wall(tenant_a, user_in, as_user, as_role):
    from apps.students.tests.factories import StudentProfileFactory

    director, _ = as_role(Role.DIRECTOR)
    student_user = user_in(tenant_a, roles=[Role.STUDENT])
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory.create(user=student_user)

    created = director.post(ACH, {"name": "Star Student", "scope": "global", "emoji": "⭐"}, format="json")
    assert created.status_code == 201, created.content
    assert created.json()["status"] == "active"  # a manager's global is live immediately
    aid = created.json()["id"]

    grant = director.post(f"{ACH}{aid}/grant/", {"student": student.id, "note": "Great term"}, format="json")
    assert grant.status_code == 201, grant.content

    student_client = as_user(tenant_a, student_user)
    rows = _rows(student_client.get(f"{ACH}mine/").json())
    assert len(rows) == 1
    assert rows[0]["achievement_detail"]["name"] == "Star Student"
    assert rows[0]["note"] == "Great term"


def test_teacher_group_active_and_global_request_approval(tenant_a, user_in, as_user, as_role):
    from apps.cohorts.tests.factories import CohortFactory
    from apps.org.tests.factories import BranchFactory

    director, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory.create()
        cohort = CohortFactory.create(branch=branch)
    teacher = _teacher_in_branch(tenant_a, user_in, as_user, branch)

    group = teacher.post(ACH, {"name": "Best Homework", "scope": "group", "cohort": cohort.id}, format="json")
    assert group.status_code == 201, group.content
    assert group.json()["status"] == "active"

    glob = teacher.post(ACH, {"name": "Center Champion", "scope": "global"}, format="json")
    assert glob.status_code == 201
    assert glob.json()["status"] == "pending"  # a teacher's global awaits a manager
    gid = glob.json()["id"]

    assert teacher.post(f"{ACH}{gid}/approve/", {}, format="json").status_code == 403  # can't self-approve
    approved = director.post(f"{ACH}{gid}/approve/", {}, format="json")
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"


def test_group_achievement_requires_a_cohort(tenant_a, as_role):
    teacher_client, _t = as_role(Role.TEACHER)
    r = teacher_client.post(ACH, {"name": "x", "scope": "group"}, format="json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "cohort_required"


def test_cross_branch_group_create_blocked(tenant_a, user_in, as_user):
    from apps.cohorts.tests.factories import CohortFactory
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant_a.schema_name):
        branch_a = BranchFactory.create()
        branch_b = BranchFactory.create()
        cohort_b = CohortFactory.create(branch=branch_b)
    teacher_a = _teacher_in_branch(tenant_a, user_in, as_user, branch_a)
    # a teacher can't pin a group achievement to another branch's cohort
    r = teacher_a.post(ACH, {"name": "x", "scope": "group", "cohort": cohort_b.id}, format="json")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cross_branch"


def test_grant_guards(tenant_a, user_in, as_user, as_role):
    from apps.cohorts.tests.factories import CohortFactory
    from apps.org.tests.factories import BranchFactory
    from apps.students.tests.factories import StudentProfileFactory

    director, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory.create()
        cohort = CohortFactory.create(branch=branch)
        member = StudentProfileFactory.create(branch=branch, current_cohort=cohort)
        outsider = StudentProfileFactory.create(branch=branch)
    teacher = _teacher_in_branch(tenant_a, user_in, as_user, branch)

    # a pending achievement cannot be granted
    pending_id = teacher.post(ACH, {"name": "P", "scope": "global"}, format="json").json()["id"]
    not_active = director.post(f"{ACH}{pending_id}/grant/", {"student": member.id}, format="json")
    assert not_active.status_code == 422
    assert not_active.json()["error"]["code"] == "achievement_not_active"

    grp_id = teacher.post(ACH, {"name": "G", "scope": "group", "cohort": cohort.id}, format="json").json()[
        "id"
    ]
    # a group achievement can't be granted to a non-member
    wrong = director.post(f"{ACH}{grp_id}/grant/", {"student": outsider.id}, format="json")
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "student_not_in_group"
    # to a member -> ok; a second time -> 409
    assert director.post(f"{ACH}{grp_id}/grant/", {"student": member.id}, format="json").status_code == 201
    dup = director.post(f"{ACH}{grp_id}/grant/", {"student": member.id}, format="json")
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "already_granted"


def test_reject_flow_then_not_grantable(tenant_a, user_in, as_user, as_role):
    from apps.students.tests.factories import StudentProfileFactory

    director, _ = as_role(Role.DIRECTOR)
    teacher_client, _t = as_role(Role.TEACHER)
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory.create()

    gid = teacher_client.post(ACH, {"name": "Maybe", "scope": "global"}, format="json").json()["id"]
    rejected = director.post(f"{ACH}{gid}/reject/", {}, format="json")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    # re-deciding a non-pending achievement is rejected
    assert director.post(f"{ACH}{gid}/approve/", {}, format="json").status_code == 422
    # a rejected achievement cannot be granted
    g = director.post(f"{ACH}{gid}/grant/", {"student": student.id}, format="json")
    assert g.status_code == 422
    assert g.json()["error"]["code"] == "achievement_not_active"


def test_grants_action_is_staff_only(tenant_a, user_in, as_user, as_role):
    from apps.students.tests.factories import StudentProfileFactory

    director, _ = as_role(Role.DIRECTOR)
    student_user = user_in(tenant_a, roles=[Role.STUDENT])
    parent_user = user_in(tenant_a, roles=[Role.PARENT])
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory.create(user=student_user)
    aid = director.post(ACH, {"name": "Public Badge", "scope": "global"}, format="json").json()["id"]
    director.post(f"{ACH}{aid}/grant/", {"student": student.id}, format="json")

    # a student / parent must NOT enumerate who earned an achievement
    assert as_user(tenant_a, student_user).get(f"{ACH}{aid}/grants/").status_code == 403
    assert as_user(tenant_a, parent_user).get(f"{ACH}{aid}/grants/").status_code == 403
    # but staff may
    assert director.get(f"{ACH}{aid}/grants/").status_code == 200


def test_parent_sees_childs_wall(tenant_a, user_in, as_user, as_role):
    from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
    from apps.students.tests.factories import StudentProfileFactory

    director, _ = as_role(Role.DIRECTOR)
    parent_user = user_in(tenant_a, roles=[Role.PARENT])
    with schema_context(tenant_a.schema_name):
        child = StudentProfileFactory.create()
        GuardianFactory.create(parent=ParentProfileFactory.create(user=parent_user), student=child)
    aid = director.post(ACH, {"name": "Reader", "scope": "global"}, format="json").json()["id"]
    director.post(f"{ACH}{aid}/grant/", {"student": child.id}, format="json")

    rows = _rows(as_user(tenant_a, parent_user).get(f"{ACH}mine/").json())
    assert len(rows) == 1
    assert rows[0]["achievement_detail"]["name"] == "Reader"


def test_student_sees_only_active_and_cannot_create(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    teacher_client, _t = as_role(Role.TEACHER)
    student_client, _s = as_role(Role.STUDENT)

    director.post(ACH, {"name": "Active", "scope": "global"}, format="json")
    teacher_client.post(ACH, {"name": "Pending", "scope": "global"}, format="json")  # stays pending

    statuses = {r["status"] for r in _rows(student_client.get(ACH).json())}
    assert statuses == {"active"}  # no pending visible to a student
    assert student_client.post(ACH, {"name": "x", "scope": "global"}, format="json").status_code == 403


def test_role_without_achievements_is_denied(tenant_a, as_role):
    cashier_client, _ = as_role(Role.CASHIER)  # cashier holds no achievements permission
    assert cashier_client.get(ACH).status_code == 403
