"""Treasury service — admin view + control of system wallets.

The model:
  - System wallets = `accounts` rows where `user_id IS NULL`.
  - `operator_adjustment` (one per tenant + currency) is the counter-leg
    for admin fund/withdraw on the system float. Its balance tracks net
    external cash that has flowed in/out via bank wires.
  - `fund_user()` reuses the existing `fund()` service (DEBIT
    system_cash_inflow, CREDIT user_wallet).

Every action below writes an `audit_log` row with the admin's reason.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_admin
from app.modules.identity.schemas import IdentifierType
from app.modules.identity.service import resolve_identifier
from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.payments.service import fund
from app.modules.treasury.schemas import (
    AdjustSystemWalletResponse,
    FundUserResponse,
    SystemWalletOut,
    SystemWalletTransactionOut,
    WithdrawFromUserResponse,
)
from app.shared.exceptions import (
    AccountNotFound,
    AppHTTPException,
    BankMirrorNameAlreadyExists,
    CurrencyMismatch,
    InsufficientFunds,
    NothingToWithdraw,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

# The name given to the default/back-compat bank mirror. The single mirror that
# existed before named mirrors (Epic 26) is backfilled to this name, and the
# lazy get-or-create path uses it so old callers keep landing on one stable row.
BANK_MIRROR_PRIMARY_NAME = "Primary"


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


def _to_system_wallet_out(account: Account, balance: Decimal) -> SystemWalletOut:
    """Project an Account + its derived balance into the API response shape."""
    return SystemWalletOut(
        id=account.id,
        tenant_id=account.tenant_id,
        account_type=account.account_type,
        name=account.name,
        currency=account.currency,
        status=account.status,
        balance=balance,
        created_at=account.created_at,
    )


async def project_system_wallet(session: AsyncSession, account: Account) -> SystemWalletOut:
    """Serialize a system account with its freshly derived balance.

    Router-facing helper so the create / rename endpoints return the same shape
    as the list endpoint without hand-rolling balance derivation in the router.
    """
    balance, _reserved = await derive_balance(session, account.id)
    return _to_system_wallet_out(account, balance)


async def get_or_create_operator_adjustment(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> Account:
    """Fetch-or-create the "Primary" bank mirror for a (tenant, currency).

    Back-compat / seed path only. Named bank mirrors (Epic 26) let the operator
    pick a counter-leg explicitly, but user-initiated external withdraws and the
    seed still need one stable mirror without asking a human — that is "Primary".

    Lazy so the operator doesn't have to pre-seed anything in a new tenant.

    Concurrency-safe: callers pre-create this BEFORE taking the wallet lock
    (Epic 18 S4 H-01), so two concurrent first-ever withdraws for the same
    (tenant, currency) can race the INSERT. The loser hits the
    `uq_accounts_bank_mirror` unique constraint (on name); we roll back and
    re-read the winner's row rather than surfacing a raw IntegrityError (mirrors
    `create_account` and `post_transaction`).
    """
    currency = currency.upper()
    stmt = select(Account).where(
        Account.tenant_id == tenant_id,
        Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        Account.currency == currency,
        Account.user_id.is_(None),
        Account.name == BANK_MIRROR_PRIMARY_NAME,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    account = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency=currency,
        name=BANK_MIRROR_PRIMARY_NAME,
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent caller created it first — roll back our INSERT and
        # return the committed row.
        await session.rollback()
        return (await session.execute(stmt)).scalar_one()
    await session.refresh(account)
    return account


async def create_bank_mirror(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    currency: str,
    name: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Account:
    """Create a new named bank mirror (operator_adjustment) for a currency.

    Bank mirrors are the counter-leg for admin withdraw + adjust; several may
    coexist per (tenant, currency), each picked explicitly by the operator.

    Args:
        name: Human-readable label, unique per (tenant, currency).

    Returns:
        The created Account.

    Raises:
        TenantNotFound: tenant_id is unknown.
        BankMirrorNameAlreadyExists: `name` is already taken in this scope
            (`uq_accounts_bank_mirror` violation).

    Side effects:
        Commits the session and writes a `treasury.create_bank_mirror` audit row.
    """
    await _assert_tenant_exists(session, tenant_id)
    currency = currency.upper()
    account = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency=currency,
        name=name,
    )
    session.add(account)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise BankMirrorNameAlreadyExists() from exc

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.create_bank_mirror",
        entity_type="account",
        entity_id=str(account.id),
        after_state={"name": name, "currency": currency},
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(account)
    return account


async def rename_bank_mirror(
    session: AsyncSession,
    *,
    account_id: UUID,
    tenant_id: UUID,
    name: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Account:
    """Rename an existing bank mirror.

    Args:
        account_id: The bank mirror to rename.
        name: New label, unique per (tenant, currency).

    Returns:
        The updated Account.

    Raises:
        AccountNotFound: no such operator_adjustment account in this tenant.
        BankMirrorNameAlreadyExists: `name` collides with another mirror.

    Side effects:
        Commits the session and writes a `treasury.rename_bank_mirror` audit row.
    """
    mirror = (
        await session.execute(
            select(Account).where(
                Account.id == account_id,
                Account.tenant_id == tenant_id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if mirror is None:
        raise AccountNotFound()

    old_name = mirror.name
    mirror.name = name
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise BankMirrorNameAlreadyExists() from exc

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.rename_bank_mirror",
        entity_type="account",
        entity_id=str(account_id),
        before_state={"name": old_name},
        after_state={"name": name},
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(mirror)
    return mirror


async def resolve_bank_mirror(
    session: AsyncSession,
    *,
    account_id: UUID,
    tenant_id: UUID,
    currency: str,
) -> Account:
    """Load and validate a caller-supplied bank mirror for a counter-leg.

    Args:
        account_id: The operator-selected bank mirror.
        currency: The action currency; must match the mirror's currency.

    Returns:
        The validated operator_adjustment Account.

    Raises:
        AccountNotFound: no such operator_adjustment in this tenant.
        CurrencyMismatch: the mirror holds a different currency.
    """
    mirror = (
        await session.execute(
            select(Account).where(
                Account.id == account_id,
                Account.tenant_id == tenant_id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if mirror is None:
        raise AccountNotFound()
    if mirror.currency != currency.upper():
        raise CurrencyMismatch()
    return mirror


async def resolve_user_financial_wallet(
    session: AsyncSession,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
    currency: str,
) -> tuple[UUID, Account]:
    """Resolve a user by identifier and return (user_id, their financial_wallet).

    Shared by the operator and external fund/withdraw paths. It can NEVER return
    a system wallet — system accounts have `user_id IS NULL`, so filtering by the
    resolved `user_id` guarantees a user-owned wallet. This is precisely why
    fund / withdraw / withdraw_all can never touch a system wallet.

    Raises:
        UserNotFound: identifier doesn't resolve in this tenant.
        AccountNotFound: the user has no financial_wallet for `currency`.
    """
    identifier_row = await resolve_identifier(
        session, tenant_id, cast(IdentifierType, identifier_type), identifier_value
    )
    user_id = identifier_row.user_id
    wallet = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one_or_none()
    if wallet is None:
        raise AccountNotFound()
    return user_id, wallet


async def resolve_withdraw_amount(
    session: AsyncSession,
    wallet: Account,
    *,
    amount: Decimal | None,
    withdraw_all: bool,
) -> Decimal:
    """Return the amount to withdraw, enforcing overdraft before any write.

    `withdraw_all` resolves to the wallet's full available balance
    (balance - reserved); otherwise the requested `amount`.

    Advisory only (invariant #11):
        This is a best-effort early error — it reads the balance WITHOUT a lock
        and may race a concurrent withdraw. The authoritative overdraft check is
        `post_transaction`'s balance guard, which locks the wallet FOR UPDATE and
        re-checks under that lock, held through the debit commit. A race that
        slips past this read is still caught there; this function just turns the
        common case into a clean early rejection.

    Raises:
        NothingToWithdraw: withdraw_all but available <= 0.
        InsufficientFunds: requested amount > available.
    """
    balance, reserved = await derive_balance(session, wallet.id)
    available = balance - reserved
    if withdraw_all:
        if available <= Decimal("0"):
            raise NothingToWithdraw()
        return available
    # The request schema guarantees a positive amount when withdraw_all is False.
    assert amount is not None
    if available < amount:
        raise InsufficientFunds()
    return amount


async def post_user_withdraw(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    wallet: Account,
    operator_adjustment: Account,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
    transaction_type: str = "withdraw",
    base_transaction_type: str = "withdraw",
) -> Transaction:
    """Post the balanced withdraw legs: DEBIT the user wallet, CREDIT the
    operator_adjustment system account (transaction_type='withdraw').

    Args:
        operator_adjustment: The counter-leg system account, resolved by the
            caller via `get_or_create_operator_adjustment`. It must already exist
            because `post_transaction` loads every entry's account up front (and
            then locks the wallet under its balance guard) — creating it lazily
            here would be a mid-flow `commit()` inside that guarded window.
        transaction_type: The RESOLVED service code to record (spec §7).
            Defaults to 'withdraw' — every existing caller (treasury's admin
            withdraw) keeps posting under plain 'withdraw' untouched. The
            partner `external_withdraw` flow is the only caller that resolves
            a derived service and passes it here.
        base_transaction_type: The BASE flow to denormalise onto the
            transaction (spec §12.1). Always 'withdraw' regardless of the
            derived code above — callers should not override this
            independently.

    The caller owns the audit row + the surrounding commit; this only appends the
    ledger transaction, which commits internally via `post_transaction`. That
    guarded commit is where the wallet FOR UPDATE lock is taken and released —
    after the debit is durably written.
    """
    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type=transaction_type,
            base_transaction_type=base_transaction_type,
            currency=currency,
            amount=amount,
            initiated_by=user_id,
            entries=[
                LedgerEntryRequest(account_id=wallet.id, entry_type="DEBIT", amount=amount),
                LedgerEntryRequest(
                    account_id=operator_adjustment.id, entry_type="CREDIT", amount=amount
                ),
            ],
        ),
    )


# -----------------------------------------------------------------------------
# Read endpoints
# -----------------------------------------------------------------------------


async def list_system_wallets(session: AsyncSession, *, tenant_id: UUID) -> list[SystemWalletOut]:
    """Return every system-owned account in the tenant with its live balance."""
    await _assert_tenant_exists(session, tenant_id)
    rows = (
        (
            await session.execute(
                select(Account)
                .where(Account.tenant_id == tenant_id, Account.user_id.is_(None))
                .order_by(Account.account_type, Account.currency, Account.name)
            )
        )
        .scalars()
        .all()
    )
    out: list[SystemWalletOut] = []
    for acct in rows:
        balance, _reserved = await derive_balance(session, acct.id)
        out.append(_to_system_wallet_out(acct, balance))
    return out


async def list_account_transactions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    limit: int = 50,
) -> list[SystemWalletTransactionOut]:
    """Return recent transactions touching a system account.

    Tenant-scoped — cross-tenant lookups return 404 (no existence leak).
    Joins ledger_entries → transactions so we can surface the entry's
    direction (DEBIT/CREDIT) for the row in the drill-down UI.
    """
    acct = (
        await session.execute(
            select(Account).where(
                Account.id == account_id,
                Account.tenant_id == tenant_id,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if acct is None:
        raise AccountNotFound()

    stmt = (
        select(Transaction, LedgerEntry)
        .join(LedgerEntry, LedgerEntry.transaction_id == Transaction.id)
        .where(LedgerEntry.account_id == account_id)
        .order_by(desc(Transaction.created_at))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        SystemWalletTransactionOut(
            transaction_id=txn.id,
            reference=txn.reference,
            transaction_type=txn.transaction_type,
            status=txn.status,
            entry_type=entry.entry_type,
            entry_amount=Decimal(str(entry.amount)),
            currency=txn.currency,
            created_at=txn.created_at,
        )
        for txn, entry in rows
    ]


# -----------------------------------------------------------------------------
# Mutating endpoints
# -----------------------------------------------------------------------------


async def fund_user(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
    amount: Decimal,
    currency: str,
    reason: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
    idempotency_key: str | None = None,
) -> FundUserResponse:
    """Admin tops up a user's wallet — wraps the existing `fund()`.

    The user is resolved from their registered identifier (phone, email,
    account_number, card_number) — operators don't have UUIDs at the
    counter. Posts the standard balanced transaction (DEBIT
    system_cash_inflow, CREDIT user_wallet) and writes a
    `treasury.fund_user` audit row with the admin's reason.

    Args:
        idempotency_key: Optional caller-supplied key. Left None for a direct
            admin fund (each is a genuinely new fund, so a fresh key is
            generated). The money-operation apply path (Epic 18) passes a
            DETERMINISTIC key derived from the request id so a re-approval or
            replay cannot double-post (invariant #2).

    Raises:
        TenantNotFound: tenant_id is unknown.
        UserNotFound: identifier doesn't resolve in this tenant.
    """
    await _assert_tenant_exists(session, tenant_id)
    identifier_row = await resolve_identifier(
        session, tenant_id, cast(IdentifierType, identifier_type), identifier_value
    )
    user_id = identifier_row.user_id

    idempotency_key = idempotency_key or f"admin-fund-{uuid4().hex}"
    txn = await fund(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        amount=amount,
        currency=currency,
        idempotency_key=idempotency_key,
    )

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.fund_user",
        entity_type="user",
        entity_id=str(user_id),
        after_state={
            "amount": str(amount),
            "currency": currency.upper(),
            "transaction_id": str(txn.id),
            "reason": reason,
            "identifier_type": identifier_type,
        },
        ip_address=ip_address,
    )
    await session.commit()

    # Re-derive the user's wallet balance for the response.
    user_wallet = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == "financial_wallet",
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one()
    new_balance, _ = await derive_balance(session, user_wallet.id)

    return FundUserResponse(
        transaction_id=txn.id,
        user_id=user_id,
        amount=amount,
        currency=currency.upper(),
        new_balance=new_balance,
    )


async def withdraw_from_user(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
    amount: Decimal | None,
    currency: str,
    bank_mirror_account_id: UUID,
    reason: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
    withdraw_all: bool = False,
    idempotency_key: str | None = None,
) -> WithdrawFromUserResponse:
    """Admin debits a user's wallet and returns the funds to the operator pool.

    The mirror of `fund_user`: DEBIT user's financial_wallet, CREDIT the
    operator-selected bank mirror (`operator_adjustment`). Both are real money
    moving back into the operator's cash float at the counter.

    Admin operations are PIN-less and fee-less: the operator's Keycloak
    session is the only authentication. The target user is identified
    by a registered identifier, not a UUID.

    Args:
        tenant_id: Tenant scope.
        identifier_type / identifier_value: Resolved to a user via
            identity.resolve_identifier — typically phone at the counter.
        amount, currency: Withdraw parameters.
        bank_mirror_account_id: The operator-selected bank mirror that receives
            the CREDIT counter-leg.
        reason: Free-text reason, persisted in the audit row.
        admin: Authenticated admin initiating the action.
        ip_address: Caller IP for the audit row.
        idempotency_key: Optional caller-supplied key; the money-operation apply
            path passes a deterministic one so replays can't double-post
            (invariant #2). None → a fresh key per direct admin withdraw.

    Returns:
        WithdrawFromUserResponse with the new wallet balance.

    Raises:
        TenantNotFound: tenant_id is unknown.
        UserNotFound: identifier doesn't resolve in this tenant.
        AccountNotFound: user has no financial_wallet for this currency, or the
            bank mirror doesn't exist in this tenant.
        CurrencyMismatch: the bank mirror holds a different currency.
        InsufficientFunds: user balance < requested amount.

    Side effects:
        Posts a balanced 2-leg transaction (transaction_type='withdraw').
        Writes a `treasury.withdraw_from_user` audit row with the reason.
        Commits the session.
    """
    await _assert_tenant_exists(session, tenant_id)
    currency = currency.upper()
    user_id, user_wallet = await resolve_user_financial_wallet(
        session, tenant_id, identifier_type, identifier_value, currency
    )
    # Resolve the operator-selected counter account up front so it exists before
    # `post_user_withdraw` posts the legs. No explicit wallet lock here:
    # `post_transaction`'s balance guard (invariant #11) locks the wallet
    # FOR UPDATE and runs the overdraft check under it, held through the debit
    # commit — so concurrent withdraws on this wallet serialise there and neither
    # can drive the balance negative.
    operator_adjustment = await resolve_bank_mirror(
        session, account_id=bank_mirror_account_id, tenant_id=tenant_id, currency=currency
    )
    final_amount = await resolve_withdraw_amount(
        session, user_wallet, amount=amount, withdraw_all=withdraw_all
    )
    txn = await post_user_withdraw(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        wallet=user_wallet,
        operator_adjustment=operator_adjustment,
        amount=final_amount,
        currency=currency,
        idempotency_key=idempotency_key or f"admin-withdraw-{uuid4().hex}",
    )

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.withdraw_from_user",
        entity_type="user",
        entity_id=str(user_id),
        after_state={
            "amount": str(final_amount),
            "currency": currency,
            "transaction_id": str(txn.id),
            "reason": reason,
            "identifier_type": identifier_type,
            "withdraw_all": withdraw_all,
            "bank_mirror_account_id": str(operator_adjustment.id),
        },
        ip_address=ip_address,
    )
    await session.commit()

    new_balance, _ = await derive_balance(session, user_wallet.id)
    return WithdrawFromUserResponse(
        transaction_id=txn.id,
        user_id=user_id,
        amount=final_amount,
        currency=currency,
        new_balance=new_balance,
    )


async def adjust_system_wallet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    amount: Decimal,  # signed
    bank_mirror_account_id: UUID,
    reason: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
    idempotency_key: str | None = None,
) -> AdjustSystemWalletResponse:
    """Fund (positive amount) or withdraw (negative) a system wallet.

    Posts a balanced transaction with the operator-selected bank mirror
    (`operator_adjustment`) as the counter-leg.

      amount > 0  (fund the float):
        DEBIT  operator_adjustment   |amount|
        CREDIT target_system_wallet  |amount|

      amount < 0  (withdraw from the float):
        DEBIT  target_system_wallet  |amount|
        CREDIT operator_adjustment   |amount|

    Tenant-scoped — cross-tenant account_id returns 404. The target
    must be a system-owned account (user_id IS NULL). Adjusting a
    user wallet via this surface is rejected (use `fund_user`).

    A bank mirror (operator_adjustment) is never a valid TARGET — it is only
    ever the counter-leg — so targeting one is rejected 422.

    Raises:
        AccountNotFound: unknown target, or unknown bank mirror, in this tenant.
        CurrencyMismatch: the bank mirror's currency differs from the target's.
    """
    if amount == 0:
        raise AppHTTPException(422, "amount_zero", "Amount must be non-zero.")

    await _assert_tenant_exists(session, tenant_id)

    target = (
        await session.execute(
            select(Account).where(
                Account.id == account_id,
                Account.tenant_id == tenant_id,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise AccountNotFound()
    if target.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT:
        raise AppHTTPException(
            422,
            "cannot_adjust_operator_adjustment",
            "operator_adjustment is the counter-leg and cannot itself "
            "be the target of an adjustment.",
        )

    counter = await resolve_bank_mirror(
        session,
        account_id=bank_mirror_account_id,
        tenant_id=tenant_id,
        currency=target.currency,
    )

    magnitude = abs(amount)
    if amount > 0:
        # Fund: float goes up.
        entries = [
            LedgerEntryRequest(account_id=counter.id, entry_type="DEBIT", amount=magnitude),
            LedgerEntryRequest(account_id=target.id, entry_type="CREDIT", amount=magnitude),
        ]
    else:
        # Withdraw: float goes down.
        entries = [
            LedgerEntryRequest(account_id=target.id, entry_type="DEBIT", amount=magnitude),
            LedgerEntryRequest(account_id=counter.id, entry_type="CREDIT", amount=magnitude),
        ]

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key or f"admin-adjust-{uuid4().hex}",
            transaction_type="treasury.adjust",
            currency=target.currency,
            entries=entries,
            initiated_by=None,
            amount=magnitude,
        ),
    )

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.adjust_system_wallet",
        entity_type="account",
        entity_id=str(account_id),
        after_state={
            "amount": str(amount),  # signed in the audit too
            "currency": target.currency,
            "transaction_id": str(txn.id),
            "reason": reason,
            "target_account_type": target.account_type,
            "bank_mirror_account_id": str(counter.id),
        },
        ip_address=ip_address,
    )
    await session.commit()

    new_balance, _ = await derive_balance(session, target.id)
    return AdjustSystemWalletResponse(
        transaction_id=txn.id,
        account_id=target.id,
        amount=amount,
        currency=target.currency,
        new_balance=new_balance,
    )
