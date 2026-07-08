"""Identity service — user lifecycle, identifier resolution, PIN/OTP auth.

All business logic for Module 1 lives here. The router is a thin wrapper.
Phase F.2 added the OTP, PIN, and session functions at the bottom of the
file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import hashing
from app.auth.lockout import (
    is_locked,
    lockout_seconds_remaining,
    register_failure,
    reset_failures,
)
from app.auth.principals import AdminPrincipal
from app.auth.rate_limit import consume_otp_send_quota
from app.auth.sessions import (
    consume_registration_token,
    create_registration_token,
    create_session,
)
from app.config import settings
from app.modules.identity.schemas import (
    AuthStartRequest,
    AuthStartResponse,
    ChangeUserTypeRequest,
    CreateUserRequest,
    IdentifierType,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    PinAuthRequest,
    PinSetRequest,
    SessionTokenResponse,
    UserProfileIn,
)
from app.shared.exceptions import (
    AccountLocked,
    IdentifierAlreadyInUse,
    InvalidCredentials,
    InvalidOtp,
    InvalidPinFormat,
    InvalidRegistrationToken,
    InvalidUserTypeParent,
    OtpRateLimited,
    PinAlreadySet,
    PinNotSet,
    TenantNotFound,
    UserNotFound,
)
from app.shared.models import (
    PARENT_TYPE_BY_CHILD,
    AuthAttempt,
    OtpRequest,
    Tenant,
    User,
    UserIdentifier,
    UserProfile,
)
from app.shared.utils.normalize import normalize_identifier


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant_id is not active in the DB.

    Args:
        session: Async DB session.
        tenant_id: The tenant UUID to verify.

    Raises:
        TenantNotFound: 404 when the tenant does not exist.
    """
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _validate_type_hierarchy(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_type: str,
    parent_user_id: UUID | None,
) -> None:
    """Enforce user-type <-> parent compatibility (Decision D4, Epic 12).

    Rules (spec §3.1):
      - consumer / super_agent / head_merchant must have a NULL parent.
      - agent's parent, when supplied, must be a super_agent in the same tenant.
      - merchant's parent, when supplied, must be a head_merchant in the same
        tenant.
      - The parent is optional for agent / merchant.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant the child user belongs to; the parent must share it.
        user_type: The child's type — already validated against the enum by the
            Pydantic layer.
        parent_user_id: The proposed parent, or None.

    Raises:
        InvalidUserTypeParent: 422 when a parent is set on a type that forbids
            one, or the parent's tenant/type does not match the requirement.
    """
    expected_parent_type = PARENT_TYPE_BY_CHILD.get(user_type)

    # Types with no slot in the hierarchy must never carry a parent.
    if expected_parent_type is None:
        if parent_user_id is not None:
            raise InvalidUserTypeParent()
        return

    # agent / merchant: parent is optional, but when present it must be the
    # right type AND live in the same tenant (no cross-tenant hierarchies).
    if parent_user_id is None:
        return

    result = await session.execute(
        select(User).where(User.id == parent_user_id, User.tenant_id == tenant_id)
    )
    parent = result.scalar_one_or_none()
    if parent is None or parent.user_type != expected_parent_type:
        raise InvalidUserTypeParent()


async def create_user(
    session: AsyncSession,
    request: CreateUserRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> User:
    """Create a new user with one or more identifiers and optional profile.

    Tenant isolation is enforced by storing `tenant_id` on every related row.
    Identifier uniqueness is enforced by the DB constraint — we catch the
    IntegrityError and re-raise as a clean 409 (Pay-PRD-0070).

    Args:
        session: Async DB session (NOT committed here — caller commits).
        request: Validated registration payload.
        admin: Authenticated admin (audit context). Direct-registration is
            admin-only after Phase F.4; absent for OTP-flow self-registration.
        ip_address: Caller IP (audit context).

    Returns:
        The created User with identifiers and profile loaded.

    Raises:
        TenantNotFound: 404 when request.tenant_id is unknown.
        IdentifierAlreadyInUse: 409 when an identifier collides in this tenant.
        InvalidUserTypeParent: 422 when user_type / parent_user_id are
            incompatible (Decision D4).

    Note:
        Merchant types (`merchant`, `head_merchant`) are accepted here, but the
        `merchant_profiles` row + collection account they need are provisioned
        in Epic 17 — this endpoint does not yet require a profile payload.
    """
    await _assert_tenant_exists(session, request.tenant_id)
    await _validate_type_hierarchy(
        session,
        tenant_id=request.tenant_id,
        user_type=request.user_type,
        parent_user_id=request.parent_user_id,
    )

    user = User(
        tenant_id=request.tenant_id,
        user_type=request.user_type,
        parent_user_id=request.parent_user_id,
    )
    session.add(user)
    # Flush to populate user.id before we insert identifiers that reference it.
    await session.flush()

    for ident in request.identifiers:
        # Normalise BEFORE persistence so the canonical form is what hits
        # the unique constraint + every future lookup.
        canonical = normalize_identifier(ident.identifier_type, ident.identifier_value)
        session.add(
            UserIdentifier(
                user_id=user.id,
                tenant_id=request.tenant_id,
                identifier_type=ident.identifier_type,
                identifier_value=canonical,
                verified=ident.verified,
            )
        )

    if request.profile is not None:
        session.add(_profile_for(user.id, request.profile))

    try:
        await session.flush()
    except IntegrityError as exc:
        # The unique constraint on (tenant_id, identifier_type, identifier_value)
        # is the only collision we expect here.
        await session.rollback()
        # We don't know which identifier collided without parsing the error —
        # the error message tells the API consumer enough.
        # Find the first colliding identifier for a clearer message.
        for ident in request.identifiers:
            existing = await _find_identifier(
                session,
                request.tenant_id,
                ident.identifier_type,
                ident.identifier_value,
            )
            if existing is not None:
                raise IdentifierAlreadyInUse(ident.identifier_type) from exc
        # Fallback if we cannot pinpoint.
        raise IdentifierAlreadyInUse(request.identifiers[0].identifier_type) from exc

    # NFR-0250: admin-initiated user creation is an audit event. Self-registration
    # via the OTP flow does NOT call this function (it has its own audit hook
    # in /pin/set landing in a follow-up phase).
    if admin is not None:
        from app.modules.audit.service import record_audit_for_admin

        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="user.registered.by_admin",
            entity_type="user",
            entity_id=str(user.id),
            after_state={
                "identifier_count": len(request.identifiers),
                "has_profile": request.profile is not None,
            },
            ip_address=ip_address,
        )

    await session.commit()
    return await _reload_user(session, user.id)


def _profile_for(user_id: UUID, src: UserProfileIn) -> UserProfile:
    """Build a UserProfile row from the request fragment."""
    return UserProfile(
        user_id=user_id,
        first_name=src.first_name,
        last_name=src.last_name,
        date_of_birth=src.date_of_birth,
    )


async def _find_identifier(
    session: AsyncSession,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
) -> UserIdentifier | None:
    """Return the matching identifier row or None — scoped to the tenant."""
    result = await session.execute(
        select(UserIdentifier).where(
            UserIdentifier.tenant_id == tenant_id,
            UserIdentifier.identifier_type == identifier_type,
            UserIdentifier.identifier_value == identifier_value,
        )
    )
    return result.scalar_one_or_none()


async def _reload_user(session: AsyncSession, user_id: UUID) -> User:
    """Fetch a user with identifiers eagerly loaded for the response."""
    result = await session.execute(
        select(User).where(User.id == user_id).options(selectinload(User.identifiers))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()
    return user


async def change_user_type(
    session: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    request: ChangeUserTypeRequest,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> User:
    """Change a user's type (and optional parent), audit-logged. Admin-only.

    Tenant-scoped: a user in another tenant returns 404 (no existence leak).
    Parent compatibility is enforced per Decision D4 (see
    `_validate_type_hierarchy`), and a user may never be its own parent.

    Idempotency is state-based (Epic 12 decision — the repo has no non-ledger
    idempotency store): if the user already has `new_type` with the same
    `parent_user_id`, this is a no-op — no audit row is written and the current
    state is returned, so retries are safe.

    The spec's merchant-specific guards (entering a merchant type requires a
    `merchant_profiles` row; leaving a merchant type is blocked while a
    `merchant_collection` account is non-zero) are DEFERRED to Epic 17 — those
    tables do not exist yet.

    Args:
        session: Async DB session (committed here on a real change).
        user_id: Target user.
        tenant_id: Caller's tenant; the user must belong to it.
        request: Validated {new_type, parent_user_id?, reason}.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP recorded on the audit row.

    Returns:
        The user with identifiers loaded (maps to `UserOut`).

    Raises:
        UserNotFound: 404 — unknown user or a user in another tenant.
        InvalidUserTypeParent: 422 — parent incompatible with new_type (D4),
            or the user was set as its own parent.

    Side effects:
        On a real change: updates `users.user_type` / `parent_user_id` and
        writes one `user.type_changed` audit row. Emits no Kafka event
        (lifecycle events are deferred).
    """
    from app.modules.audit.service import record_audit_for_admin

    result = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()

    # A user can never sit under itself in the hierarchy — reject before the
    # generic parent-type check (which would otherwise pass if the user is
    # currently the parent type it's pointing at).
    if request.parent_user_id == user.id:
        raise InvalidUserTypeParent()

    await _validate_type_hierarchy(
        session,
        tenant_id=tenant_id,
        user_type=request.new_type,
        parent_user_id=request.parent_user_id,
    )

    # State-based idempotency: already in the target state → no-op, no audit.
    if user.user_type == request.new_type and user.parent_user_id == request.parent_user_id:
        return await _reload_user(session, user.id)

    before = {
        "user_type": user.user_type,
        "parent_user_id": str(user.parent_user_id) if user.parent_user_id else None,
    }
    user.user_type = request.new_type
    user.parent_user_id = request.parent_user_id
    after = {
        "user_type": request.new_type,
        "parent_user_id": str(request.parent_user_id) if request.parent_user_id else None,
    }

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="user.type_changed",
        entity_type="user",
        entity_id=str(user.id),
        before_state=before,
        after_state=after,
        note=request.reason,
        ip_address=ip_address,
    )
    await session.commit()
    return await _reload_user(session, user.id)


async def get_user_detail(session: AsyncSession, *, user_id: UUID, tenant_id: UUID):
    """Load the full admin user-detail payload — identifiers, profile, accounts.

    Returns a plain dict so the router can map to the Pydantic response
    model. Tenant isolation is enforced: the user must belong to
    `tenant_id` or we raise UserNotFound (no existence leak across tenants).

    Args:
        session: Async DB session.
        user_id: The target user.
        tenant_id: Tenant of the requesting admin (carries forward from
            the path / query for now; F.5+ derives from realm context).

    Raises:
        UserNotFound: 404 — unknown user or user belongs to a different tenant.
    """

    from app.modules.accounts.service import derive_balance
    from app.shared.models import Account, UserProfile

    # Pull the user + identifiers in one round trip.
    user_q = await session.execute(
        select(User)
        .where(User.id == user_id, User.tenant_id == tenant_id)
        .options(selectinload(User.identifiers))
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        raise UserNotFound()

    # Profile is 0..1, separate table.
    profile_q = await session.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = profile_q.scalar_one_or_none()

    # Accounts (any account_type) — derive balance per account on demand.
    accounts_q = await session.execute(
        select(Account).where(Account.tenant_id == tenant_id, Account.user_id == user.id)
    )
    accounts = list(accounts_q.scalars().all())
    account_payload = []
    for acct in accounts:
        balance, reserved = await derive_balance(session, acct.id)
        account_payload.append(
            {
                "id": acct.id,
                "account_type": acct.account_type,
                "currency": acct.currency,
                "status": acct.status,
                "balance": str(balance),
                "reserved_balance": str(reserved),
                "available_balance": str(balance - reserved),
            }
        )

    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "status": user.status,
        "user_type": user.user_type,
        "parent_user_id": user.parent_user_id,
        "created_at": user.created_at,
        "identifiers": user.identifiers,
        "profile": profile,
        "accounts": account_payload,
    }


async def get_my_wallet(session: AsyncSession, *, user_id: UUID, tenant_id: UUID) -> dict:
    """Return the authenticated user's own wallet view.

    Mirrors what a real mobile app needs: accounts with derived balances
    plus the user's recent transactions. Transactions are pulled via the
    user's accounts' ledger entries so BOTH inbound (received P2P) and
    outbound (sent / spent) movements show up.

    Tenant scoping is implicit — the caller already authenticated and we
    re-assert against the session's tenant_id (NFR-0220).

    Args:
        session: Async DB session (read-only).
        user_id: The authenticated user.
        tenant_id: The session's tenant.

    Returns:
        Dict matching `WalletOut`. The router maps it to the schema.

    Raises:
        UserNotFound: 404 — user has been deleted between session issue
            and this call, or token's user_id is bogus.
    """
    from app.modules.accounts.service import derive_balance
    from app.shared.models import Account, UserProfile

    user_q = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        raise UserNotFound()

    profile_q = await session.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = profile_q.scalar_one_or_none()

    accounts_q = await session.execute(
        select(Account).where(Account.tenant_id == tenant_id, Account.user_id == user.id)
    )
    accounts = list(accounts_q.scalars().all())
    account_ids = [a.id for a in accounts]
    account_payload = []
    for acct in accounts:
        balance, reserved = await derive_balance(session, acct.id)
        account_payload.append(
            {
                "id": acct.id,
                "account_type": acct.account_type,
                "currency": acct.currency,
                "status": acct.status,
                "balance": str(balance),
                "reserved_balance": str(reserved),
                "available_balance": str(balance - reserved),
            }
        )

    # Recent transactions: DISTINCT through the user's accounts' ledger
    # entries so both sent + received movements appear. Limit 10 — mobile
    # surfaces a short feed; a full statement is a separate endpoint.
    txns_payload: list[dict] = await _build_recent_txns_payload(
        session, tenant_id=tenant_id, account_ids=account_ids
    )

    return {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "first_name": profile.first_name if profile else None,
        "accounts": account_payload,
        "recent_transactions": txns_payload,
    }


async def _build_recent_txns_payload(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_ids: list[UUID],
    limit: int = 10,
) -> list[dict]:
    """Build the recent-transactions list for /me/wallet.

    Loads up to 10 recent transactions touching the caller's accounts,
    then for each one derives:
      - `direction`: CREDIT on the user's account → "in"; DEBIT → "out".
      - `counterparty_name`: for `transaction_type='p2p'`, the OTHER
        side's user profile first_name. For top-ups / reward issuance /
        redemption the other side is a system or provider account with
        no owning user, so the value is None and the mobile UI falls
        back to a category label.

    Uses three additional queries (entries-by-txn batch fetch, other-
    side accounts batch fetch, user-profiles batch fetch) regardless of
    txn count — the constant-factor is fine for a feed capped at 10.

    Args:
        session: Async DB session (read-only).
        tenant_id: Caller's tenant (already validated upstream).
        account_ids: All accounts owned by the caller (financial + points).

    Returns:
        List of dicts shaped to match `WalletTransactionOut`.
    """
    from app.shared.models import Account, LedgerEntry, Transaction, UserProfile

    if not account_ids:
        return []

    txns_q = await session.execute(
        select(Transaction)
        .join(LedgerEntry, LedgerEntry.transaction_id == Transaction.id)
        .where(
            Transaction.tenant_id == tenant_id,
            LedgerEntry.account_id.in_(account_ids),
        )
        .distinct()
        .order_by(Transaction.created_at.desc())
        .limit(limit)
    )
    txns = list(txns_q.scalars().all())
    if not txns:
        return []

    txn_ids = [t.id for t in txns]

    # Pull every ledger entry for these txns in one query so we can
    # decide direction (from the user's-side entry) and find the
    # counterparty's account_id (from the other-side entries).
    entries_q = await session.execute(
        select(LedgerEntry).where(LedgerEntry.transaction_id.in_(txn_ids))
    )
    entries_by_txn: dict[UUID, list[LedgerEntry]] = {}
    for e in entries_q.scalars().all():
        entries_by_txn.setdefault(e.transaction_id, []).append(e)

    # Resolve counterparty first_name only when the other-side account
    # belongs to a user (i.e., P2P — both legs are user accounts). For
    # system / provider counterparts the account has user_id IS NULL.
    other_account_ids: set[UUID] = set()
    own_account_set = set(account_ids)
    for entries in entries_by_txn.values():
        for e in entries:
            if e.account_id not in own_account_set:
                other_account_ids.add(e.account_id)

    first_name_by_account: dict[UUID, str | None] = {}
    if other_account_ids:
        cp_rows = await session.execute(
            select(Account.id, UserProfile.first_name)
            .outerjoin(UserProfile, UserProfile.user_id == Account.user_id)
            .where(
                Account.id.in_(other_account_ids),
                Account.user_id.is_not(None),
            )
        )
        for acct_id, first_name in cp_rows.all():
            first_name_by_account[acct_id] = first_name

    payload: list[dict] = []
    for t in txns:
        entries = entries_by_txn.get(t.id, [])
        user_entry = next((e for e in entries if e.account_id in own_account_set), None)
        # Default to "out" if we somehow couldn't find a side; the user
        # would never see this row otherwise but the type system needs
        # a literal value.
        direction = "out"
        if user_entry is not None:
            direction = "in" if user_entry.entry_type == "CREDIT" else "out"

        counterparty_name: str | None = None
        if t.transaction_type == "p2p":
            other_entries = [e for e in entries if e.account_id not in own_account_set]
            for e in other_entries:
                name = first_name_by_account.get(e.account_id)
                if name:
                    counterparty_name = name
                    break

        payload.append(
            {
                "id": t.id,
                "transaction_type": t.transaction_type,
                "status": t.status,
                "amount": str(t.amount),
                "fee_amount": str(t.fee_amount),
                "currency": t.currency,
                "created_at": t.created_at,
                "direction": direction,
                "counterparty_name": counterparty_name,
            }
        )
    return payload


async def list_user_transactions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    limit: int = 50,
) -> list[dict]:
    """Return a user's recent transactions for the admin user-detail view.

    Resolves the user's accounts then delegates to the same payload
    builder the mobile /me/wallet endpoint uses, so the response shape
    stays consistent across admin and user surfaces.

    Args:
        tenant_id: Required for tenant isolation; cross-tenant lookups
            return UserNotFound (404).
        user_id: Target user.
        limit: Cap on rows returned. UI default is 50 — operators looking
            at a single account rarely need more on one screen.

    Returns:
        List of dicts shaped to match `UserTransactionOut`.

    Raises:
        UserNotFound: user_id is unknown or belongs to a different tenant.
    """
    from app.shared.models import Account

    user_q = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    if user_q.scalar_one_or_none() is None:
        raise UserNotFound()

    accounts_q = await session.execute(
        select(Account.id).where(Account.tenant_id == tenant_id, Account.user_id == user_id)
    )
    account_ids = list(accounts_q.scalars().all())
    return await _build_recent_txns_payload(
        session, tenant_id=tenant_id, account_ids=account_ids, limit=limit
    )


async def admin_reset_pin(
    session: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> dict:
    """Generate a fresh random 4-digit PIN for the user and persist its hash.

    Admin-only. Tenant-scoped — admin must supply the user's tenant_id;
    cross-tenant resets return 404 (no existence leak).

    The new PIN is generated server-side and the plaintext is RETURNED
    in the response so the operator can read it back over a verified
    channel (today). Phase 2 wires this through the notifications
    module to deliver via SMS, at which point `delivered_via` flips
    to "sms" and `new_pin` becomes None.

    Side effects:
      - Updates `users.pin_hash` (bcrypt of the new PIN).
      - Resets the user's PIN-failure lockout counter so they aren't
        locked out by stale state from before the reset.
      - Writes an `admin.pin_reset` audit row (the PLAIN PIN is NEVER
        written there — only the fact that a reset occurred).

    Args:
        session: Async DB session (commits inside).
        user_id: Target user.
        tenant_id: Caller's tenant; user must belong to it.
        admin: Authenticated admin principal for audit.
        ip_address: Caller IP for audit.

    Returns:
        Dict shaped like `AdminPinResetResponse`.

    Raises:
        UserNotFound: user unknown or belongs to another tenant.
    """
    import secrets

    from app.auth import hashing
    from app.auth.lockout import reset_failures
    from app.modules.audit.service import record_audit_for_admin

    user_q = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        raise UserNotFound()

    # 4-digit zero-padded — matches the mobile PIN spec. secrets module is
    # the CSPRNG safe choice; never use random.randint here.
    new_pin = f"{secrets.randbelow(10_000):04d}"
    user.pin_hash = hashing.hash_pin(new_pin)

    # A reset clears the lockout state — otherwise a previously-locked
    # user still couldn't log in with the new PIN until the window expires.
    await reset_failures(user_id)

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="admin.pin_reset",
        entity_type="user",
        entity_id=str(user_id),
        after_state={"delivered_via": "inline"},
        ip_address=ip_address,
    )
    await session.commit()

    return {"user_id": user_id, "delivered_via": "inline", "new_pin": new_pin}


async def resolve_identifier(
    session: AsyncSession,
    tenant_id: UUID,
    identifier_type: IdentifierType,
    identifier_value: str,
) -> UserIdentifier:
    """Resolve any registered identifier to a UserIdentifier row.

    Per Pay-PRD-0060, this is the entry point that maps phone / email /
    account / card to the canonical `user_id`.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope — cross-tenant resolution is NOT supported in
            Phase 1 (PRD §6.16 non-goal).
        identifier_type: One of the supported identifier types.
        identifier_value: The raw identifier value.

    Returns:
        The matching UserIdentifier row.

    Raises:
        UserNotFound: 404 when no identifier matches in this tenant.
    """
    # Normalise the lookup value so `+27 82 555 0001`, `+27-82-555-0001`,
    # and `+27825550001` all resolve to the same row.
    canonical = normalize_identifier(identifier_type, identifier_value)
    row = await _find_identifier(session, tenant_id, identifier_type, canonical)
    if row is None:
        raise UserNotFound()
    return row


# =============================================================================
# Phase F.2 — PIN/OTP user authentication flow
# =============================================================================


async def _find_user_by_phone(session: AsyncSession, tenant_id: UUID, phone: str) -> User | None:
    """Resolve a phone number to a User in this tenant, or None."""
    result = await session.execute(
        select(User)
        .join(UserIdentifier, UserIdentifier.user_id == User.id)
        .where(
            User.tenant_id == tenant_id,
            UserIdentifier.identifier_type == "phone",
            UserIdentifier.identifier_value == phone,
        )
    )
    return result.scalar_one_or_none()


async def _autocreate_user_with_phone(session: AsyncSession, tenant_id: UUID, phone: str) -> User:
    """First-time user: create on-the-fly when /otp/send hits an unknown phone.

    Matches Pay-PRD-0010 semantics — registration is a side-effect of the
    first OTP for that phone.
    """
    user = User(tenant_id=tenant_id)
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant_id,
            identifier_type="phone",
            identifier_value=phone,
            verified=False,  # becomes True after /otp/verify
        )
    )
    await session.commit()
    await session.refresh(user)
    return user


async def send_otp(session: AsyncSession, request: OtpSendRequest) -> OtpSendResponse:
    """Generate, store, and 'deliver' a one-time password.

    Auto-registers the phone if it's not already known in this tenant
    (Pay-PRD-0010). Rate-limited per phone via Redis.

    Args:
        session: Async DB session.
        request: Validated payload.

    Returns:
        Response indicating delivery; in local-dev mode the OTP itself is
        included so tests and manual demos can verify without an SMS gateway.

    Raises:
        TenantNotFound: 404 when tenant is unknown.
        OtpRateLimited: 429 when this phone has requested too many OTPs.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    allowed, retry_after = await consume_otp_send_quota(request.phone)
    if not allowed:
        raise OtpRateLimited(retry_after)

    user = await _find_user_by_phone(session, request.tenant_id, request.phone)
    if user is None:
        user = await _autocreate_user_with_phone(session, request.tenant_id, request.phone)

    otp = hashing.generate_otp()
    otp_hash = hashing.hash_otp(otp)
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.OTP_EXPIRY_SECONDS)
    session.add(
        OtpRequest(
            user_id=user.id,
            phone_number=request.phone,
            otp_hash=otp_hash,
            purpose="registration",
            expires_at=expires_at,
        )
    )
    await session.commit()

    return OtpSendResponse(
        delivered=True,
        otp=otp if settings.OTP_DEV_RETURN else None,
    )


async def verify_otp(session: AsyncSession, request: OtpVerifyRequest) -> OtpVerifyResponse:
    """Verify an OTP, mark it used, return a short-lived registration_token.

    Single-use semantics — `used_at` is set even if the OTP value matches a
    previously-used row (defence in depth; should not happen because we
    filter on `used_at IS NULL`).

    Args:
        session: Async DB session.
        request: phone + otp.

    Returns:
        registration_token (10-min TTL in Redis) for the subsequent /pin/set.

    Raises:
        TenantNotFound: 404 when tenant_id unknown.
        InvalidOtp: 401 for wrong, expired, or already-used OTP. Same message
            for all three — no enumeration leak.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    user = await _find_user_by_phone(session, request.tenant_id, request.phone)
    if user is None:
        raise InvalidOtp()

    # Find the latest unused, unexpired OTP for this phone.
    now = datetime.now(UTC)
    result = await session.execute(
        select(OtpRequest)
        .where(
            OtpRequest.user_id == user.id,
            OtpRequest.phone_number == request.phone,
            OtpRequest.used_at.is_(None),
            OtpRequest.expires_at > now,
        )
        .order_by(OtpRequest.created_at.desc())
        .limit(1)
    )
    otp_row = result.scalar_one_or_none()
    if otp_row is None:
        raise InvalidOtp()

    if not hashing.verify_otp(request.otp, otp_row.otp_hash):
        raise InvalidOtp()

    # Mark single-use + mark identifier verified.
    otp_row.used_at = now
    identifier_result = await session.execute(
        select(UserIdentifier).where(
            UserIdentifier.user_id == user.id,
            UserIdentifier.identifier_type == "phone",
            UserIdentifier.identifier_value == request.phone,
        )
    )
    identifier = identifier_result.scalar_one_or_none()
    if identifier is not None:
        identifier.verified = True
    await session.commit()

    reg_token = await create_registration_token(user.id, request.phone)
    return OtpVerifyResponse(
        registration_token=reg_token,
        expires_in=settings.REGTOKEN_TTL_SECONDS,
    )


def _validate_pin_format(pin: str) -> None:
    """4-6 digit numeric. Pydantic validates length; we add the digit check."""
    if not pin.isdigit():
        raise InvalidPinFormat()


async def set_pin(session: AsyncSession, request: PinSetRequest) -> None:
    """Set the user's PIN using a registration_token from /otp/verify.

    The token is single-use — `consume_registration_token` deletes it
    atomically on read.

    Args:
        session: Async DB session.
        request: registration_token + pin.

    Raises:
        InvalidPinFormat: PIN isn't 4-6 digits.
        InvalidRegistrationToken: token unknown / expired / already used.
        PinAlreadySet: user has a PIN — must use reset flow (deferred).
        UserNotFound: token's user_id doesn't exist (shouldn't happen).
    """
    _validate_pin_format(request.pin)

    payload = await consume_registration_token(request.registration_token)
    if payload is None:
        raise InvalidRegistrationToken()

    user_id = UUID(payload["user_id"])
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()
    if user.pin_hash is not None:
        raise PinAlreadySet()

    user.pin_hash = hashing.hash_pin(request.pin)
    await session.commit()


async def authenticate_pin(
    session: AsyncSession,
    request: PinAuthRequest,
    *,
    ip_address: str | None = None,
) -> SessionTokenResponse:
    """Verify PIN, write auth_attempts, enforce lockout, issue session_token.

    Lockout precedence:
      1. Check Redis lockout — if set, 423 immediately (don't even check PIN)
      2. Verify PIN; on miss increment counter; lock if threshold reached
      3. On success: reset counter, write success row, issue session

    Args:
        session: Async DB session.
        request: tenant + phone + PIN.
        ip_address: Caller IP for the auth_attempts row (recorded for forensics).

    Returns:
        SessionTokenResponse with the opaque token + TTL.

    Raises:
        TenantNotFound: 404 when tenant unknown.
        AccountLocked: 423 — currently locked (whether the PIN was right or not).
        InvalidCredentials: 401 — wrong phone or wrong PIN (same message).
        PinNotSet: 401 — user exists but hasn't completed PIN setup.
    """
    await _assert_tenant_exists(session, request.tenant_id)
    user = await _find_user_by_phone(session, request.tenant_id, request.phone)
    if user is None:
        raise InvalidCredentials()

    # Check lockout BEFORE comparing PIN — otherwise a locked-out attacker
    # who happens to guess the right PIN could still get in.
    if await is_locked(user.id):
        raise AccountLocked(await lockout_seconds_remaining(user.id))

    if user.pin_hash is None:
        # User started registration but never completed PIN setup.
        session.add(
            AuthAttempt(
                user_id=user.id,
                attempt_type="pin",
                success=False,
                ip_address=ip_address,
            )
        )
        await session.commit()
        raise PinNotSet()

    if not hashing.verify_pin(request.pin, user.pin_hash):
        # Record failed attempt + bump lockout counter.
        session.add(
            AuthAttempt(
                user_id=user.id,
                attempt_type="pin",
                success=False,
                ip_address=ip_address,
            )
        )
        await session.commit()
        await register_failure(user.id)
        # If the failure just tripped the lockout, prefer the locked error.
        if await is_locked(user.id):
            raise AccountLocked(await lockout_seconds_remaining(user.id))
        raise InvalidCredentials()

    # Success.
    session.add(
        AuthAttempt(
            user_id=user.id,
            attempt_type="pin",
            success=True,
            ip_address=ip_address,
        )
    )
    await session.commit()
    await reset_failures(user.id)

    session_token = await create_session(
        user_id=user.id, tenant_id=request.tenant_id, channel="mobile"
    )
    return SessionTokenResponse(
        session_token=session_token,
        expires_in=settings.SESSION_TTL_SECONDS,
    )


async def auth_start_lookup(session: AsyncSession, request: AuthStartRequest) -> AuthStartResponse:
    """Branch the mobile auth flow on whether (tenant, phone) already has a user.

    Pure read-only lookup — UNLIKE `send_otp`, this function MUST NOT
    create any rows. The mobile client calls this immediately after the
    user enters a phone number to decide between OTP registration
    (`needs_otp`) and PIN entry (`needs_pin`). No rate limit either; the
    OTP rate limit applies on the subsequent /otp/send call.

    Tenant isolation (NFR-0220): a phone known in tenant B is invisible
    from tenant A — both paths return `needs_otp`, which is what we want
    to avoid cross-tenant user enumeration.

    Args:
        session: Async DB session (read-only — no commit needed).
        request: Validated payload; phone is already normalised by the
            schema validator.

    Returns:
        AuthStartResponse with status `"needs_pin"` if a user exists for
        (tenant_id, phone), else `"needs_otp"`.

    Raises:
        TenantNotFound: 404 when tenant_id is unknown. Mirrors /otp/send so
            an attacker can't probe tenant existence via this endpoint either.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    user = await _find_user_by_phone(session, request.tenant_id, request.phone)
    if user is not None:
        return AuthStartResponse(status="needs_pin")
    return AuthStartResponse(status="needs_otp")
