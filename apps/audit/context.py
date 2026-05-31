"""Request-scoped actor context for audit attribution.

Signals fire deep in the ORM with no access to the request, so AuditMiddleware
stashes the current actor/ip/user-agent in a ContextVar that audit_log() reads.
ContextVars are coroutine- and thread-safe, so this is correct under ASGI too.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser


@dataclass
class ActorContext:
    user: AbstractBaseUser | None = None
    ip: str | None = None
    user_agent: str = ""


_current: ContextVar[ActorContext | None] = ContextVar("audit_actor", default=None)


def set_actor(ctx: ActorContext | None) -> object:
    return _current.set(ctx)


def reset_actor(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


def get_actor() -> ActorContext:
    return _current.get() or ActorContext()


def set_actor_user(user: AbstractBaseUser | None) -> None:
    """Refine the current context's user, preserving ip/user-agent.

    Called from the DRF view layer (TenantSafeModelViewSet.initial) once
    authentication has run — middleware sees request.user before DRF auth
    populates it, so the API actor must be set here.
    """
    ctx = get_actor()
    _current.set(ActorContext(user=user, ip=ctx.ip, user_agent=ctx.user_agent))
