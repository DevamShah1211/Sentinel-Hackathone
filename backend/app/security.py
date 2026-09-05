"""
Authentication and role enforcement.

Three roles, matching how a statewide deployment would actually be operated:

  state_admin   — everything, including the audit trail and the camera registry
  dept_operator — search, watchlist, alerts, reports for operational work
  viewer        — live view and the map only

The role model is only meaningful if it is enforced, so `require_role` is a
dependency that endpoints declare rather than an advisory note in a document.

Enforcement can be switched off for local development with `AUTH_ENABLED=false`,
which is how the prototype runs when demonstrating the pipeline without logging
in first. That default is deliberate and stated in the HLD rather than hidden: a
deployed instance sets `AUTH_ENABLED=true` and every protected route then requires
a bearer token.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.settings import settings

logger = logging.getLogger("sentinel.security")

# auto_error=False so an anonymous request reaches the dependency and can be
# allowed through when auth is disabled, rather than being rejected by FastAPI
# before our own logic runs.
bearer_scheme = HTTPBearer(auto_error=False)

ROLE_STATE_ADMIN = "state_admin"
ROLE_DEPT_OPERATOR = "dept_operator"
ROLE_VIEWER = "viewer"

# Higher number grants everything a lower number grants.
ROLE_RANK: dict[str, int] = {
    ROLE_VIEWER: 1,
    ROLE_DEPT_OPERATOR: 2,
    ROLE_STATE_ADMIN: 3,
}


class Principal(BaseModel):
    """Who is making a request. Used as the audit actor."""
    id: str | None = None
    email: str = "anonymous"
    username: str = "anonymous"
    role: str = ROLE_VIEWER
    department: str | None = None
    authenticated: bool = False

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)

    def can(self, minimum_role: str) -> bool:
        return self.rank >= ROLE_RANK.get(minimum_role, 99)


# The principal used when authentication is disabled for local development.
DEV_PRINCIPAL = Principal(
    email="dev@localhost", username="dev", role=ROLE_STATE_ADMIN, authenticated=False,
)


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "department": user.department,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """
    Resolve the caller from the bearer token.

    With auth disabled this returns a development principal so the prototype can
    be driven without logging in. With auth enabled a missing or invalid token is
    rejected.
    """
    if credentials is None or not credentials.credentials:
        if settings.auth_enabled:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return DEV_PRINCIPAL

    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key,
                             algorithms=[settings.algorithm])
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    # Re-read the user so a deactivated account loses access immediately rather
    # than at token expiry.
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none() \
        if user_id else None
    if user is not None and not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")

    return Principal(
        id=user_id,
        email=payload.get("email", "unknown"),
        username=payload.get("username", "unknown"),
        role=payload.get("role", ROLE_VIEWER),
        department=payload.get("department"),
        authenticated=True,
    )


def require_role(minimum_role: str):
    """
    Dependency factory enforcing a minimum role.

        @router.get("/audit", dependencies=[Depends(require_role(ROLE_STATE_ADMIN))])
    """
    async def _guard(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.can(minimum_role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action requires the '{minimum_role}' role; "
                f"you hold '{principal.role}'.",
            )
        return principal
    return _guard


RequireViewer = Depends(require_role(ROLE_VIEWER))
RequireOperator = Depends(require_role(ROLE_DEPT_OPERATOR))
RequireStateAdmin = Depends(require_role(ROLE_STATE_ADMIN))
CurrentPrincipal = Depends(current_principal)
