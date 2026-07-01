"""Parent-domain presenters — plain dict mappers (replace the DRF ModelSerializers)."""

from __future__ import annotations

from typing import Any

from apps.parents.models import Guardian, ParentProfile, PickupAuthorization
from apps.users.presenters import user_brief


def parent_to_dict(parent: ParentProfile) -> dict[str, Any]:
    return {
        "id": parent.id,
        "user": user_brief(parent.user),
        "workplace": parent.workplace,
        "notes": parent.notes,
        "created_at": parent.created_at.isoformat(),
    }


def guardian_to_dict(g: Guardian) -> dict[str, Any]:
    return {
        "id": g.id,
        "parent": g.parent_id,
        "student": g.student_id,
        "relationship": g.relationship,
        "is_primary": g.is_primary,
        "custody_notes": g.custody_notes,
    }


def pickup_to_dict(p: PickupAuthorization) -> dict[str, Any]:
    return {
        "id": p.id,
        "student": p.student_id,
        "full_name": p.full_name,
        "phone": p.phone,
        "relationship": p.relationship,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat(),
    }
