"""Cohort service port — the contract the views resolve from the container."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from django.db.models import QuerySet

from apps.cohorts.dto.cohort_dto import CohortCreateDTO, CohortEnrollDTO, CohortMoveDTO
from apps.cohorts.models import Cohort, CohortMembership


class ICohortService(ABC):
    @abstractmethod
    def list(self) -> QuerySet[Cohort]:
        """Base (unscoped) queryset with relations eager-loaded; the view scopes +
        filters + paginates it."""

    @abstractmethod
    def get(self, cohort_id: int) -> Cohort | None: ...

    @abstractmethod
    def create(self, data: CohortCreateDTO) -> Cohort: ...

    @abstractmethod
    def update(self, cohort: Cohort, changes: dict[str, Any]) -> Cohort:
        """Apply the provided fields (PATCH-style); archived cohorts are read-only."""

    @abstractmethod
    def delete(self, cohort: Cohort) -> None:
        """Hard-delete only an empty, unarchived cohort; else 400/409 (history is kept)."""

    @abstractmethod
    def unarchive(self, cohort: Cohort) -> Cohort: ...

    @abstractmethod
    def enroll(self, cohort: Cohort, data: CohortEnrollDTO) -> CohortMembership: ...

    @abstractmethod
    def move(self, cohort: Cohort, data: CohortMoveDTO, actor) -> dict[str, Any]:
        """Move a student into ``cohort`` (history preserved); returns
        {membership, over_capacity}."""

    @abstractmethod
    def members(self, cohort: Cohort) -> QuerySet[CohortMembership]: ...
