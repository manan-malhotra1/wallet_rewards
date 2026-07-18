"""Step-up service — threshold lookup, PIN re-verify, admin CRUD.

The hot path is `enforce_step_up` — one query, one bcrypt verify when
the threshold is exceeded, otherwise a no-op. Callers (P2P, redemption)
invoke it inside their orchestration sequence BEFORE any ledger write.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hashing
from app.auth.lockout import is_locked, register_failure, reset_failures
from app.auth.principals import AdminPrincipal, UserPrincipal
from app.modules.audit.service import record_audit_for_admin, record_audit_for_user
from app.modules.step_up.schemas import (
    StepUpPolicyCreateRequest,
    StepUpPolicyOut,
)
from app.shared.exceptions import (
    AppHTTPException,
    InvalidStepUpPin,
    StepUpPolicyNotFound,
    StepUpRequired,
    TenantNotFound,
)
from app.shared.models import StepUpPolicy, Tenant, User

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


# -----------------------------------------------------------------------------
# Hot path
# -----------------------------------------------------------------------------


async def enforce_step_up(
    session: AsyncSession,
    *,
    principal: UserPrincipal,
    transaction_type: str,
    currency: str,
    amount: Decimal,
    pin: str | None,
    ip_address: str | None = None,
) -> None:
    """Enforce a PIN step-up on a user-initiated transaction.

    Sequence (FAIL-CLOSED — secure by default):
      1. Look up the policy for (principal.tenant_id, txn_type, currency).
      2. ONLY skip the PIN when a policy EXISTS and amount <= its threshold.
         A missing policy does NOT skip step-up — it requires a PIN (a missing
         security config must never silently weaken the control, mirroring the
         invariant-#12 fail-closed stance for pricing/limits).
      3. PIN required + none supplied → raise StepUpRequired.
      4. PIN supplied → bcrypt-verify against `users.pin_hash`. Wrong
         PIN bumps the lockout counter (shared with login) and raises
         InvalidStepUpPin.
      5. Correct PIN → resets the lockout counter, writes a `pin.step_up_ok`
         audit row, returns.

    Args:
        session: Async DB session (no commit performed here — caller commits
            as part of the txn it's protecting).
        principal: Authenticated user from the session token.
        transaction_type: Matches the policy scope ("p2p", "redemption").
        currency: Matches the policy scope.
        amount: The amount being moved. Must already be a Decimal.
        pin: Plain-text PIN from the request body. None means the client
            didn't supply one — first prompt path.
        ip_address: Caller IP for the audit row.

    Raises:
        StepUpRequired (401): policy says PIN needed but caller didn't send one.
        InvalidStepUpPin (401): PIN supplied but didn't verify.
        AppHTTPException (401, user_locked_out): user is in the lockout
            window from prior PIN failures.
    """
    policy_q = await session.execute(
        select(StepUpPolicy).where(
            StepUpPolicy.tenant_id == principal.tenant_id,
            StepUpPolicy.transaction_type == transaction_type,
            StepUpPolicy.currency == currency,
        )
    )
    policy = policy_q.scalar_one_or_none()
    # FAIL-CLOSED: only a configured policy whose threshold the amount does not
    # exceed lets the session token stand alone. No policy → PIN required.
    if policy is not None and amount <= Decimal(str(policy.threshold_amount)):
        return  # Below the configured threshold → session token is sufficient.

    # `threshold` is only meaningful for the StepUpRequired hint; with no policy
    # there is no threshold, so report 0 ("any amount requires a PIN").
    threshold = Decimal(str(policy.threshold_amount)) if policy is not None else Decimal("0")

    if pin is None:
        raise StepUpRequired(
            transaction_type=transaction_type,
            threshold=str(threshold),
            currency=currency,
        )

    # Lockout gate — same UUID-keyed counter as the login path so failed
    # step-ups contribute to the 5-fail / 30-min lockout (NFR-0190).
    if await is_locked(principal.id):
        raise AppHTTPException(
            401,
            "user_locked_out",
            "Too many failed PIN attempts. Try again later.",
        )

    # Load the bcrypt hash. Selecting only the column keeps this cheap
    # and avoids loading the relationships graph.
    pin_hash_q = await session.execute(select(User.pin_hash).where(User.id == principal.id))
    pin_hash = pin_hash_q.scalar_one_or_none()
    if not pin_hash or not hashing.verify_pin(pin, pin_hash):
        await register_failure(principal.id)
        # Audit the failed attempt — never the PIN itself (NFR-0170).
        record_audit_for_user(
            session,
            principal,
            action="pin.step_up_failed",
            entity_type="user",
            entity_id=str(principal.id),
            after_state={
                "transaction_type": transaction_type,
                "amount": str(amount),
                "currency": currency,
            },
            ip_address=ip_address,
        )
        raise InvalidStepUpPin()

    await reset_failures(principal.id)
    record_audit_for_user(
        session,
        principal,
        action="pin.step_up_ok",
        entity_type="user",
        entity_id=str(principal.id),
        after_state={
            "transaction_type": transaction_type,
            "amount": str(amount),
            "currency": currency,
            "threshold": str(threshold),
        },
        ip_address=ip_address,
    )


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


async def create_policy(
    session: AsyncSession,
    request: StepUpPolicyCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> StepUpPolicy:
    """Create a step-up policy. 409 on the unique-index collision."""
    await _assert_tenant_exists(session, request.tenant_id)

    policy = StepUpPolicy(
        tenant_id=request.tenant_id,
        transaction_type=request.transaction_type,
        currency=request.currency.upper(),
        threshold_amount=request.threshold_amount,
    )
    session.add(policy)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "step_up_policy_exists",
            "A step-up policy already exists for this scope.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="step_up_policy.created",
            entity_type="step_up_policy",
            entity_id=str(policy.id),
            after_state={
                "transaction_type": policy.transaction_type,
                "currency": policy.currency,
                "threshold_amount": str(policy.threshold_amount),
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(policy)
    return policy


async def list_policies_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[StepUpPolicyOut]:
    """Return every step-up policy in the tenant — newest first."""
    result = await session.execute(
        select(StepUpPolicy)
        .where(StepUpPolicy.tenant_id == tenant_id)
        .order_by(StepUpPolicy.created_at.desc())
    )
    return [StepUpPolicyOut.model_validate(p) for p in result.scalars().all()]


async def delete_policy(
    session: AsyncSession,
    policy_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a policy. Tenant-scoped — cross-tenant deletes return 404."""
    result = await session.execute(
        select(StepUpPolicy).where(
            StepUpPolicy.id == policy_id, StepUpPolicy.tenant_id == tenant_id
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise StepUpPolicyNotFound()

    before = {
        "transaction_type": policy.transaction_type,
        "currency": policy.currency,
        "threshold_amount": str(policy.threshold_amount),
    }
    await session.delete(policy)

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="step_up_policy.deleted",
            entity_type="step_up_policy",
            entity_id=str(policy_id),
            before_state=before,
            ip_address=ip_address,
        )

    await session.commit()
