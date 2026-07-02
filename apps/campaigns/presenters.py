"""Campaign-domain presenters — plain dict mappers (replace the DRF serializers)."""

from __future__ import annotations

from typing import Any

from apps.campaigns.models import Campaign, CampaignRecipient, DoNotContact, MessageTemplate


def campaign_to_dict(c: Campaign) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "message": c.message,
        "segment": c.segment,
        "branch": c.branch_id,
        "status": c.status,
        "total": c.total,
        "sent_count": c.sent_count,
        "failed_count": c.failed_count,
        "skipped_count": c.skipped_count,
        "created_by": c.created_by_id,
        "sent_by": c.sent_by_id,
        "sent_at": c.sent_at.isoformat() if c.sent_at else None,
        "created_at": c.created_at.isoformat(),
    }


def recipient_to_dict(r: CampaignRecipient) -> dict[str, Any]:
    return {
        "id": r.id,
        "student": r.student_id,
        "phone": r.phone,
        "status": r.status,
        "error": r.error,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
    }


def do_not_contact_to_dict(d: DoNotContact) -> dict[str, Any]:
    return {
        "id": d.id,
        "phone": d.phone,
        "reason": d.reason,
        "created_by": d.created_by_id,
        "created_at": d.created_at.isoformat(),
    }


def template_to_dict(t: MessageTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "category": t.category,
        "purpose": t.purpose,
        "body": t.body,
        "is_active": t.is_active,
        "created_by": t.created_by_id,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }
