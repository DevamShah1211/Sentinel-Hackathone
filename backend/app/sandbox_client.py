"""
Sentinel sandbox client — authenticated access to the Gujarat CCTV grid.

The sandbox sits behind a login (GET /api/ingest returns 302 -> /auth/login), so
every catalogue fetch must carry a session cookie. This module owns that concern:
log in once, cache the cookie jar, and re-authenticate transparently when the
session lapses.

Per the playbook's sandbox rules: the catalogue is the contract. We never hardcode
camera ids or URL patterns — whatever /api/ingest returns is what we store.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger("sentinel.sandbox")

# Where the raw catalogue is committed to disk. The playbook asks for this to be
# in the repo: it is the camera inventory, the GIS layer and the onboarding demo.
CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "catalogue.json"

# Endpoints tried in order. /api/ingest is the documented contract; the others are
# fallbacks observed on the sandbox host.
CATALOGUE_PATHS = ("/api/ingest", "/cameras.json", "/api/cameras")

# Login forms observed on the portal. Tried in order until a session cookie appears.
_LOGIN_PATHS = ("/auth/login", "/api/auth/login", "/login")


class SandboxClient:
    """Authenticated HTTP client for the Sentinel sandbox."""

    def __init__(self, host: str | None = None, email: str | None = None,
                 password: str | None = None, timeout: float = 30.0):
        self.host = host or settings.sentinel_cdn_host
        self.email = email or settings.sentinel_user_email
        self.password = password or settings.sentinel_user_password
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def base(self) -> str:
        return f"https://{self.host}"

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "Sentinel-Platform/1.0 (Gujarat CCTV Hackathon 2026)"},
            )
        return self._client

    async def login(self) -> bool:
        """
        Authenticate against the portal. Returns True if a session cookie was issued.

        The portal accepts a form POST; we also try JSON since the login route is
        undocumented and has changed shape before.
        """
        if not self.email or not self.password:
            logger.warning("No sandbox credentials configured — set SENTINEL_USER_EMAIL "
                           "and SENTINEL_USER_PASSWORD in backend/.env")
            return False

        client = await self._ensure_client()
        creds = {"email": self.email, "password": self.password}

        for path in _LOGIN_PATHS:
            url = f"{self.base}{path}"
            for kind in ("form", "json"):
                try:
                    if kind == "form":
                        resp = await client.post(url, data=creds)
                    else:
                        resp = await client.post(url, json=creds)
                except httpx.HTTPError as exc:
                    logger.debug("Login attempt %s (%s) failed: %s", url, kind, exc)
                    continue

                if client.cookies and len(client.cookies):
                    logger.info("Sandbox login succeeded via %s (%s) — session established", path, kind)
                    return True
                logger.debug("Login %s (%s) returned %s with no cookie", path, kind, resp.status_code)

        logger.warning("Sandbox login did not yield a session cookie — catalogue fetch may return the login page")
        return False

    async def fetch_catalogue(self) -> list[dict[str, Any]]:
        """
        Pull the camera catalogue, authenticating first. Returns [] on failure so
        callers fall back to whatever is already in the database.
        """
        client = await self._ensure_client()
        await self.login()

        for path in CATALOGUE_PATHS:
            url = f"{self.base}{path}"
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                logger.debug("Catalogue fetch %s failed: %s", url, exc)
                continue

            if resp.status_code != 200:
                logger.debug("Catalogue %s -> HTTP %s", url, resp.status_code)
                continue

            # A login page comes back as HTML with a 200; detect and skip it.
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype:
                logger.debug("Catalogue %s returned %s, not JSON (likely the login page)", url, ctype)
                continue

            try:
                data = resp.json()
            except json.JSONDecodeError:
                continue

            cameras = self._extract_camera_list(data)
            if cameras:
                logger.info("Fetched %d cameras from %s", len(cameras), url)
                self._persist(data)
                return cameras

        logger.warning("Could not reach any sandbox catalogue endpoint")
        return []

    @staticmethod
    def _extract_camera_list(data: Any) -> list[dict[str, Any]]:
        """The catalogue has appeared both as a bare list and wrapped in an object."""
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict)]
        if isinstance(data, dict):
            for key in ("cameras", "data", "items", "results"):
                val = data.get(key)
                if isinstance(val, list):
                    return [c for c in val if isinstance(c, dict)]
        return []

    @staticmethod
    def _persist(data: Any) -> None:
        """Commit the raw catalogue to disk — it is a submission artefact."""
        try:
            CATALOGUE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info("Catalogue written to %s", CATALOGUE_PATH)
        except OSError as exc:
            logger.warning("Could not write catalogue.json: %s", exc)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


async def fetch_catalogue() -> list[dict[str, Any]]:
    """Convenience wrapper — one-shot authenticated catalogue fetch."""
    client = SandboxClient()
    try:
        return await client.fetch_catalogue()
    finally:
        await client.aclose()
