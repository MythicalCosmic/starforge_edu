"""Tasks + hierarchy services (F5-2/3)."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.tasks.models import RoleGrade, Task
from core.exceptions import PermissionException, UnprocessableEntity
from core.permissions import has_permission_code

_UNSET: object = object()

# Allowed status transitions. DONE may still be cancelled; both DONE and CANCELLED
# can be reopened to OPEN. A same-status transition is a no-op (handled below).
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Task.Status.OPEN: {Task.Status.IN_PROGRESS, Task.Status.BLOCKED, Task.Status.DONE, Task.Status.CANCELLED},
    Task.Status.IN_PROGRESS: {Task.Status.OPEN, Task.Status.BLOCKED, Task.Status.DONE, Task.Status.CANCELLED},
    Task.Status.BLOCKED: {Task.Status.OPEN, Task.Status.IN_PROGRESS, Task.Status.DONE, Task.Status.CANCELLED},
    Task.Status.DONE: {Task.Status.OPEN, Task.Status.CANCELLED},
    Task.Status.CANCELLED: {Task.Status.OPEN},
}


def _roles_of(user) -> set[str]:
    return {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}


def user_grade(user, roles: set[str] | None = None) -> int:
    """The seniority level of `user` = the max RoleGrade.level over their roles.
    Ungraded roles count as 0 (most junior)."""
    if roles is None:
        roles = _roles_of(user)
    grades = dict(RoleGrade.objects.values_list("role", "level"))
    return max((grades.get(r, 0) for r in roles), default=0)


def can_assign(*, actor, actor_roles: set[str], target_user) -> bool:
    """Hierarchy gate (F5-3): you may assign to an equal/lower grade, unless you
    hold tasks:assign_any (manager/CEO bypass) or are a superuser.

    Fails CLOSED on a partially-configured hierarchy: once any RoleGrade exists, a
    target whose roles are all UNGRADED is treated as unrankable — you may not task
    them without the bypass (so forgetting to grade a senior role can't be exploited
    to task them). An empty grade table means "no hierarchy configured" → unrestricted.
    """
    if getattr(actor, "is_superuser", False):
        return True
    if has_permission_code(actor_roles, "tasks:assign_any"):
        return True
    grades = dict(RoleGrade.objects.values_list("role", "level"))
    if not grades:
        return True  # hierarchy not configured for this center
    actor_grade = max((grades.get(r, 0) for r in actor_roles), default=0)
    target_levels = [grades[r] for r in _roles_of(target_user) if r in grades]
    if not target_levels:
        return False  # target unplaced in the hierarchy -> fail closed
    return actor_grade >= max(target_levels)


def _guard_assignee(actor, actor_roles, assignee) -> None:
    if assignee is not None and not can_assign(actor=actor, actor_roles=actor_roles, target_user=assignee):
        raise PermissionException(
            _("You can only assign tasks to an equal or lower grade."), code="cannot_assign_grade"
        )


@transaction.atomic
def create_task(
    *,
    title: str,
    created_by,
    created_by_roles: set[str],
    assignee=None,
    department=None,
    branch=None,
    description: str = "",
    priority: str = Task.Priority.NORMAL,
    due_at=None,
) -> Task:
    _guard_assignee(created_by, created_by_roles, assignee)
    return Task.objects.create(
        title=title,
        description=description,
        assignee=assignee,
        department=department,
        branch=branch,
        priority=priority,
        due_at=due_at,
        created_by=created_by,
    )


@transaction.atomic
def assign_task(*, task: Task, actor, actor_roles: set[str], assignee=_UNSET, department=_UNSET) -> Task:
    """Reassign a task to a person and/or a department. The person assignment is
    hierarchy-gated; clearing an assignee (None) is always allowed."""
    fields: list[str] = []
    if assignee is not _UNSET:
        _guard_assignee(actor, actor_roles, assignee)
        task.assignee = assignee
        fields.append("assignee")
    if department is not _UNSET:
        task.department = department
        fields.append("department")
    if fields:
        fields.append("updated_at")
        task.save(update_fields=fields)
    return task


@transaction.atomic
def transition_task(*, task: Task, to_status: str, actor=None) -> Task:
    if to_status == task.status:
        return task  # no-op
    if to_status not in _ALLOWED_TRANSITIONS.get(task.status, set()):
        raise UnprocessableEntity(
            _("That status change is not allowed from the task's current state."),
            code="invalid_transition",
        )
    task.status = to_status
    task.completed_at = timezone.now() if to_status == Task.Status.DONE else None
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return task
