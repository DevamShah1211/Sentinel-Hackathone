"""
Tests for the VAHAN adapter.

The point of these is that the *contract* is testable even though the live
endpoint is unreachable — which is the whole argument for contract-first
integration. They also pin the safety properties: a mock record must always
identify itself as a mock, and must never contain a full chassis or engine number.
"""
from __future__ import annotations

import pytest

from app.adapters.vahan import (
    MockVahanClient,
    LiveVahanClient,
    VahanSettings,
    VehicleNotFound,
    VahanLookupError,
    get_vahan_client,
)


@pytest.fixture
def client() -> MockVahanClient:
    return MockVahanClient()


class TestMockLookup:
    @pytest.mark.asyncio
    async def test_returns_a_populated_record(self, client: MockVahanClient) -> None:
        record = await client.lookup("GJ01AB1234")
        assert record.registration_number == "GJ01AB1234"
        assert record.owner_name
        assert record.maker_model
        assert record.registering_authority

    @pytest.mark.asyncio
    async def test_is_deterministic(self, client: MockVahanClient) -> None:
        # A route reconstruction shows the same vehicle at several sightings; the
        # details must not change between lookups.
        first = await client.lookup("GJ01AB1234")
        second = await client.lookup("GJ01AB1234")
        assert first.owner_name == second.owner_name
        assert first.maker_model == second.maker_model
        assert first.chassis_number_masked == second.chassis_number_masked

    @pytest.mark.asyncio
    async def test_different_plates_differ(self, client: MockVahanClient) -> None:
        a = await client.lookup("GJ01AB1234")
        b = await client.lookup("MH12DE1433")
        assert (a.owner_name, a.maker_model) != (b.owner_name, b.maker_model)

    @pytest.mark.asyncio
    async def test_normalises_separators_and_case(self, client: MockVahanClient) -> None:
        spaced = await client.lookup("gj-01 ab 1234")
        plain = await client.lookup("GJ01AB1234")
        assert spaced.registration_number == "GJ01AB1234"
        assert spaced.owner_name == plain.owner_name

    @pytest.mark.asyncio
    async def test_rejects_an_implausible_registration(self, client: MockVahanClient) -> None:
        with pytest.raises(VehicleNotFound):
            await client.lookup("XY1")

    @pytest.mark.asyncio
    async def test_maps_gujarat_rto_codes(self, client: MockVahanClient) -> None:
        record = await client.lookup("GJ18CD5678")
        assert "Gandhinagar" in record.registering_authority

    @pytest.mark.asyncio
    async def test_blacklist_is_reported(self) -> None:
        flagged = MockVahanClient(blacklisted={"GJ01AB1234"})
        record = await flagged.lookup("GJ01AB1234")
        assert record.is_blacklisted
        assert record.blacklist_reason

        clean = await flagged.lookup("GJ05JV7219")
        assert not clean.is_blacklisted


class TestMockSafety:
    """A synthetic record must never be mistakable for an authoritative one."""

    @pytest.mark.asyncio
    async def test_record_declares_itself_a_mock(self, client: MockVahanClient) -> None:
        record = await client.lookup("GJ01AB1234")
        assert record.source == "mock"
        assert record.is_mock

    @pytest.mark.asyncio
    async def test_identifiers_are_masked(self, client: MockVahanClient) -> None:
        # Never synthesise a complete chassis or engine number, even fictionally.
        record = await client.lookup("GJ01AB1234")
        assert "*" in record.chassis_number_masked
        assert "*" in record.engine_number_masked


class TestLiveClient:
    @pytest.mark.asyncio
    async def test_refuses_without_credentials(self) -> None:
        live = LiveVahanClient(VahanSettings())
        with pytest.raises(VahanLookupError, match="not configured"):
            await live.lookup("GJ01AB1234")

    def test_settings_report_unconfigured_by_default(self) -> None:
        assert not VahanSettings().configured
        assert VahanSettings(base_url="https://example.gov.in", api_key="k").configured


class TestFactory:
    def test_defaults_to_the_mock(self) -> None:
        assert isinstance(get_vahan_client(), MockVahanClient)
