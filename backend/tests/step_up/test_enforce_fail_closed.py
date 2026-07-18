"""Direct unit tests for `enforce_step_up` — the FAIL-CLOSED contract.

These bypass the HTTP layer and call `enforce_step_up` against a real DB
session so the policy lookup, the fail-closed branch, and the real bcrypt
verify all execute. They pin the security-critical invariant introduced when
step-up flipped from fail-OPEN to fail-CLOSED: a MISSING policy for the
(tenant, transaction_type, currency) scope must REQUIRE a PIN — never wave the
caller through — mirroring the invariant-#12 fail-closed stance for
pricing/limits. A configured policy whose threshold the amount does not exceed
must still skip the PIN (the below-threshold regression guard).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_pin
from app.auth.principals import UserPrincipal
from app.modules.step_up.service import enforce_step_up
from app.shared.exceptions import InvalidStepUpPin, StepUpRequired
from app.shared.models import StepUpPolicy, Tenant, User

_PIN = "1234"


async def _make_user_with_pin(session: AsyncSession, tenant: Tenant, pin: str = _PIN) -> User:
    """Create a user carrying a bcrypt PIN hash so the verify path is real."""
    user = User(tenant_id=tenant.id, pin_hash=hash_pin(pin))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def _principal(user: User) -> UserPrincipal:
    """Build the session principal the hot path receives from the token."""
    return UserPrincipal(id=user.id, tenant_id=user.tenant_id, channel="mobile")


async def _seed_policy(
    session: AsyncSession, tenant: Tenant, *, threshold: str, txn_type: str = "p2p"
) -> None:
    """Insert a step-up policy for (tenant, txn_type, ZAR)."""
    session.add(
        StepUpPolicy(
            tenant_id=tenant.id,
            transaction_type=txn_type,
            currency="ZAR",
            threshold_amount=Decimal(threshold),
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_no_policy_no_pin_raises_step_up_required(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """FAIL-CLOSED: no policy for the scope + no PIN → StepUpRequired (any amount)."""
    user = await _make_user_with_pin(db_session, test_tenant)

    with pytest.raises(StepUpRequired) as exc:
        await enforce_step_up(
            db_session,
            principal=_principal(user),
            transaction_type="p2p",
            currency="ZAR",
            amount=Decimal("1"),  # tiny amount still requires a PIN with no policy
            pin=None,
        )
    assert exc.value.error_code == "step_up_required"
    # The reported threshold is 0 when there is no policy ("any amount → PIN").
    assert "ZAR 0" in exc.value.message


@pytest.mark.asyncio
async def test_no_policy_correct_pin_succeeds(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """FAIL-CLOSED companion: no policy + the correct PIN → no raise (returns None)."""
    user = await _make_user_with_pin(db_session, test_tenant)

    result = await enforce_step_up(
        db_session,
        principal=_principal(user),
        transaction_type="p2p",
        currency="ZAR",
        amount=Decimal("9000"),
        pin=_PIN,
    )
    assert result is None


@pytest.mark.asyncio
async def test_no_policy_wrong_pin_raises_invalid(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """No policy + a wrong PIN → InvalidStepUpPin (fail-closed still verifies)."""
    user = await _make_user_with_pin(db_session, test_tenant)

    with pytest.raises(InvalidStepUpPin):
        await enforce_step_up(
            db_session,
            principal=_principal(user),
            transaction_type="p2p",
            currency="ZAR",
            amount=Decimal("50"),
            pin="9999",
        )


@pytest.mark.asyncio
async def test_policy_below_threshold_skips_pin(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Regression guard: WITH a policy, amount <= threshold still skips the PIN.

    The fail-closed flip must NOT have broken the below-threshold path — a
    configured R200 threshold lets a R100 transfer through with no PIN.
    """
    user = await _make_user_with_pin(db_session, test_tenant)
    await _seed_policy(db_session, test_tenant, threshold="200")

    result = await enforce_step_up(
        db_session,
        principal=_principal(user),
        transaction_type="p2p",
        currency="ZAR",
        amount=Decimal("100"),
        pin=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_policy_above_threshold_requires_pin(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """WITH a policy, an amount over the threshold + no PIN → StepUpRequired.

    The reported hint carries the CONFIGURED threshold (200), not 0.
    """
    user = await _make_user_with_pin(db_session, test_tenant)
    await _seed_policy(db_session, test_tenant, threshold="200")

    with pytest.raises(StepUpRequired) as exc:
        await enforce_step_up(
            db_session,
            principal=_principal(user),
            transaction_type="p2p",
            currency="ZAR",
            amount=Decimal("500"),
            pin=None,
        )
    assert "ZAR 200" in exc.value.message
