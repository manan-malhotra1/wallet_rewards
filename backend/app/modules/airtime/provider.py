"""Airtime provider adapter + simulator (Epic 17 S3).

The recharge flow calls a provider AFTER the funds are reserved and committed
(NFR-0130). v1 ships a `SimulatorProvider` so the whole ledger + callback flow
is exercisable without a live MNO integration; a real `httpx`-backed adapter
slots in behind the same `AirtimeProvider` protocol later.

The simulator's outcome is deterministic so tests + the seeded merchant can
drive success / failure / pending paths:
  - ``provider_config["force_outcome"]`` ("success" | "failed" | "pending")
    wins if set;
  - else the msisdn suffix decides: ``...0001`` -> failed, ``...0002`` ->
    pending, anything else -> success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from app.shared.models import MERCHANT_MODE_SIMULATOR

# Provider provisioning outcomes. Distinct from the AirtimeRecharge status —
# the service maps success -> COMPLETED, failed -> REVERSED (refund), pending
# -> stays PENDING (resolved later by callback / reconciliation).
PROVIDER_OUTCOME_SUCCESS = "success"
PROVIDER_OUTCOME_FAILED = "failed"
PROVIDER_OUTCOME_PENDING = "pending"

# Simulator magic MSISDN suffixes — test numbers that force an outcome.
_SIM_SUFFIX_FAILED = "0001"
_SIM_SUFFIX_PENDING = "0002"


@dataclass(frozen=True)
class ProvisionRequest:
    """Everything a provider needs to attempt an airtime recharge.

    `amount` is a stringified Decimal — provider APIs take money as strings to
    avoid float drift, and it keeps this seam serialisation-friendly.
    """

    recharge_id: str
    msisdn: str
    network: str
    amount: str
    currency: str
    provider_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisionResult:
    """A provider's answer: terminal (success / failed) or pending."""

    outcome: str
    provider_reference: str | None = None
    failure_reason: str | None = None


class AirtimeProvider(Protocol):
    """The seam a real MNO / aggregator adapter implements."""

    async def provision(self, request: ProvisionRequest) -> ProvisionResult:
        """Attempt to vend airtime; return the (possibly pending) outcome."""
        ...


class SimulatorProvider:
    """Deterministic in-process provider for v1 / tests (no network call)."""

    async def provision(self, request: ProvisionRequest) -> ProvisionResult:
        """Return a deterministic outcome (rules in the module docstring)."""
        forced = request.provider_config.get("force_outcome")
        outcome = forced or self._outcome_for_msisdn(request.msisdn)

        if outcome == PROVIDER_OUTCOME_FAILED:
            return ProvisionResult(
                outcome=PROVIDER_OUTCOME_FAILED,
                failure_reason="simulated_provider_failure",
            )
        if outcome == PROVIDER_OUTCOME_PENDING:
            # Accepted but not yet vended — resolved later by the callback.
            return ProvisionResult(outcome=PROVIDER_OUTCOME_PENDING)
        return ProvisionResult(
            outcome=PROVIDER_OUTCOME_SUCCESS,
            provider_reference=f"SIM-{uuid4().hex[:12].upper()}",
        )

    @staticmethod
    def _outcome_for_msisdn(msisdn: str) -> str:
        """Map a test-MSISDN suffix to an outcome; default success."""
        digits = msisdn.replace(" ", "")
        if digits.endswith(_SIM_SUFFIX_FAILED):
            return PROVIDER_OUTCOME_FAILED
        if digits.endswith(_SIM_SUFFIX_PENDING):
            return PROVIDER_OUTCOME_PENDING
        return PROVIDER_OUTCOME_SUCCESS


def get_provider(mode: str) -> AirtimeProvider:
    """Return the provider adapter for a merchant's provisioning `mode`.

    v1 wires only the simulator. 'live' has no real adapter yet, so it raises
    rather than silently simulating real money (the httpx-backed adapter lands
    in a follow-up behind this same seam).

    Raises:
        NotImplementedError: `mode` has no adapter wired (e.g. 'live' in v1).
    """
    if mode == MERCHANT_MODE_SIMULATOR:
        return SimulatorProvider()
    raise NotImplementedError(f"No airtime provider adapter wired for mode {mode!r}")
