"""Instruments catalog service-layer logic.

Owns CRUD over the `instruments` table. On create, optionally backfills
one account per existing tenant user so the new instrument is spendable
immediately (mirrors the operator UX expectation that flipping on a new
currency "shows up" in every user wallet, not just future signups).
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.instruments.schemas import (
    InstrumentCreateRequest,
    InstrumentUpdateRequest,
)
from app.shared.exceptions import (
    InstrumentCodeAlreadyExists,
    InstrumentNotFound,
)
from app.shared.models import Account, Instrument, User

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
) -> Instrument:
    """Insert a new instrument and optionally backfill user accounts.

    Args:
        payload: Validated request. When `assign_to_existing_users` is
            true, accounts are created for every existing user *after*
            the instrument row commits — the account write is in the
            same transaction so partial state is impossible.

    Raises:
        InstrumentCodeAlreadyExists: another live instrument has this code.

    Side effects:
        Commits the session. May add 0..N Account rows when backfilling.
    """
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

    backfilled_count = 0
    if payload.assign_to_existing_users:
        backfilled_count = await _backfill_user_accounts(
            session=session,
            tenant_id=payload.tenant_id,
            account_type=payload.account_type,
            currency=payload.code,
        )

    await session.commit()
    await session.refresh(instrument)
    log.info(
        "instrument_created",
        tenant_id=str(instrument.tenant_id),
        instrument_id=str(instrument.id),
        code=instrument.code,
        backfilled_accounts=backfilled_count,
    )
    return instrument


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
) -> Instrument:
    """Apply symbol / display_name / description / status edits.

    Code and account_type are intentionally immutable. Side effects:
    commits the session.
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
) -> Instrument:
    """Mark the instrument deleted_at=now(). Existing accounts are not touched."""
    instrument = await get_instrument_by_id(session, tenant_id, instrument_id)
    instrument.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(instrument)
    log.info(
        "instrument_deleted",
        tenant_id=str(instrument.tenant_id),
        instrument_id=str(instrument.id),
        code=instrument.code,
    )
    return instrument
