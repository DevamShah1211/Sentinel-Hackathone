"""
Regressions for the security audit of 9 September 2026.

Every test here corresponds to a vulnerability that was live in this codebase
and was verified by exploiting it against a running instance. They assert
behaviour rather than implementation where possible, so a future refactor that
reintroduces a hole fails rather than passing on a technicality.

The audit and its findings are recorded in DOCS/SECURITY_AUDIT.md.
"""
from __future__ import annotations

import importlib
import inspect
from unittest.mock import Mock, patch

import pytest


class TestCredentialsAreNotDisclosed:
    """
    C1. GET /cameras/internal/streams returned the sandbox RTSP password,
    unauthenticated, for up to a thousand cameras - the credential for the live
    Gujarat Police camera grid, in a JSON body, discoverable from the open
    OpenAPI schema.
    """

    def test_strip_credentials_removes_userinfo(self):
        from app.routers.cameras import _strip_credentials
        stripped = _strip_credentials(
            "rtsp://user%40mail.com:s3cret@1.2.3.4:8554/stream/cam01")
        assert stripped == "rtsp://1.2.3.4:8554/stream/cam01"
        assert "s3cret" not in stripped

    def test_strip_credentials_leaves_clean_urls_alone(self):
        from app.routers.cameras import _strip_credentials
        url = "https://cdn.example/cam14/index.m3u8"
        assert _strip_credentials(url) == url

    def test_at_sign_in_path_is_not_treated_as_userinfo(self):
        """Only an '@' inside the authority delimits credentials."""
        from app.routers.cameras import _strip_credentials
        url = "rtsp://host/path@weird"
        assert _strip_credentials(url) == url

    def test_handles_empty_input(self):
        from app.routers.cameras import _strip_credentials
        assert _strip_credentials(None) is None
        assert _strip_credentials("") == ""

    def test_internal_streams_requires_a_principal(self):
        from app.routers.cameras import internal_stream_urls
        assert "principal" in inspect.signature(internal_stream_urls).parameters

    def test_internal_streams_strips_before_returning(self):
        from app.routers.cameras import internal_stream_urls
        source = inspect.getsource(internal_stream_urls)
        assert "_strip_credentials(cam.rtsp_url)" in source


class TestAuthenticationFailsClosed:
    """
    C2. auth_enabled defaulted to False and the fallback principal carries the
    state-admin role, so an unset environment variable promoted every anonymous
    request to administrator and disabled every RBAC guard, audit included.
    """

    def test_auth_is_enabled_by_default(self):
        from app.settings import Settings
        assert Settings.model_fields["auth_enabled"].default is True

    def test_demo_users_are_not_seeded_by_default(self):
        from app.settings import Settings
        assert Settings.model_fields["seed_demo_users"].default is False

    def test_demo_admin_password_is_not_a_published_constant(self):
        from app.settings import Settings
        assert Settings.model_fields["demo_admin_password"].default == ""

    def test_generated_demo_passwords_are_unique_and_long(self):
        from app.routers.auth import _demo_users
        passwords = [u[2] for u in _demo_users()]
        assert len(set(passwords)) == len(passwords)
        assert all(len(p) >= 16 for p in passwords)


class TestPrivilegedRoutesAreGuarded:
    """
    C3 / H1 / H4 / H5. Watchlist, alerts, detection ingest, camera mutation and
    catalogue sync were all reachable with no authentication. The watchlist is
    active police case data; the detection index is the evidentiary record.
    """

    @pytest.mark.parametrize("module,function", [
        ("app.routers.watchlist", "list_watchlist"),
        ("app.routers.watchlist", "add_to_watchlist"),
        ("app.routers.watchlist", "remove_from_watchlist"),
        ("app.routers.watchlist", "bulk_import"),
        ("app.routers.alerts", "list_alerts"),
        ("app.routers.alerts", "acknowledge_alert"),
        ("app.routers.alerts", "resolve_alert"),
        ("app.routers.detections", "create_detection"),
        ("app.routers.detections", "recent_detections"),
        ("app.routers.cameras", "update_camera"),
        ("app.routers.cameras", "create_camera"),
        ("app.routers.cameras", "cameras_geojson"),
        ("app.routers.ingest", "sync_catalogue"),
    ])
    def test_route_resolves_a_principal(self, module, function):
        fn = getattr(importlib.import_module(module), function)
        assert "principal" in inspect.signature(fn).parameters, (
            f"{module}.{function} is reachable without authentication")


class TestAuditAttributionCannotBeForged:
    """
    C3. acknowledge_alert took the acknowledging officer from a query parameter
    defaulting to "operator", so the caller chose the name recorded against the
    action. An audit record its own subject can author is not an audit record.
    """

    def test_acknowledger_comes_from_the_principal(self):
        from app.routers.alerts import acknowledge_alert
        source = inspect.getsource(acknowledge_alert)
        assert "alert.acknowledged_by = principal.email" in source
        assert "operator: str = Query" not in source


class TestMassAssignmentIsClosed:
    """
    H4. PATCH /cameras/{id} took an untyped dict and assigned any matching
    attribute, so every column was writable - including rtsp_url, which let an
    attacker repoint a camera at a host of their choosing and have the server
    fetch it. That is a stream hijack and an SSRF primitive in one.
    """

    def test_update_uses_a_typed_model(self):
        from app.routers.cameras import update_camera
        annotation = inspect.signature(update_camera).parameters["body"].annotation
        assert annotation is not dict
        assert getattr(annotation, "__name__", "") == "CameraUpdate"

    def test_stream_urls_are_not_client_writable(self):
        from app.routers.cameras import CameraUpdate
        for field in ("rtsp_url", "hls_url", "whep_url"):
            assert field not in CameraUpdate.model_fields

    def test_unknown_fields_are_rejected(self):
        from app.routers.cameras import CameraUpdate
        assert CameraUpdate.model_config.get("extra") == "forbid"
        with pytest.raises(Exception):
            CameraUpdate(rtsp_url="rtsp://attacker.example/evil")

    def test_coordinates_are_range_checked(self):
        from app.routers.cameras import CameraUpdate
        with pytest.raises(Exception):
            CameraUpdate(lat=999.0)


class TestRateLimiterCannotBeBypassed:
    """
    M4. The limiter keyed on X-Forwarded-For with no trusted-proxy check, so a
    client could present a different address per request and get a fresh bucket
    each time - making the ten-per-minute login limit unlimited in practice.
    """

    def test_forwarded_header_ignored_from_untrusted_peer(self):
        from app.middleware import RateLimitMiddleware
        request = Mock()
        request.client.host = "203.0.113.9"
        request.headers = {"X-Forwarded-For": "1.1.1.1"}
        assert RateLimitMiddleware._client_key(request) == "203.0.113.9"

    def test_forwarded_header_honoured_from_trusted_proxy(self):
        from app.middleware import RateLimitMiddleware
        request = Mock()
        request.client.host = "10.0.0.1"
        request.headers = {"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}
        with patch("app.middleware.settings") as settings:
            settings.trusted_proxy_set = frozenset({"10.0.0.1"})
            assert RateLimitMiddleware._client_key(request) == "1.1.1.1"

    def test_trusted_proxies_defaults_to_trusting_nothing(self):
        from app.settings import Settings
        assert Settings.model_fields["trusted_proxies"].default == ""


class TestUploadsAreBounded:
    """M3. Both CSV import paths read the whole upload into memory unbounded."""

    def test_watchlist_import_has_byte_and_row_caps(self):
        from app.routers import watchlist
        assert watchlist.MAX_IMPORT_BYTES <= 10 * 1024 * 1024
        assert watchlist.MAX_IMPORT_ROWS <= 100_000
        source = inspect.getsource(watchlist.bulk_import)
        assert "MAX_IMPORT_BYTES" in source
        assert "await file.read()" not in source


class TestDeletedAccountsLoseAccess:
    """
    M5. A token whose subject no longer existed fell through and built the
    principal from the token's own claims, so a deleted account kept working at
    its original privilege until the token expired.
    """

    def test_missing_user_is_rejected(self):
        from app import security
        source = inspect.getsource(security.current_principal)
        assert "if user is None:" in source
        assert "role=user.role" in source, "role must come from the row, not the claim"


class TestAlertStreamIsAuthenticated:
    """
    The live alert WebSocket streamed every watchlist match — plate, camera,
    severity, case reference — to anyone who could open a socket. Active police
    case data, unauthenticated.

    It was missed by the first audit because it is declared in main.py rather
    than in a router, so the sweep over app/routers/ never saw it. Worth
    recording: an access audit is only as complete as its file list.
    """

    def test_websocket_route_takes_a_token(self):
        import inspect
        import main
        params = inspect.signature(main.alerts_websocket).parameters
        assert "token" in params, "the alert stream must authenticate"

    def test_invalid_token_is_rejected_when_auth_is_on(self):
        import inspect
        import main
        source = inspect.getsource(main.alerts_websocket)
        # Closed with a policy-violation code rather than accepted and ignored.
        assert "1008" in source
        assert "jwt.decode" in source
        assert "settings.auth_enabled" in source
