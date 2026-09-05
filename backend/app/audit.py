"""
Audit logging — who looked at what, and why.

Surveillance data carries an accountability obligation that ordinary application
data does not. Every search, export and route reconstruction is recorded with the
actor, the object, the stated purpose and a case reference, so access to citizen
movement data can be reviewed after the fact.

This is also the DPDP Act 2023 posture: purpose limitation is only meaningful if
the purpose is captured at the point of access, and an audit trail nobody can
query is not an audit trail.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

logger = logging.getLogger("sentinel.audit")


async def record(
    db: AsyncSession,
    actor: str,
    action: str,
    object_type: str | None = None,
    object_id: str | None = None,
    purpose: str | None = None,
    case_ref: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> None:
    """
    Write one audit entry.

    Auditing must never break the operation it is auditing: a failure here is
    logged and swallowed, because losing a search result to a logging error is a
    worse outcome than a gap in the trail.
    """
    payload = dict(details or {})
    if request is not None:
        client = request.client
        payload.setdefault("ip", client.host if client else None)
        payload.setdefault("user_agent", request.headers.get("user-agent"))

    try:
        db.add(AuditLog(
            actor=actor or "anonymous",
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            purpose=purpose,
            case_ref=case_ref,
            details=payload,
        ))
        if commit:
            await db.commit()
    except Exception as exc:  # never let the audit trail break the request
        logger.warning("Audit write failed for %s/%s: %s", action, object_type, exc)
