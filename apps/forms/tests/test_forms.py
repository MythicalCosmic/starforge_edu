"""F3-3 — forms / surveys engine: build → publish → submit → summarize, with
type/required validation, anonymity, one-per-respondent dedupe, lifecycle guards,
and permission scoping (builders vs responders)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db

FORMS = "/api/v1/forms/"


def _rows(body):
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _build_published_form(client, **form_kwargs):
    """A 3-field form: required single-choice, required rating, optional textarea."""
    fid = client.post(FORMS, {"title": "Feedback", **form_kwargs}, format="json").json()["id"]
    f1 = client.post(
        f"{FORMS}{fid}/fields/",
        {"label": "Liked?", "field_type": "single_choice", "required": True, "options": ["yes", "no"]},
        format="json",
    ).json()["id"]
    f2 = client.post(
        f"{FORMS}{fid}/fields/",
        {"label": "Rating", "field_type": "rating", "required": True},
        format="json",
    ).json()["id"]
    f3 = client.post(
        f"{FORMS}{fid}/fields/", {"label": "Comments", "field_type": "textarea"}, format="json"
    ).json()["id"]
    pub = client.post(f"{FORMS}{fid}/publish/", {}, format="json")
    assert pub.status_code == 200, pub.content
    return fid, (f1, f2, f3)


def test_build_publish_submit_and_summary(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    fid, (f1, f2, f3) = _build_published_form(director)

    resp = student.post(
        f"{FORMS}{fid}/submit/",
        {
            "answers": [
                {"field": f1, "value": "yes"},
                {"field": f2, "value": 5},
                {"field": f3, "value": "great class"},
            ]
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content

    rows = _rows(director.get(f"{FORMS}{fid}/responses/").json())
    assert len(rows) == 1
    assert {a["field"]: a["value"] for a in rows[0]["answers"]}[f1] == "yes"

    summary = director.get(f"{FORMS}{fid}/summary/").json()
    assert summary["response_count"] == 1
    by_field = {x["field"]: x for x in summary["fields"]}
    assert by_field[f1]["summary"]["counts"] == {"yes": 1, "no": 0}
    assert by_field[f2]["summary"]["avg"] == 5


def test_required_and_type_validation(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    fid, (f1, f2, _f3) = _build_published_form(director)

    def submit(answers):
        return student.post(f"{FORMS}{fid}/submit/", {"answers": answers}, format="json")

    missing = submit([{"field": f2, "value": 3}])  # required f1 omitted
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "field_required"

    bad_choice = submit([{"field": f1, "value": "maybe"}, {"field": f2, "value": 3}])
    assert bad_choice.status_code == 400
    assert bad_choice.json()["error"]["code"] == "field_choice_invalid"

    bad_rating = submit([{"field": f1, "value": "yes"}, {"field": f2, "value": 9}])
    assert bad_rating.status_code == 400
    assert bad_rating.json()["error"]["code"] == "field_rating_range"

    # text where a rating is expected
    bad_type = submit([{"field": f1, "value": "yes"}, {"field": f2, "value": "five"}])
    assert bad_type.status_code == 400
    assert bad_type.json()["error"]["code"] == "field_rating_range"


def test_anonymous_form_does_not_record_respondent(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    fid, (f1, f2, _f3) = _build_published_form(director, is_anonymous=True)
    student.post(
        f"{FORMS}{fid}/submit/",
        {"answers": [{"field": f1, "value": "no"}, {"field": f2, "value": 2}]},
        format="json",
    )
    rows = _rows(director.get(f"{FORMS}{fid}/responses/").json())
    assert rows[0]["respondent"] is None


def test_one_response_per_respondent_then_allow_multiple(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    fid, (f1, f2, _f3) = _build_published_form(director)
    answer = {"answers": [{"field": f1, "value": "yes"}, {"field": f2, "value": 4}]}
    assert student.post(f"{FORMS}{fid}/submit/", answer, format="json").status_code == 201
    dup = student.post(f"{FORMS}{fid}/submit/", answer, format="json")
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "already_responded"

    # a form that allows multiple accepts repeat submissions
    fid2, (g1, g2, _g3) = _build_published_form(director, allow_multiple=True)
    a2 = {"answers": [{"field": g1, "value": "no"}, {"field": g2, "value": 1}]}
    assert student.post(f"{FORMS}{fid2}/submit/", a2, format="json").status_code == 201
    assert student.post(f"{FORMS}{fid2}/submit/", a2, format="json").status_code == 201


def test_lifecycle_guards(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)

    # publish with no fields -> 422
    empty = director.post(FORMS, {"title": "empty"}, format="json").json()["id"]
    no_fields = director.post(f"{FORMS}{empty}/publish/", {}, format="json")
    assert no_fields.status_code == 422
    assert no_fields.json()["error"]["code"] == "form_has_no_fields"

    # submit to a draft -> 422 form_not_open
    director.post(f"{FORMS}{empty}/fields/", {"label": "q", "field_type": "text"}, format="json")
    draft_submit = director.post(f"{FORMS}{empty}/submit/", {"answers": []}, format="json")
    assert draft_submit.status_code == 422
    assert draft_submit.json()["error"]["code"] == "form_not_open"

    # add a field to a published form -> 422 form_not_draft
    fid, _f = _build_published_form(director)
    late = director.post(f"{FORMS}{fid}/fields/", {"label": "late", "field_type": "text"}, format="json")
    assert late.status_code == 422
    assert late.json()["error"]["code"] == "form_not_draft"

    # closing then submitting -> 422
    assert director.post(f"{FORMS}{fid}/close/", {}, format="json").status_code == 200
    closed = director.post(
        f"{FORMS}{fid}/submit/", {"answers": [{"field": _f[0], "value": "yes"}]}, format="json"
    )
    assert closed.status_code == 422


def test_responder_cannot_build_or_see_responses(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    # a student (forms:read) cannot create a form
    assert student.post(FORMS, {"title": "x"}, format="json").status_code == 403

    fid, _f = _build_published_form(director)
    # nor read responses / summary (forms:write)
    assert student.get(f"{FORMS}{fid}/responses/").status_code == 403
    assert student.get(f"{FORMS}{fid}/summary/").status_code == 403


def test_responder_lists_only_published_forms(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    director.post(FORMS, {"title": "hidden draft"}, format="json")  # stays draft
    _build_published_form(director)

    rows = _rows(student.get(FORMS).json())
    assert rows  # sees something
    assert {r["status"] for r in rows} == {"published"}  # never a draft


# --------------------------------------------------------------------------- #
# review hardening
# --------------------------------------------------------------------------- #
def _build_typed_form(client):
    fid = client.post(FORMS, {"title": "Typed"}, format="json").json()["id"]
    f = {}
    for spec in (
        {"label": "agree", "field_type": "boolean", "required": True},
        {"label": "age", "field_type": "number"},
        {"label": "when", "field_type": "date"},
        {"label": "langs", "field_type": "multi_choice", "options": ["en", "uz", "ru"]},
    ):
        f[spec["label"]] = client.post(f"{FORMS}{fid}/fields/", spec, format="json").json()["id"]
    client.post(f"{FORMS}{fid}/publish/", {}, format="json")
    return fid, f


def test_all_field_types_submit_and_summary(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    s1, _ = as_role(Role.STUDENT)
    s2, _ = as_role(Role.STUDENT)
    fid, f = _build_typed_form(director)

    r1 = s1.post(
        f"{FORMS}{fid}/submit/",
        {
            "answers": [
                {"field": f["agree"], "value": True},
                {"field": f["age"], "value": 20},
                {"field": f["when"], "value": "2026-06-01"},
                {"field": f["langs"], "value": ["en", "uz"]},
            ]
        },
        format="json",
    )
    assert r1.status_code == 201, r1.content
    # required boolean answered False must be accepted (not treated as "empty")
    r2 = s2.post(
        f"{FORMS}{fid}/submit/",
        {
            "answers": [
                {"field": f["agree"], "value": False},
                {"field": f["age"], "value": 30},
                {"field": f["langs"], "value": ["en"]},
            ]
        },
        format="json",
    )
    assert r2.status_code == 201, r2.content

    by = {x["field"]: x["summary"] for x in director.get(f"{FORMS}{fid}/summary/").json()["fields"]}
    assert by[f["agree"]]["true"] == 1
    assert by[f["agree"]]["false"] == 1
    assert (by[f["age"]]["avg"], by[f["age"]]["min"], by[f["age"]]["max"]) == (25, 20, 30)
    assert by[f["langs"]]["counts"] == {"en": 2, "uz": 1, "ru": 0}


def test_multi_choice_duplicate_selection_rejected(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    fid = director.post(FORMS, {"title": "m"}, format="json").json()["id"]
    mc = director.post(
        f"{FORMS}{fid}/fields/",
        {"label": "langs", "field_type": "multi_choice", "options": ["en", "uz"]},
        format="json",
    ).json()["id"]
    director.post(f"{FORMS}{fid}/publish/", {}, format="json")
    r = student.post(
        f"{FORMS}{fid}/submit/", {"answers": [{"field": mc, "value": ["en", "en"]}]}, format="json"
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "field_choice_duplicate"


def test_add_field_validates_options(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    fid = director.post(FORMS, {"title": "o"}, format="json").json()["id"]

    def add(options):
        return director.post(
            f"{FORMS}{fid}/fields/",
            {"label": "x", "field_type": "single_choice", "options": options},
            format="json",
        )

    assert add(["a", "a"]).json()["error"]["code"] == "duplicate_options"
    assert add(["a", "  "]).json()["error"]["code"] == "invalid_options"
    assert add([]).json()["error"]["code"] == "choice_needs_options"


def test_duplicate_and_unknown_field_ids_rejected(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    fid, (f1, f2, _f3) = _build_published_form(director)

    dup = student.post(
        f"{FORMS}{fid}/submit/",
        {"answers": [{"field": f1, "value": "yes"}, {"field": f1, "value": "no"}, {"field": f2, "value": 3}]},
        format="json",
    )
    assert dup.status_code == 400
    assert dup.json()["error"]["code"] == "duplicate_field"

    unknown = student.post(
        f"{FORMS}{fid}/submit/",
        {
            "answers": [
                {"field": f1, "value": "yes"},
                {"field": f2, "value": 3},
                {"field": 999999, "value": "x"},
            ]
        },
        format="json",
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "unknown_field"


def test_submission_window_enforced(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    now = timezone.now()

    def published_with(window):
        fid = director.post(FORMS, {"title": "w", **window}, format="json").json()["id"]
        director.post(f"{FORMS}{fid}/fields/", {"label": "q", "field_type": "text"}, format="json")
        director.post(f"{FORMS}{fid}/publish/", {}, format="json")
        return fid

    early = student.post(
        f"{FORMS}{published_with({'opens_at': (now + timedelta(days=1)).isoformat()})}/submit/",
        {"answers": []},
        format="json",
    )
    assert early.status_code == 422
    assert early.json()["error"]["code"] == "form_not_open"

    late = student.post(
        f"{FORMS}{published_with({'closes_at': (now - timedelta(days=1)).isoformat()})}/submit/",
        {"answers": []},
        format="json",
    )
    assert late.status_code == 422
    assert late.json()["error"]["code"] == "form_closed"


def test_non_builder_cannot_manage_a_form(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student, _ = as_role(Role.STUDENT)
    fid, _f = _build_published_form(director)
    # forms:write actions are closed to a forms:read-only responder
    assert (
        student.post(f"{FORMS}{fid}/fields/", {"label": "x", "field_type": "text"}, format="json").status_code
        == 403
    )
    assert student.post(f"{FORMS}{fid}/publish/", {}, format="json").status_code == 403
    assert student.post(f"{FORMS}{fid}/close/", {}, format="json").status_code == 403


def test_cross_branch_builder_isolation(tenant_a, user_in, as_user):
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant_a.schema_name):
        branch_a = BranchFactory.create()
        branch_b = BranchFactory.create()
    teacher_a = as_user(tenant_a, user_in(tenant_a, roles=[Role.TEACHER], branch=branch_a))
    teacher_b = as_user(tenant_a, user_in(tenant_a, roles=[Role.TEACHER], branch=branch_b))

    fid, _f = _build_published_form(teacher_b, branch=branch_b.id)
    # the other branch's builder cannot read this form's responses or summary
    assert teacher_a.get(f"{FORMS}{fid}/responses/").status_code == 404
    assert teacher_a.get(f"{FORMS}{fid}/summary/").status_code == 404
    # nor create a form pinned to a branch that isn't theirs
    cross = teacher_a.post(FORMS, {"title": "x", "branch": branch_b.id}, format="json")
    assert cross.status_code == 403
    assert cross.json()["error"]["code"] == "cross_branch"


def test_draft_form_can_be_deleted(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    fid = director.post(FORMS, {"title": "Draft"}, format="json").json()["id"]
    assert director.delete(f"{FORMS}{fid}/").status_code == 204
    assert director.get(f"{FORMS}{fid}/").status_code == 404


def test_published_and_closed_forms_cannot_be_deleted(tenant_a, as_role):
    """A published/closed form holds collected responses — a builder must not be
    able to hard-delete it (would CASCADE the responses away with no audit)."""
    director, _ = as_role(Role.DIRECTOR)
    fid, _fields = _build_published_form(director)
    published_delete = director.delete(f"{FORMS}{fid}/")
    assert published_delete.status_code == 422
    assert published_delete.json()["error"]["code"] == "form_not_draft"
    # closing it doesn't make it deletable either
    director.post(f"{FORMS}{fid}/close/", {}, format="json")
    assert director.delete(f"{FORMS}{fid}/").status_code == 422
