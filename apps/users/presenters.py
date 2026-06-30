"""User presenters — plain dict mappers for the layered (off-DRF) views, replacing
the DRF read serializers. Reused by other domains that embed a compact person view."""

from __future__ import annotations

from typing import Any


def user_brief(user: Any) -> dict[str, Any]:
    """Compact read view of a person (was UserBriefSerializer)."""
    return {
        "id": user.id,
        "username": user.username,
        "phone": user.phone,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "middle_name": user.middle_name,
        "full_name": user.get_full_name(),
        "birthdate": user.birthdate.isoformat() if user.birthdate else None,
        "gender": user.gender,
    }
