from __future__ import annotations

from rest_framework import serializers

from apps.messaging.models import Message, Thread, ThreadParticipant


class ThreadParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ThreadParticipant
        fields = ("user", "last_read_at", "added_at")
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ("id", "thread", "sender", "body", "attachments", "created_at")
        read_only_fields = fields


class ThreadSerializer(serializers.ModelSerializer):
    participants = ThreadParticipantSerializer(many=True, read_only=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = (
            "id",
            "subject",
            "branch",
            "created_by",
            "last_message_at",
            "created_at",
            "participants",
            "unread_count",
        )
        read_only_fields = fields

    def get_unread_count(self, obj) -> int:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return 0
        uid = request.user.id
        part = next((p for p in obj.participants.all() if p.user_id == uid), None)
        last_read = part.last_read_at if part else None
        # Messages from others, newer than the viewer's last read.
        return sum(
            1
            for m in obj.messages.all()
            if m.sender_id != uid and (last_read is None or m.created_at > last_read)
        )


class ThreadCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    participant_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    first_body = serializers.CharField(required=False, allow_blank=True, default="")
    attachments = serializers.JSONField(required=False, default=list)  # type: ignore[arg-type]


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField()
    attachments = serializers.JSONField(required=False, default=list)  # type: ignore[arg-type]
