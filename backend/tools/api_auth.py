"""
Authenticate a tool's requests session against the platform API.

The detection ingest and registry routes require an authenticated principal —
the detection index is the evidentiary record, so writing to it needs an
identity. Every tool that writes through the API therefore needs a token, and
this is the one place that logic lives.

Order of preference:

  1. SENTINEL_WORKER_TOKEN — a token issued elsewhere, for unattended runs.
  2. DEMO_ADMIN_EMAIL / DEMO_ADMIN_PASSWORD from settings, exchanged for one.

If neither works the caller is told exactly what to set, because the failure it
would otherwise produce is a wall of 401s that looks like a bug in the tool
rather than a missing credential.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("sentinel.tools")


def authenticate(session: requests.Session, api_base: str) -> bool:
    """
    Attach a bearer token to `session`. Returns True when authenticated.

    Never raises: a tool that cannot authenticate should say so plainly and
    continue or exit on its own terms, rather than dying in a traceback.
    """
    token = os.getenv("SENTINEL_WORKER_TOKEN", "").strip()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
        return True

    try:
        from app.settings import settings
        email = settings.demo_admin_email
        password = settings.demo_admin_password
    except Exception:                                    # pragma: no cover
        email = password = ""

    if not password:
        print("\nNo API credentials available.\n"
              "  Set SENTINEL_WORKER_TOKEN, or DEMO_ADMIN_PASSWORD in backend/.env\n"
              "  to the password printed when the demonstration accounts were seeded.\n")
        return False

    try:
        response = requests.post(f"{api_base}/auth/login",
                                 json={"email": email, "password": password},
                                 timeout=20)
        response.raise_for_status()
        session.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        return True
    except requests.RequestException as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 401:
            print(f"\nThe API rejected {email}.\n"
                  "  DEMO_ADMIN_PASSWORD in backend/.env does not match the account.\n")
        else:
            print(f"\nCould not reach the API at {api_base} ({exc}).\n"
                  "  Start it with:  python run_server.py\n")
        return False


def authenticated_session(api_base: str) -> requests.Session | None:
    """
    A requests.Session carrying a bearer token, or None if none could be had.

    Convenience for tools that used module-level `requests.post(...)` calls: swap
    `requests` for the returned session and every call is authenticated.
    """
    session = requests.Session()
    return session if authenticate(session, api_base) else None
