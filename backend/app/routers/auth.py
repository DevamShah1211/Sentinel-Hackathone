"""
Authentication — login, registration and the current user.

Roles are defined and enforced in `app.security`; this router only issues and
describes tokens. Three demonstration accounts are seeded on first start so a
deployed instance has working credentials to hand to an evaluator, and so the
role model can be shown rather than merely described.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models import User
from app.security import (
    ROLE_DEPT_OPERATOR,
    ROLE_STATE_ADMIN,
    ROLE_VIEWER,
    CurrentPrincipal,
    Principal,
    RequireStateAdmin,
    create_access_token,
)
from app.settings import settings

logger = logging.getLogger("sentinel.auth")
router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        # A malformed stored hash must fail closed, not raise a 500.
        return False


# ─── Schemas ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    role: str = ROLE_VIEWER
    department: Optional[str] = None


class UserOut(BaseModel):
    id: UUID
    email: str
    username: str
    role: str
    department: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in_minutes: int
    user: UserOut


class LoginRequest(BaseModel):
    email: str
    password: str


# ─── Seeding ──────────────────────────────────────────────────────────────────

def _demo_users() -> tuple[tuple[str, str, str, str, str], ...]:
    """
    The demonstration accounts, with passwords generated rather than published.

    Every password here used to be a constant in this file. That is safe only
    while authentication is switched off — the moment a deployment enables it,
    three known-password accounts exist, one of them state admin, and the
    credentials are in a public repository. Switching auth on is supposed to
    make the system safer, not hand an attacker the door key.

    A password supplied through configuration is respected; otherwise one is
    generated per account and logged once, at creation, so the operator can
    record it. Nothing is reset on later starts.
    """
    admin_password = settings.demo_admin_password or secrets.token_urlsafe(18)
    return (
        # (email, username, password, role, department)
        (settings.demo_admin_email, "State Admin", admin_password,
         ROLE_STATE_ADMIN, "Home Department"),
        ("operator@sentinel.gujarat.gov.in", "Traffic Operator",
         secrets.token_urlsafe(18), ROLE_DEPT_OPERATOR, "Traffic Police"),
        ("viewer@sentinel.gujarat.gov.in", "Control Room Viewer",
         secrets.token_urlsafe(18), ROLE_VIEWER, "City Surveillance"),
    )


async def seed_demo_users() -> None:
    """
    Create the demonstration accounts, when explicitly asked to.

    Only ever creates; an existing account is left alone so a changed password is
    never silently reset back to the default.
    """
    if not settings.seed_demo_users:
        logger.info("Demonstration accounts not seeded (SEED_DEMO_USERS is false).")
        return

    async with AsyncSessionLocal() as db:
        created = []
        for email, username, password, role, department in _demo_users():
            exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if exists:
                continue
            db.add(User(
                email=email,
                username=username,
                hashed_password=hash_password(password),
                role=role,
                department=department,
                is_active=True,
            ))
            created.append(f"    {email}  role={role}  password={password}")
        if created:
            await db.commit()
            # Logged once, at creation, because a generated password that is
            # never shown cannot be used. Subsequent starts print nothing.
            logger.warning(
                "Seeded %d demonstration account(s). Record these now — they are "
                "not stored anywhere else and will not be shown again:%s%s",
                len(created), chr(10), chr(10).join(created))


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/token", response_model=Token, summary="Login (OAuth2 form) — returns a JWT")
async def login_form(form: OAuth2PasswordRequestForm = Depends(),
                     db: AsyncSession = Depends(get_db)):
    return await _authenticate(form.username, form.password, db)


@router.post("/login", response_model=Token, summary="Login (JSON) — returns a JWT")
async def login_json(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    return await _authenticate(body.email, body.password, db)


async def _authenticate(email: str, password: str, db: AsyncSession) -> dict:
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    # Same message and same work whether the account exists or the password is
    # wrong, so the response does not reveal which addresses are registered.
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")

    logger.info("Login: %s (%s)", user.email, user.role)
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "expires_in_minutes": settings.access_token_expire_minutes,
        "user": user,
    }


@router.get("/me", response_model=UserOut, summary="The authenticated user")
async def me(principal: Principal = CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    if principal.id:
        user = (await db.execute(select(User).where(User.id == principal.id))).scalar_one_or_none()
        if user:
            return user
    # Auth disabled — describe the development principal rather than 404.
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


@router.get("/roles", summary="The role model and what each role may do")
async def roles():
    """Documents the role model so it can be shown, not just asserted."""
    return {
        "auth_enabled": settings.auth_enabled,
        "roles": [
            {"role": ROLE_STATE_ADMIN, "rank": 3,
             "grants": ["everything", "audit trail", "camera registry changes",
                        "user management"]},
            {"role": ROLE_DEPT_OPERATOR, "rank": 2,
             "grants": ["plate search", "route reconstruction", "watchlist",
                        "alert acknowledge/resolve", "report export"]},
            {"role": ROLE_VIEWER, "rank": 1,
             "grants": ["camera map", "live viewing"]},
        ],
    }


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             summary="Create a user (state admin only)")
async def register(body: UserCreate,
                   db: AsyncSession = Depends(get_db),
                   _: Principal = RequireStateAdmin):
    existing = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if body.role not in (ROLE_STATE_ADMIN, ROLE_DEPT_OPERATOR, ROLE_VIEWER):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown role '{body.role}'")

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role,
        department=body.department,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
