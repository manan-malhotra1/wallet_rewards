"""Unit tests for the airtime provider adapter + simulator (Epic 17 S3).

The simulator is deterministic so the recharge flow's success / failure /
pending branches are exercisable without a live MNO. Outcome rules:
  - `provider_config["force_outcome"]` wins if set;
  - else the msisdn suffix decides ('...0001' fail, '...0002' pending, else success).
"""

from __future__ import annotations

import pytest

from app.modules.airtime.provider import (
    PROVIDER_OUTCOME_FAILED,
    PROVIDER_OUTCOME_PENDING,
    PROVIDER_OUTCOME_SUCCESS,
    ProvisionRequest,
    SimulatorProvider,
    get_provider,
)
from app.shared.models import MERCHANT_MODE_LIVE, MERCHANT_MODE_SIMULATOR


def _req(msisdn: str, **config: object) -> ProvisionRequest:
    return ProvisionRequest(
        recharge_id="rc-1",
        msisdn=msisdn,
        network="MTN",
        amount="10.00",
        currency="ZAR",
        provider_config=dict(config),
    )


@pytest.mark.asyncio
async def test_simulator_default_msisdn_succeeds_with_reference() -> None:
    result = await SimulatorProvider().provision(_req("+27825551234"))
    assert result.outcome == PROVIDER_OUTCOME_SUCCESS
    assert result.provider_reference is not None
    assert result.failure_reason is None


@pytest.mark.asyncio
async def test_simulator_failed_suffix_returns_failure_no_reference() -> None:
    result = await SimulatorProvider().provision(_req("+27820000001"))
    assert result.outcome == PROVIDER_OUTCOME_FAILED
    assert result.failure_reason is not None
    assert result.provider_reference is None


@pytest.mark.asyncio
async def test_simulator_pending_suffix_returns_pending() -> None:
    result = await SimulatorProvider().provision(_req("+27820000002"))
    assert result.outcome == PROVIDER_OUTCOME_PENDING
    assert result.provider_reference is None


@pytest.mark.asyncio
async def test_force_outcome_overrides_msisdn_rule() -> None:
    # msisdn would otherwise succeed, but the forced outcome wins.
    result = await SimulatorProvider().provision(_req("+27825551234", force_outcome="failed"))
    assert result.outcome == PROVIDER_OUTCOME_FAILED


def test_get_provider_returns_simulator_for_simulator_mode() -> None:
    assert isinstance(get_provider(MERCHANT_MODE_SIMULATOR), SimulatorProvider)


def test_get_provider_rejects_unwired_live_mode() -> None:
    # 'live' has no real adapter wired in v1 — fail loudly, never silently
    # fall back to the simulator for real money.
    with pytest.raises(NotImplementedError):
        get_provider(MERCHANT_MODE_LIVE)
