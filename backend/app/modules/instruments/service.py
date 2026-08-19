"""Instruments catalog service-layer logic.

Owns CRUD over the `instruments` table. On create, optionally backfills
one account per existing tenant user so the new instrument is spendable
immediately (mirrors the operator UX expectation that flipping on a new
currency "shows up" in every user wallet, not just future signups).
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.instruments.schemas import (
    InstrumentCreateRequest,
    InstrumentUpdateRequest,
)
from app.shared.exceptions import (
    InstrumentCodeAlreadyExists,
    InstrumentNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Account,
    Instrument,
    User,
)
from app.shared.tenant_mode import assert_points_scope_allowed

log = structlog.get_logger(__name__)


async def list_instruments(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    status: str | None = None,
) -> list[Instrument]:
    """Return non-deleted instruments for the tenant."""
    stmt = (
        select(Instrument)
        .where(
            Instrument.tenant_id == tenant_id,
            Instrument.deleted_at.is_(None),
        )
        .order_by(Instrument.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Instrument.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_instrument_by_id(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    instrument_id: uuid.UUID,
) -> Instrument:
    """Return one instrument or raise InstrumentNotFound."""
    stmt = select(Instrument).where(
        Instrument.id == instrument_id,
        Instrument.tenant_id == tenant_id,
        Instrument.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    instrument = result.scalar_one_or_none()
    if instrument is None:
        raise InstrumentNotFound()
    return instrument


async def create_instrument(
    session: AsyncSession,
    payload: InstrumentCreateRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Instrument:
    """Insert a new instrument and optionally backfill user accounts.

    Rejects a points instrument for a wallet-only tenant (422
    `points_not_available`, B6.1) — it would resurrect the points surface the
    tenant's mode excludes.

    Args:
        payload: Validated request. When `assign_to_existing_users` is
            true, accounts are created for every existing user *after*
            the instrument row commits — the account write is in the
            same transaction so partial state is impossible.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP (audit context).

    Raises:
        InstrumentCodeAlreadyExists: another live instrument has this code.

    Side effects:
        Writes an `instrument.created` audit_log row, committed atomically with
        the insert (NFR-0250). Always provisions the currency's SYSTEM accounts
        (Epic 28). May add 0..N user Account rows when backfilling.
    """
    # B6.1: no points programme, no points instrument. Checked on both
    # dimensions because either one alone would resurrect the points surface.
    await assert_points_scope_allowed(
        session,
        payload.tenant_id,
        account_type=payload.account_type,
        currency=payload.code,
    )

    instrument = Instrument(
        tenant_id=payload.tenant_id,
        code=payload.code,
        symbol=payload.symbol,
        display_name=payload.display_name,
        description=payload.description,
        account_type=payload.account_type,
    )
    session.add(instrument)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_instruments_tenant_code_alive" in str(exc.orig).lower():
            raise InstrumentCodeAlreadyExists(payload.code) from exc
        raise

    # Epic 28 S28.1: eagerly provision the currency's SYSTEM accounts so it
    # shows up complete on the System Wallets page instead of waiting for the
    # first transaction to lazily create them. Same transaction as the insert.
    system_count = await _provision_system_accounts(
        session,
        tenant_id=payload.tenant_id,
        account_type=payload.account_type,
        currency=payload.code,
    )

    backfilled_count = 0
    if payload.assign_to_existing_users:
        backfilled_count = await _backfill_user_accounts(
            session=session,
            tenant_id=payload.tenant_id,
            account_type=payload.account_type,
            currency=payload.code,
        )

    record_audit_for_admin(
        session,
        admin,
        tenant_id=instrument.tenant_id,
        action="instrument.created",
        entity_type="instrument",
        entity_id=str(instrument.id),
        after_state={
            "code": instrument.code,
            "symbol": instrument.symbol,
            "display_name": instrument.display_name,
            "account_type": instrument.account_type,
            "status": instrument.status,
            "backfilled_accounts": backfilled_count,
            "system_accounts": system_count,
        },
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(instrument)
    log.info(
        "instrument_created",
        tenant_id=str(instrument.tenant_id),
        instrument_id=str(instrument.id),
        code=instrument.code,
        backfilled_accounts=backfilled_count,
        system_accounts=system_count,
    )
    return instrument


async def _provision_system_accounts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account_type: str,
    currency: str,
) -> int:
    """Provision the currency's SYSTEM accounts on instrument create (Epic 28).

    Reuses the existing get-or-create helpers on the money / rewards services,
    so it is idempotent by construction: re-creating an instrument for an
    already-provisioned currency (or one the lazy path already touched) adds
    nothing and never errors.

    Local imports avoid an import-time cycle — the money modules already reach
    into instrument-adjacent code lazily.

    Args:
        tenant_id: Tenant scope.
        account_type: The instrument's account_type (financial_wallet vs
            points_account). Determines which system set is provisioned.
        currency: The new instrument's code (ISO 4217 or a points code).

    Returns:
        Number of system accounts provisioned for this currency.

    Side effects:
        Adds 0..N Account rows in the caller's transaction (before its commit).
    """
    if account_type == ACCOUNT_TYPE_FINANCIAL_WALLET:
        from app.modules.payments.service import get_or_create_system_cash_inflow
        from app.modules.pricing.service import (
            get_or_create_system_commission,
            get_or_create_system_fee_account,
            get_or_create_system_tax_commission,
            get_or_create_system_tax_service,
        )

        # The 5 core money system accounts every financial currency needs.
        # DELIBERATELY EXCLUDES `operator_adjustment`: that is a treasury
        # artifact — a NAMED "Primary" bank mirror created via the Epic 18
        # bank-float flow (treasury.service.get_or_create_operator_adjustment),
        # not a generic per-currency base account. Auto-creating an unnamed one
        # here would collide with the named mirror's unique constraint.
        await get_or_create_system_cash_inflow(session, tenant_id, currency)
        await get_or_create_system_fee_account(session, tenant_id=tenant_id, currency=currency)
        await get_or_create_system_commission(session, tenant_id=tenant_id, currency=currency)
        await get_or_create_system_tax_service(session, tenant_id=tenant_id, currency=currency)
        await get_or_create_system_tax_commission(session, tenant_id=tenant_id, currency=currency)
        return 5

    if account_type == ACCOUNT_TYPE_POINTS:
        from app.modules.rewards.service import get_or_create_system_points_issuance

        await get_or_create_system_points_issuance(session, tenant_id, currency)
        return 1

    return 0


async def _backfill_user_accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    account_type: str,
    currency: str,
) -> int:
    """Create one account per tenant user that doesn't yet have one for this instrument.

    Idempotent: pre-existing (user, account_type, currency) tuples are
    skipped, so re-running the backfill doesn't duplicate rows.

    Returns:
        Number of new Account rows inserted.
    """
    # Find users who don't yet have an account of this (type, currency).
    users_stmt = select(User.id).where(
        User.tenant_id == tenant_id,
        ~User.id.in_(
            select(Account.user_id).where(
                Account.tenant_id == tenant_id,
                Account.account_type == account_type,
                Account.currency == currency,
                Account.user_id.is_not(None),
            )
        ),
    )
    user_ids = (await session.execute(users_stmt)).scalars().all()
    for user_id in user_ids:
        session.add(
            Account(
                tenant_id=tenant_id,
                user_id=user_id,
                account_type=account_type,
                currency=currency,
            )
        )
    return len(user_ids)


async def update_instrument(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    instrument_id: uuid.UUID,
    payload: InstrumentUpdateRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Instrument:
    """Apply symbol / display_name / description / status edits.

    Code and account_type are intentionally immutable.

    Side effects:
        Writes an `instrument.updated` audit_log row (before/after snapshot),
        committed atomically with the change (NFR-0250).
    """
    instrument = await get_instrument_by_id(session, tenant_id, instrument_id)
    before = {
        "symbol": instrument.symbol,
        "display_name": instrument.display_name,
        "status": instrument.status,
    }

    if payload.symbol is not None:
        instrument.symbol = payload.symbol
    if payload.display_name is not None:
        instrument.display_name = payload.display_name
    if payload.description is not None:
        instrument.description = payload.description
    if payload.status is not None:
        instrument.status = payload.status

    record_audit_for_admin(
        session,
        admin,
        tenant_id=instrument.tenant_id,
        action="instrument.updated",
        entity_type="instrument",
        entity_id=str(instrument.id),
        before_state=before,
        after_state={
            "symbol": instrument.symbol,
            "display_name": instrument.display_name,
            "status": instrument.status,
        },
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(instrument)
    log.info(
        "instrument_updated",
        tenant_id=str(instrument.tenant_id),
        instrument_id=str(instrument.id),
        before=before,
        after={
            "symbol": instrument.symbol,
            "display_name": instrument.display_name,
            "status": instrument.status,
        },
    )
    return instrument


async def soft_delete_instrument(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    instrument_id: uuid.UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Instrument:
    """Mark the instrument deleted_at=now(). Existing accounts are not touched.

    Side effects:
        Writes an `instrument.deleted` audit_log row (before-state snapshot),
        committed atomically with the soft-delete (NFR-0250).
    """
    instrument = await get_instrument_by_id(session, tenant_id, instrument_id)
    before = {
        "code": instrument.code,
        "symbol": instrument.symbol,
        "display_name": instrument.display_name,
        "status": instrument.status,
    }
    instrument.deleted_at = datetime.now(UTC)
    record_audit_for_admin(
        session,
        admin,
        tenant_id=instrument.tenant_id,
        action="instrument.deleted",
        entity_type="instrument",
        entity_id=str(instrument.id),
        before_state=before,
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(instrument)
    log.info(
        "instrument_deleted",
        tenant_id=str(instrument.tenant_id),
        instrument_id=str(instrument.id),
        code=instrument.code,
    )
    return instrument
