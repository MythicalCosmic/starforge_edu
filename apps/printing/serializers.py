"""Printing serializers (read/write split, D4-LD-3/7)."""

from __future__ import annotations

from rest_framework import serializers

from apps.printing.models import BranchAgent, Printer, PrintJob


# --------------------------------------------------------------------------- #
# Printer
# --------------------------------------------------------------------------- #
class PrinterReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Printer
        fields = (
            "id",
            "branch",
            "name",
            "model_name",
            "capabilities",
            "is_active",
            "created_at",
            "updated_at",
        )


class PrinterWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Printer
        fields = ("id", "branch", "name", "model_name", "capabilities", "is_active")


# --------------------------------------------------------------------------- #
# BranchAgent
# --------------------------------------------------------------------------- #
class BranchAgentReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchAgent
        # token_hash is intentionally NEVER serialized.
        fields = ("id", "branch", "name", "last_seen_at", "revoked_at", "created_at")


class BranchAgentCreateSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    name = serializers.CharField(max_length=120)


class BranchAgentCreatedSerializer(serializers.ModelSerializer):
    """Returned once on creation — includes the raw token (shown a single time)."""

    token = serializers.CharField(read_only=True)

    class Meta:
        model = BranchAgent
        fields = ("id", "branch", "name", "token", "created_at")


# --------------------------------------------------------------------------- #
# PrintJob
# --------------------------------------------------------------------------- #
class PrintJobReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrintJob
        fields = (
            "id",
            "branch",
            "printer",
            "agent",
            "status",
            "source",
            "source_id",
            "payload_s3_key",
            "pages",
            "copies",
            "color",
            "duplex",
            "cohort_id",
            "requested_by",
            "attempts",
            "next_attempt_at",
            "pages_printed",
            "last_error",
            "created_at",
            "claimed_at",
            "finished_at",
        )


class PrintJobCreateSerializer(serializers.Serializer):
    """Staff create path (POST /printing/jobs/). Service applies the quota."""

    # ``source`` shadows DRF's ``Field.source`` attribute; the ignore is the
    # documented way to declare a serializer field with that name.
    source = serializers.ChoiceField(choices=PrintJob.Source.choices)  # type: ignore[assignment]
    source_id = serializers.IntegerField(min_value=1)
    payload_s3_key = serializers.CharField(max_length=512)
    branch = serializers.IntegerField(min_value=1)
    pages = serializers.IntegerField(min_value=1)
    copies = serializers.IntegerField(min_value=1, default=1)
    color = serializers.BooleanField(default=False)
    duplex = serializers.BooleanField(default=False)
    cohort = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class AgentClaimResponseSerializer(serializers.Serializer):
    job = PrintJobReadSerializer()
    download_url = serializers.CharField()


class AgentStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(
            (PrintJob.Status.PRINTING, "printing"),
            (PrintJob.Status.DONE, "done"),
            (PrintJob.Status.FAILED, "failed"),
        )
    )
    error = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    pages_printed = serializers.IntegerField(min_value=0, required=False, allow_null=True, default=None)
