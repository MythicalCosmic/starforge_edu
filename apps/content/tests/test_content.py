"""Content lane tests (D2-E): upload-flow validation, libmagic sniff + tmp→content
move, thumbnailing, download gating + F() counters, visibility matrix, version
chain, key prefix, seed bootstrap, cross-tenant, query budgets.

S3 is stubbed (test settings use local FS storage with no S3 OPTIONS); libmagic
is stubbed via `_sniff_mime`; Pillow runs for real."""

from __future__ import annotations

import io
from typing import Any

import pytest
from django_tenants.utils import schema_context

from apps.content import selectors, services
from apps.content.models import FileView, LessonFile
from apps.content.tests.factories import (
    ContentLibraryFactory,
    FolderFactory,
    LessonFileFactory,
)
from apps.org.models import CenterSettings
from apps.org.tests.factories import BranchFactory, DepartmentFactory
from core.exceptions import ConflictException, UnprocessableEntity

pytestmark = pytest.mark.django_db


def _png_bytes(size=(500, 400)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format="PNG")
    return buffer.getvalue()


def _stub_s3(monkeypatch):
    monkeypatch.setattr(services, "presign_upload", lambda key, **kw: f"https://put/{key}")
    monkeypatch.setattr(services, "presign_download", lambda key, **kw: f"https://get/{key}")


# --------------------------------------------------------------------------- #
# request_upload validation
# --------------------------------------------------------------------------- #


def test_upload_url_allowlist_size_quota_rejections(tenant_a, monkeypatch):
    _stub_s3(monkeypatch)
    with schema_context(tenant_a.schema_name):
        folder: Any = FolderFactory()

        with pytest.raises(UnprocessableEntity) as bad_type:
            services.request_upload(
                filename="x.exe", content_type="application/octet-stream", size_bytes=10, folder=folder
            )
        assert bad_type.value.code == "file_type_not_allowed"

        with pytest.raises(UnprocessableEntity) as too_big:
            services.request_upload(
                filename="x.pdf", content_type="application/pdf", size_bytes=10**12, folder=folder
            )
        assert too_big.value.code == "file_too_large"

        # Quota: 1 GB quota, an existing 1 GB clean file → any new upload exceeds.
        settings = CenterSettings.load()
        settings.storage_quota_gb = 1
        settings.save(update_fields=["storage_quota_gb"])
        from django.core.cache import cache

        cache.clear()
        LessonFileFactory(folder=folder, size_bytes=1024**3, status=LessonFile.Status.CLEAN)
        with pytest.raises(UnprocessableEntity) as quota:
            services.request_upload(
                filename="x.pdf", content_type="application/pdf", size_bytes=1000, folder=folder
            )
        assert quota.value.code == "storage_quota_exceeded"


def test_every_issued_key_starts_with_schema_name(tenant_a, monkeypatch):
    _stub_s3(monkeypatch)
    with schema_context(tenant_a.schema_name):
        folder: Any = FolderFactory()
        result = services.request_upload(
            filename="notes.pdf", content_type="application/pdf", size_bytes=2048, folder=folder
        )
        assert result["key"].startswith(f"{tenant_a.schema_name}/tmp/")
        assert result["file"].status == LessonFile.Status.PENDING


def test_confirm_non_pending_conflicts(tenant_a, monkeypatch):
    _stub_s3(monkeypatch)
    with schema_context(tenant_a.schema_name):
        file: Any = LessonFileFactory(status=LessonFile.Status.CLEAN)
        with pytest.raises(ConflictException) as exc:
            services.confirm_upload(file=file)
        assert exc.value.code == "file_not_pending"


# --------------------------------------------------------------------------- #
# validate task (libmagic stubbed)
# --------------------------------------------------------------------------- #


def _pending_file(folder, *, content_type="application/pdf", size=1000) -> Any:
    return LessonFile.objects.create(
        folder=folder,
        title="doc",
        s3_key=f"tenant_a/tmp/abc/doc.{content_type.split('/')[-1]}",
        content_type=content_type,
        size_bytes=size,
        status=LessonFile.Status.PENDING,
    )


def _stub_validate_s3(monkeypatch, *, sniff, copies, content_length=1000, deletes=None):
    def _copy(*, src_key, dest_key):
        copies.append(dest_key)
        return dest_key

    def _delete(key):
        if deletes is not None:
            deletes.append(key)

    monkeypatch.setattr(services, "head_object", lambda key: {"ContentLength": content_length})
    monkeypatch.setattr(services, "get_object_range", lambda key, **kw: b"binarymagic")
    monkeypatch.setattr(services, "_sniff_mime", lambda buf: sniff)
    monkeypatch.setattr(services, "copy_object", _copy)
    monkeypatch.setattr(services, "delete_object", _delete)


def test_magic_mismatch_rejected(tenant_a, monkeypatch):
    copies: list[str] = []
    _stub_validate_s3(monkeypatch, sniff="image/png", copies=copies)
    with schema_context(tenant_a.schema_name):
        file = _pending_file(FolderFactory(), content_type="application/pdf")
        result = services.validate_uploaded_file(file.id)
        assert result == LessonFile.Status.REJECTED
        file.refresh_from_db()
        assert file.status == LessonFile.Status.REJECTED
        assert "does not match" in file.reject_reason
        assert copies == []  # nothing moved


def test_valid_pdf_clean_and_moved(tenant_a, monkeypatch):
    copies: list[str] = []
    _stub_validate_s3(monkeypatch, sniff="application/pdf", copies=copies)
    with schema_context(tenant_a.schema_name):
        file = _pending_file(FolderFactory(), content_type="application/pdf")
        result = services.validate_uploaded_file(file.id)
        assert result == LessonFile.Status.CLEAN
        file.refresh_from_db()
        assert file.status == LessonFile.Status.CLEAN
        assert file.s3_key == f"{tenant_a.schema_name}/content/{file.id}/doc.pdf"
        assert copies == [file.s3_key]


def test_validate_task_idempotent(tenant_a, monkeypatch):
    copies: list[str] = []
    _stub_validate_s3(monkeypatch, sniff="application/pdf", copies=copies)
    with schema_context(tenant_a.schema_name):
        file = _pending_file(FolderFactory(), content_type="application/pdf")
        services.validate_uploaded_file(file.id)
        services.validate_uploaded_file(file.id)  # already clean → short-circuit
        assert len(copies) == 1


def test_reject_deletes_tmp_object(tenant_a, monkeypatch):
    """Reject path mirrors the happy path: the orphaned tmp blob is deleted so
    rejected uploads do not linger in the shared bucket (D2-E-8)."""
    copies: list[str] = []
    deletes: list[str] = []
    _stub_validate_s3(monkeypatch, sniff="image/png", copies=copies, deletes=deletes)
    with schema_context(tenant_a.schema_name):
        file = _pending_file(FolderFactory(), content_type="application/pdf")
        tmp_key = file.s3_key
        result = services.validate_uploaded_file(file.id)
        assert result == LessonFile.Status.REJECTED
        assert copies == []  # nothing moved
        assert deletes == [tmp_key]  # tmp object swept


def test_sniff_must_match_exact_mime_not_just_family(tenant_a, monkeypatch):
    """A PNG declared as image/jpeg (same family) is rejected: the sniff is
    compared against the exact MIME set for the .jpg extension, not just the
    top-level family (D2-E-4)."""
    copies: list[str] = []
    _stub_validate_s3(monkeypatch, sniff="image/png", copies=copies)
    with schema_context(tenant_a.schema_name):
        folder: Any = FolderFactory()
        # filename ext is .jpeg (sniff/content_type say jpeg) but bytes sniff png.
        file = LessonFile.objects.create(
            folder=folder,
            title="img",
            s3_key="tenant_a/tmp/abc/photo.jpeg",
            content_type="image/jpeg",
            size_bytes=1000,
            status=LessonFile.Status.PENDING,
        )
        result = services.validate_uploaded_file(file.id)
        assert result == LessonFile.Status.REJECTED
        file.refresh_from_db()
        assert "does not match" in file.reject_reason
        assert copies == []  # nothing moved


def test_sniff_exact_match_passes(tenant_a, monkeypatch):
    """The matching exact MIME (png bytes for a .png declared image/png) cleans."""
    copies: list[str] = []
    _stub_validate_s3(monkeypatch, sniff="image/png", copies=copies)
    with schema_context(tenant_a.schema_name):
        folder: Any = FolderFactory()
        file = LessonFile.objects.create(
            folder=folder,
            title="img",
            s3_key="tenant_a/tmp/abc/photo.png",
            content_type="image/png",
            size_bytes=1000,
            status=LessonFile.Status.PENDING,
        )
        result = services.validate_uploaded_file(file.id)
        assert result == LessonFile.Status.CLEAN


# --------------------------------------------------------------------------- #
# thumbnail (Pillow real, S3 stubbed)
# --------------------------------------------------------------------------- #


def test_thumbnail_idempotent(tenant_a, monkeypatch):
    uploads: list[tuple[str, bytes]] = []

    def _capture(key, data, **kw):
        uploads.append((key, data))
        return key

    monkeypatch.setattr(services, "download_bytes", lambda key: _png_bytes())
    monkeypatch.setattr(services, "upload_bytes", _capture)
    with schema_context(tenant_a.schema_name):
        file: Any = LessonFileFactory(
            content_type="image/png", status=LessonFile.Status.CLEAN, s3_key="tenant_a/content/9/i.png"
        )
        key = services.generate_thumbnail(file.id)
        file.refresh_from_db()
        assert key == f"{tenant_a.schema_name}/content/{file.id}/thumb.jpg"
        assert file.thumbnail_key == key
        assert uploads[0][1].startswith(b"\xff\xd8")  # JPEG magic
        services.generate_thumbnail(file.id)  # already has thumb → short-circuit
        assert len(uploads) == 1


# --------------------------------------------------------------------------- #
# download gating + counters
# --------------------------------------------------------------------------- #


def test_only_clean_downloadable(tenant_a, monkeypatch):
    _stub_s3(monkeypatch)
    with schema_context(tenant_a.schema_name):
        pending: Any = LessonFileFactory(status=LessonFile.Status.PENDING)
        with pytest.raises(ConflictException) as exc:
            services.download_url(file=pending, user=None)
        assert exc.value.code == "file_not_clean"


def test_counters_f_expression(tenant_a, user_in, monkeypatch):
    _stub_s3(monkeypatch)
    user = user_in(tenant_a)
    with schema_context(tenant_a.schema_name):
        file: Any = LessonFileFactory(status=LessonFile.Status.CLEAN)
        services.download_url(file=file, user=user)
        services.download_url(file=file, user=user)
        services.track_view(file=file, user=user)
        file.refresh_from_db()
        assert file.download_count == 2
        assert file.view_count == 1
        assert FileView.objects.filter(file=file, action="download").count() == 2
        assert FileView.objects.filter(file=file, action="view").count() == 1


# --------------------------------------------------------------------------- #
# visibility matrix
# --------------------------------------------------------------------------- #


def _file(lib) -> int:
    folder = FolderFactory(library=lib)
    created: Any = LessonFileFactory(folder=folder, status=LessonFile.Status.CLEAN)
    return created.id


def test_visibility_matrix_per_role(tenant_a, user_in):
    from apps.cohorts.tests.factories import CohortFactory, CohortMembershipFactory
    from apps.students.tests.factories import StudentProfileFactory

    student_user = user_in(tenant_a, roles=["student"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        dept = DepartmentFactory(branch=branch)
        cohort = CohortFactory(branch=branch)
        student = StudentProfileFactory(user=student_user, branch=branch)
        CohortMembershipFactory(cohort=cohort, student=student)

        tenant_file = _file(ContentLibraryFactory(visibility="tenant"))
        cohort_file = _file(ContentLibraryFactory(visibility="cohort", cohort=cohort))
        dept_file = _file(ContentLibraryFactory(visibility="department", department=dept))
        role_file = _file(ContentLibraryFactory(visibility="role", allowed_roles=["teacher"]))
        other_cohort_file = _file(
            ContentLibraryFactory(visibility="cohort", cohort=CohortFactory(branch=branch))
        )

        visible = set(
            selectors.scoped_files(user=student_user, roles={"student"}).values_list("id", flat=True)
        )
        assert tenant_file in visible
        assert cohort_file in visible
        assert dept_file not in visible  # student has no dept membership
        assert role_file not in visible  # student is not a teacher
        assert other_cohort_file not in visible


def test_visibility_positive_department_membership(tenant_a, user_in):
    """A user with a DEPARTMENT RoleMembership sees a department-visibility
    library (positive department_id__in branch), but not another department's."""
    from apps.users.models import RoleMembership

    user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch: Any = BranchFactory()
        my_dept: Any = DepartmentFactory(branch=branch)
        other_dept: Any = DepartmentFactory(branch=branch)
        RoleMembership.objects.create(user=user, branch=branch, department=my_dept, role="teacher")

        my_dept_file = _file(ContentLibraryFactory(visibility="department", department=my_dept))
        other_dept_file = _file(ContentLibraryFactory(visibility="department", department=other_dept))

        visible = set(selectors.scoped_files(user=user, roles={"teacher"}).values_list("id", flat=True))
        assert my_dept_file in visible
        assert other_dept_file not in visible


def test_visibility_positive_role_allowlist(tenant_a, user_in):
    """A user whose role is in allowed_roles sees a role-visibility library
    (positive allowed_roles__contains JSONField containment branch)."""
    student_user = user_in(tenant_a, roles=["student"])
    with schema_context(tenant_a.schema_name):
        allowed_file = _file(ContentLibraryFactory(visibility="role", allowed_roles=["student"]))
        not_allowed_file = _file(ContentLibraryFactory(visibility="role", allowed_roles=["teacher"]))

        visible = set(
            selectors.scoped_files(user=student_user, roles={"student"}).values_list("id", flat=True)
        )
        assert allowed_file in visible
        assert not_allowed_file not in visible


def test_visibility_parent_sees_childs_cohort_only(tenant_a, user_in):
    """Exercises the previously-dead parent branch of _related_cohort_ids: a
    Guardian-linked parent sees their child's cohort-visibility file and NOT an
    unrelated cohort's file (DAY-2.md D2-E-6 cohort visibility incl. parents)."""
    from apps.cohorts.tests.factories import CohortFactory, CohortMembershipFactory
    from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
    from apps.students.tests.factories import StudentProfileFactory

    parent_user = user_in(tenant_a, roles=["parent"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        student = StudentProfileFactory(branch=branch)
        CohortMembershipFactory(cohort=cohort, student=student)
        parent = ParentProfileFactory(user=parent_user)
        GuardianFactory(parent=parent, student=student)

        cohort_file = _file(ContentLibraryFactory(visibility="cohort", cohort=cohort))
        other_cohort_file = _file(
            ContentLibraryFactory(visibility="cohort", cohort=CohortFactory(branch=branch))
        )

        visible = set(selectors.scoped_files(user=parent_user, roles={"parent"}).values_list("id", flat=True))
        assert cohort_file in visible
        assert other_cohort_file not in visible


# --------------------------------------------------------------------------- #
# version chain + storage meter
# --------------------------------------------------------------------------- #


def test_version_chain(tenant_a, monkeypatch):
    _stub_s3(monkeypatch)
    with schema_context(tenant_a.schema_name):
        folder: Any = FolderFactory()
        v1 = services.request_upload(
            filename="a.pdf", content_type="application/pdf", size_bytes=10, folder=folder
        )["file"]
        v2 = services.create_new_version(
            previous=v1, filename="a.pdf", content_type="application/pdf", size_bytes=20
        )["file"]
        assert v2.version == 2
        assert v2.previous_version_id == v1.id
        assert v2.folder_id == v1.folder_id


def test_storage_used_bytes_sums_clean_only(tenant_a):
    with schema_context(tenant_a.schema_name):
        folder: Any = FolderFactory()
        LessonFileFactory(folder=folder, size_bytes=1000, status=LessonFile.Status.CLEAN)
        LessonFileFactory(folder=folder, size_bytes=2500, status=LessonFile.Status.CLEAN)
        LessonFileFactory(folder=folder, size_bytes=9999, status=LessonFile.Status.PENDING)  # excluded
        assert selectors.storage_used_bytes() == 3500


def test_quota_rechecked_at_validate_blocks_pending_batch_bypass(tenant_a, monkeypatch):
    """Two 0.6 GB pending uploads each pass the cheap request_upload gate (each
    sees only the unchanged CLEAN total — pending siblings do not count), but the
    SECOND is REJECTED when it validates: the quota is re-checked at the
    authoritative chokepoint, so storage_used_bytes() never exceeds the 1 GB
    quota (closes the sequential-batch bypass, D3-E meter)."""
    from django.core.cache import cache

    _stub_s3(monkeypatch)
    point_six_gb = 600 * 1024 * 1024  # 0.6 GB each; quota is 1 GB
    quota_bytes = 1024**3
    with schema_context(tenant_a.schema_name):
        settings = CenterSettings.load()
        settings.storage_quota_gb = 1
        # Per-file limit must clear 0.6 GB so the QUOTA (not max_upload_mb) governs.
        settings.max_upload_mb = 1000
        settings.save(update_fields=["storage_quota_gb", "max_upload_mb"])
        cache.clear()

        folder: Any = FolderFactory()

        # Both pending requests pass: each sees the same 0 CLEAN total; the
        # other still-pending sibling is excluded from storage_used_bytes().
        f1 = services.request_upload(
            filename="a.pdf", content_type="application/pdf", size_bytes=point_six_gb, folder=folder
        )["file"]
        f2 = services.request_upload(
            filename="b.pdf", content_type="application/pdf", size_bytes=point_six_gb, folder=folder
        )["file"]

        copies: list[str] = []
        _stub_validate_s3(monkeypatch, sniff="application/pdf", copies=copies, content_length=point_six_gb)

        # f1: 0 CLEAN + 0.6 GB ≤ 1 GB → clean.
        assert services.validate_uploaded_file(f1.id) == LessonFile.Status.CLEAN
        assert selectors.storage_used_bytes() == point_six_gb

        # f2: 0.6 GB CLEAN + 0.6 GB = 1.2 GB > 1 GB → rejected at validate.
        assert services.validate_uploaded_file(f2.id) == LessonFile.Status.REJECTED
        f2.refresh_from_db()
        assert "quota" in f2.reject_reason.lower()
        # CLEAN bytes never exceeded the quota.
        assert selectors.storage_used_bytes() <= quota_bytes


# --------------------------------------------------------------------------- #
# seed bootstrap
# --------------------------------------------------------------------------- #


def test_seed_bootstrap_idempotent():
    from unittest.mock import MagicMock

    from scripts.seed_dev import bootstrap_dev_storage

    client = MagicMock()
    client.list_buckets.return_value = {"Buckets": []}
    assert bootstrap_dev_storage(client=client, bucket="dev-bucket") is True
    client.create_bucket.assert_called_once_with(Bucket="dev-bucket")
    client.put_bucket_lifecycle_configuration.assert_called_once()
    client.put_bucket_cors.assert_called_once()

    client.list_buckets.return_value = {"Buckets": [{"Name": "dev-bucket"}]}
    client.create_bucket.reset_mock()
    assert bootstrap_dev_storage(client=client, bucket="dev-bucket") is True
    client.create_bucket.assert_not_called()  # already exists → no-op


# --------------------------------------------------------------------------- #
# API: gating, cross-tenant, query budgets
# --------------------------------------------------------------------------- #


def test_upload_url_requires_write(tenant_a, as_role):
    from core.permissions import Role

    client, _ = as_role(Role.STUDENT)  # content:read only
    resp = client.post("/api/v1/content/upload-url/", {}, format="json")
    assert resp.status_code == 403


def test_upload_url_rejects_out_of_scope_folder(tenant_a, as_role, monkeypatch):
    """A content:write holder cannot attach a file into a library they cannot
    see: the upload-url serializer scopes lesson/folder to scoped_libraries, so
    a folder in an out-of-scope cohort library is invalid (scoped writes)."""
    from apps.cohorts.tests.factories import CohortFactory
    from core.permissions import Role

    _stub_s3(monkeypatch)
    client, _ = as_role(Role.TEACHER)  # content:* but visibility-scoped reads
    with schema_context(tenant_a.schema_name):
        branch: Any = BranchFactory()
        other_cohort = CohortFactory(branch=branch)
        # A folder inside a cohort library the teacher is not a member of.
        hidden_folder: Any = FolderFactory(
            library=ContentLibraryFactory(visibility="cohort", cohort=other_cohort)
        )
        hidden_id = hidden_folder.id
        before = LessonFile.objects.count()

    resp = client.post(
        "/api/v1/content/upload-url/",
        {
            "filename": "x.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1000,
            "folder": hidden_id,
        },
        format="json",
    )
    assert resp.status_code in (400, 404, 422)
    with schema_context(tenant_a.schema_name):
        assert LessonFile.objects.count() == before  # nothing created


def test_upload_url_accepts_in_scope_folder(tenant_a, as_role, monkeypatch):
    """A content:write holder CAN attach into a tenant-visibility library they
    can see (positive path for the scoped lesson/folder queryset)."""
    from core.permissions import Role

    _stub_s3(monkeypatch)
    client, _ = as_role(Role.TEACHER)
    with schema_context(tenant_a.schema_name):
        visible_folder: Any = FolderFactory(library=ContentLibraryFactory(visibility="tenant"))
        visible_id = visible_folder.id

    resp = client.post(
        "/api/v1/content/upload-url/",
        {
            "filename": "x.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1000,
            "folder": visible_id,
        },
        format="json",
    )
    assert resp.status_code == 200
    assert "file_id" in resp.json()


def test_files_cross_tenant_isolated(tenant_a, tenant_b, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        LessonFileFactory(status=LessonFile.Status.CLEAN)

    director_b = user_in(tenant_b, roles=["director"])
    body = as_user(tenant_b, director_b).get("/api/v1/content/files/").json()
    assert body["count"] == 0


def test_files_list_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        folder = FolderFactory()
        for _ in range(5):
            LessonFileFactory(folder=folder, status=LessonFile.Status.CLEAN)

    client = as_user(tenant_a, director)
    with django_assert_max_num_queries(8):
        body = client.get("/api/v1/content/files/").json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 5


def test_libraries_list_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        for _ in range(5):
            ContentLibraryFactory(visibility="tenant")

    client = as_user(tenant_a, director)
    with django_assert_max_num_queries(8):
        body = client.get("/api/v1/content/libraries/").json()
    assert body["count"] == 5


def test_library_clean_file_round_trip_api(tenant_a, user_in, as_user, monkeypatch):
    """A clean file is listable + downloadable through the API by a director."""
    _stub_s3(monkeypatch)
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        file: Any = LessonFileFactory(status=LessonFile.Status.CLEAN)
        file_id = file.id

    client = as_user(tenant_a, director)
    detail = client.get(f"/api/v1/content/files/{file_id}/").json()
    assert detail["status"] == "clean"
    dl = client.get(f"/api/v1/content/files/{file_id}/download-url/")
    assert dl.status_code == 200
    assert dl.json()["expires_in"] == 300
    with schema_context(tenant_a.schema_name):
        assert LessonFile.objects.get(pk=file_id).download_count == 1


def test_serializer_hides_thumbnail_key_and_signs_url(tenant_a, user_in, as_user, monkeypatch):
    """The raw schema-prefixed thumbnail_key is never serialized; clients get a
    TTL-limited signed thumbnail_url instead (mirrors download_url)."""
    import infrastructure.storage.s3_client as s3_client

    monkeypatch.setattr(s3_client, "presign_download", lambda key, **kw: f"https://signed/{key}")
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        with_thumb: Any = LessonFileFactory(
            status=LessonFile.Status.CLEAN,
            content_type="image/png",
            thumbnail_key="tenant_a/content/7/thumb.jpg",
        )
        no_thumb: Any = LessonFileFactory(status=LessonFile.Status.CLEAN)
        with_id, no_id = with_thumb.id, no_thumb.id

    client = as_user(tenant_a, director)
    detail = client.get(f"/api/v1/content/files/{with_id}/").json()
    assert "thumbnail_key" not in detail  # raw key never exposed
    assert detail["thumbnail_url"] == "https://signed/tenant_a/content/7/thumb.jpg"

    no_detail = client.get(f"/api/v1/content/files/{no_id}/").json()
    assert no_detail["thumbnail_url"] is None  # no thumbnail → null, not signed
