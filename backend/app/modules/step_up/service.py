"""Step-up service — threshold lookup, PIN re-verify, admin CRUD.

The hot path is `enforce_step_up` — one query, one bcrypt verify when
the threshold is exceeded, otherwise a no-op. Callers (P2P, redemption)
invoke it inside their orchestration sequence BEFORE any ledger write.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, select
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
# Admin CRUD — write paths flow through config-governance maker-checker
# -----------------------------------------------------------------------------
#
# Step-up policy WRITES (create / update / delete) are no longer exposed as
# direct routes: they are proposed and approved via `config_requests` (config
# type "step_up"), exactly like pricing / limit / commission / tax. The apply
# dispatch there calls `create_policy` (create), `replace_step_up_policy_for_scope`
# (update), and `delete_step_up_policy_for_scope` (delete). Only the read path
# (`list_policies_for_tenant`) and the hot path (`enforce_step_up`) stay exposed.


def _new_step_up_policy(request: StepUpPolicyCreateRequest) -> StepUpPolicy:
    """Build a StepUpPolicy ORM row from a validated create request (no DB I/O).

    Shared by `create_policy` and `replace_step_up_policy_for_scope`.
    """
    return StepUpPolicy(
        tenant_id=request.tenant_id,
        transaction_type=request.transaction_type,
        currency=request.currency.upper(),
        threshold_amount=request.threshold_amount,
    )


def _step_up_scope_filter(
    *, tenant_id: UUID, transaction_type: str, currency: str
) -> list[ColumnElement[bool]]:
    """Column predicates selecting the step-up row in one scope.

    Shared by `replace_step_up_policy_for_scope` and
    `delete_step_up_policy_for_scope`. Scope = (tenant, transaction_type,
    currency) — a single row. `currency` is upper-cased.
    """
    return [
        StepUpPolicy.tenant_id == tenant_id,
        StepUpPolicy.transaction_type == transaction_type,
        StepUpPolicy.currency == currency.upper(),
    ]


def _step_up_state(policy: StepUpPolicy) -> dict[str, object]:
    """Serialise a step-up policy for an audit snapshot."""
    return {
        "transaction_type": policy.transaction_type,
        "currency": policy.currency,
        "threshold_amount": str(policy.threshold_amount),
    }


async def create_policy(
    session: AsyncSession,
    request: StepUpPolicyCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> StepUpPolicy:
    """Create a step-up policy. 409 on the unique-index collision.

    Invoked by the config-governance apply dispatch on approval of a `step_up`
    `create` request (never a direct route). Commits once; writes a
    `step_up_policy.created` audit row.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    policy = _new_step_up_policy(request)
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
            after_state=_step_up_state(policy),
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(policy)
    return policy


async def replace_step_up_policy_for_scope(
    session: AsyncSession,
    requests: list[StepUpPolicyCreateRequest],
    *,
    target_config_id: UUID | None = None,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Atomically replace the step-up policy for a scope with a new one.

    Scope = (tenant, transaction_type, currency) — a single row. The existing
    row is deleted and the new one inserted in ONE transaction — DELETE flushed
    before INSERT so the unique index never trips — committed once. A mid-apply
    failure rolls the whole replace back. Invoked by the config-governance apply
    dispatch on approval of a `step_up` `update` request.

    Args:
        requests: A one-element list holding the validated new policy.
        target_config_id: The live row the maker edited (audit traceability).

    Side effects:
        Deletes + inserts a step_up_policies row; appends one
        `step_up_policy.updated` audit row. Commits once.
    """
    first = requests[0]
    scope = _step_up_scope_filter(
        tenant_id=first.tenant_id,
        transaction_type=first.transaction_type,
        currency=first.currency,
    )
    existing = list((await session.execute(select(StepUpPolicy).where(*scope))).scalars().all())
    before = [_step_up_state(p) for p in existing]
    for row in existing:
        await session.delete(row)
    await session.flush()  # DELETE must precede the INSERT (unique index).

    new_policy = _new_step_up_policy(first)
    session.add(new_policy)
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=first.tenant_id,
            action="step_up_policy.updated",
            entity_type="step_up_policy",
            entity_id=str(target_config_id or new_policy.id),
            before_state={"replaced": before},
            after_state=_step_up_state(new_policy),
            ip_address=ip_address,
        )
    await session.commit()


async def list_policies_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[StepUpPolicyOut]:
    """Return every step-up policy in the tenant — newest first."""
    result = await session.execute(
        select(StepUpPolicy)
        .where(StepUpPolicy.tenant_id == tenant_id)
        .order_by(StepUpPolicy.created_at.desc())
    )
    return [StepUpPolicyOut.model_validate(p) for p in result.scalars().all()]


async def delete_step_up_policy_for_scope(
    session: AsyncSession,
    target: StepUpPolicy,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete every step-up row sharing `target`'s scope, in one commit.

    Scope = (tenant, transaction_type, currency) — a single row, so this removes
    exactly that policy. The removal plus one `step_up_policy.deleted` audit row
    (before_state summarising the removed row) land in ONE transaction, so a
    mid-delete failure rolls back. Invoked by the config-governance apply
    dispatch on approval of a `step_up` `delete` request.

    Args:
        target: The live row whose scope is removed — already loaded and
            tenant-checked by the caller; its id anchors the audit entry.

    Side effects:
        Deletes a step_up_policies row; appends one `step_up_policy.deleted`
        audit row. Commits once.
    """
    scope = _step_up_scope_filter(
        tenant_id=target.tenant_id,
        transaction_type=target.transaction_type,
        currency=target.currency,
    )
    existing = list((await session.execute(select(StepUpPolicy).where(*scope))).scalars().all())
    before = [_step_up_state(p) for p in existing]
    for row in existing:
        await session.delete(row)
    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=target.tenant_id,
            action="step_up_policy.deleted",
            entity_type="step_up_policy",
            entity_id=str(target.id),
            before_state={"deleted": before},
            ip_address=ip_address,
        )
    await session.commit()
