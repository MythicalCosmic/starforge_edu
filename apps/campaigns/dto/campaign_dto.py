"""Campaign-domain DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateCampaignDTO:
    name: str
    message: str = ""
    template_id: int | None = None
    branch_id: int | None = None
    segment: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateTemplateDTO:
    name: str
    category: str = ""
    purpose: str = ""
