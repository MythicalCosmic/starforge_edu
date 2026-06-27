from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.forms import services
from apps.forms.models import Form
from apps.forms.serializers import (
    FormCreateSerializer,
    FormFieldSerializer,
    FormResponseSerializer,
    FormSerializer,
    FormUpdateSerializer,
    SubmitResponseSerializer,
)
from apps.org.models import Branch
from core.exceptions import PermissionException, ValidationException
from core.permissions import (
    Role,
    default_perms,
    get_role_memberships,
    get_user_roles,
    has_permission_code,
)
from core.viewsets import TenantSafeModelViewSet


class FormViewSet(TenantSafeModelViewSet):
    """Forms / surveys engine (F3-3). Builders (forms:write) create, add fields,
    publish/close, and read responses + the aggregate summary. Anyone with
    forms:read can see published forms and submit a response — builders see all
    forms (incl. drafts); everyone else sees only published ones."""

    serializer_class = FormSerializer
    resource = "forms"
    required_perms = {
        **default_perms("forms"),
        "add_field": "forms:write",
        "publish": "forms:write",
        "close": "forms:write",
        "responses": "forms:write",
        "summary": "forms:write",
        "analyze": "forms:write",
        "submit": "forms:read",
    }
    search_fields = ("title",)
    ordering_fields = ("created_at", "title")
    filterset_fields = ("status", "branch", "is_anonymous")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def _is_director(self) -> bool:
        return self.request.user.is_superuser or Role.DIRECTOR in get_user_roles(self.request)

    def get_queryset(self):
        qs = Form.objects.select_related("branch", "created_by").prefetch_related("fields")
        if self._is_director():
            return qs  # the director sees the whole center
        roles = get_user_roles(self.request)
        if has_permission_code(roles, "forms:write"):
            # A builder manages only their own branches' forms (+ anything they made) —
            # never another branch's responses/summaries (the isolation gate, since
            # every detail action resolves through get_object -> this queryset).
            return qs.filter(Q(created_by=self.request.user) | Q(branch_id__in=self._branch_ids()))
        # Responders: published forms in their branch, plus center-wide (branch null).
        return qs.filter(status=Form.Status.PUBLISHED).filter(
            Q(branch_id__in=self._branch_ids()) | Q(branch__isnull=True)
        )

    def get_serializer_class(self):
        if self.action == "create":
            return FormCreateSerializer
        if self.action in ("update", "partial_update"):
            return FormUpdateSerializer
        return FormSerializer

    @extend_schema(request=FormCreateSerializer, responses={201: FormSerializer}, tags=["forms"])
    def create(self, request, *args, **kwargs):
        ser = FormCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        if not self._is_director():
            # A non-director builds only within their own branch; only the director
            # may create a center-wide (branch=None) form that reaches every branch.
            my_branches = self._branch_ids()
            branch = data.get("branch")
            if branch is None:
                if len(my_branches) == 1:
                    data["branch"] = Branch.objects.get(pk=next(iter(my_branches)))
                else:
                    raise ValidationException(_("Choose a branch for this form."), code="branch_required")
            elif branch.id not in my_branches:
                raise PermissionException(
                    _("You can only create forms in your own branch."), code="cross_branch"
                )
        form = services.create_form(created_by=request.user, **data)
        return Response(FormSerializer(form).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        form = self.get_object()
        ser = FormUpdateSerializer(data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        form = services.update_form(form=form, **ser.validated_data)
        return Response(FormSerializer(form).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        # DRAFT-only: a published/closed form holds collected responses and must
        # not be hard-deleted unilaterally (would CASCADE the responses away).
        services.delete_form(form=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=FormFieldSerializer, responses={201: FormFieldSerializer}, tags=["forms"])
    @action(detail=True, methods=["post"], url_path="fields")
    def add_field(self, request, pk=None):
        form = self.get_object()
        ser = FormFieldSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        field = services.add_field(form=form, **ser.validated_data)
        return Response(FormFieldSerializer(field).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: FormSerializer}, tags=["forms"])
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        form = services.publish_form(form=self.get_object())
        return Response(FormSerializer(form).data)

    @extend_schema(request=None, responses={200: FormSerializer}, tags=["forms"])
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        form = services.close_form(form=self.get_object())
        return Response(FormSerializer(form).data)

    @extend_schema(
        request=SubmitResponseSerializer,
        responses={201: OpenApiResponse(description="{id, created_at}")},
        tags=["forms"],
    )
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        form = self.get_object()
        ser = SubmitResponseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        response = services.submit_response(
            form=form, respondent=request.user, answers=ser.validated_data["answers"]
        )
        # Anonymous-safe: only echo the receipt, never the respondent.
        return Response(
            {"id": response.id, "created_at": response.created_at}, status=status.HTTP_201_CREATED
        )

    @extend_schema(responses={200: FormResponseSerializer(many=True)}, tags=["forms"])
    @action(detail=True, methods=["get"])
    def responses(self, request, pk=None):
        form = self.get_object()
        qs = form.responses.select_related("respondent").prefetch_related("answers")
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(FormResponseSerializer(page, many=True).data)
        return Response(FormResponseSerializer(qs, many=True).data)

    @extend_schema(responses={200: OpenApiResponse(description="aggregate summary")}, tags=["forms"])
    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        return Response(services.form_summary(self.get_object()))

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(description="{request_id, status} — poll /ai/requests/{id}/")},
        tags=["forms"],
    )
    @action(detail=True, methods=["post"])
    def analyze(self, request, pk=None):
        """F3-4: AI-analyze this form's responses (async). The narrative is stored on
        the AI request; charts come from /summary/. Poll the AI request for status."""
        ai_request = services.request_form_analysis(form=self.get_object(), requested_by=request.user)
        return Response(
            {"request_id": ai_request.pk, "status": ai_request.status},
            status=status.HTTP_202_ACCEPTED,
        )
