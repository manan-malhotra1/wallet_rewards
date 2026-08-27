"""Identity service — user lifecycle, identifier resolution, PIN/OTP auth.

All business logic for Module 1 lives here. The router is a thin wrapper.
Phase F.2 added the OTP, PIN, and session functions at the bottom of the
file.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
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
    invalidate_user_sessions,
)
from app.config import settings
from app.modules.identity.schemas import (
    AuthStartRequest,
    AuthStartResponse,
    ChangeUserTypeRequest,
    CreateUserRequest,
    IdentifierIn,
    IdentifierType,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    ParentIdentifierIn,
    PinAuthRequest,
    PinSetRequest,
    SessionTokenResponse,
    UserProfileIn,
)
from app.modules.roles.service import assign_default_role
from app.modules.user_types.service import assert_user_type_valid
from app.shared.exceptions import (
    AccountLocked,
    AccountSuspended,
    IdentifierAlreadyInUse,
    IdentifierNotManuallyVerifiable,
    InvalidCredentials,
    InvalidOtp,
    InvalidPinFormat,
    InvalidReferralCode,
    InvalidRegistrationToken,
    InvalidUserTypeParent,
    OtpRateLimited,
    ParentNotFound,
    ParentReferenceAmbiguous,
    PinAlreadySet,
    PinNotSet,
    SelfReferralNotAllowed,
    TenantNotFound,
    TransactionsBlocked,
    UserNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    REFERRAL_STATUS_PENDING,
    SERVICE_STATUS_ACTIVE,
    USER_STATUS_ACTIVE,
    USER_STATUS_CLOSED,
    USER_STATUS_SUSPENDED,
    USER_STATUS_TXN_LOCKED,
    AuthAttempt,
    MerchantProfile,
    OtpRequest,
    Referral,
    ReferralCode,
    Service,
    Tenant,
    User,
    UserIdentifier,
    UserProfile,
)
from app.shared.utils.account_labels import account_label
from app.shared.utils.normalize import normalize_identifier

log = structlog.get_logger()


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


# Admin access-lock (migration 0045). An access LEVEL is the operator-facing
# concept; it maps 1:1 onto a `user.status`. `closed` is terminal and has no
# level an admin can set here — it only appears when READING an already-closed
# user (surfaced as its own "closed" access_level).
ACCESS_LEVEL_TO_STATUS = {
    "active": USER_STATUS_ACTIVE,
    "login_locked": USER_STATUS_SUSPENDED,
    "transactions_locked": USER_STATUS_TXN_LOCKED,
}
STATUS_TO_ACCESS_LEVEL = {
    USER_STATUS_ACTIVE: "active",
    USER_STATUS_SUSPENDED: "login_locked",
    USER_STATUS_TXN_LOCKED: "transactions_locked",
    USER_STATUS_CLOSED: "closed",
}


async def assert_user_can_transact(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> None:
    """Block a user-initiated money path unless the acting user is `active`.

    Shared guard called at the TOP of every user-initiated money path (after the
    idempotency fast-path, before charge/ledger work). It loads the initiating
    user tenant-scoped and rejects when their status is anything other than
    `active` — `txn_locked`, `suspended`, and `closed` all block. The RECEIVING
    side of a transfer is passive and must NOT be guarded (see money-path call
    sites); only the initiator is checked.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — a user in another tenant is treated as unknown.
        user_id: The user INITIATING the money movement.

    Raises:
        UserNotFound: 404 — unknown user, or a user in another tenant.
        TransactionsBlocked: 403 — the account's status is not `active`.
    """
    result = await session.execute(
        select(User.status).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    status = result.scalar_one_or_none()
    if status is None:
        raise UserNotFound()
    if status != USER_STATUS_ACTIVE:
        raise TransactionsBlocked()


async def _resolve_parent_user_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    parent_user_id: UUID | None,
    parent_identifier: ParentIdentifierIn | None,
) -> UUID | None:
    """Collapse the two supervisor reference forms into one user id (spec §7.2).

    Args:
        session: Async DB session (read-only).
        tenant_id: Resolution is tenant-scoped; a supervisor in another tenant
            is indistinguishable from a missing one.
        parent_user_id: Direct reference, or None.
        parent_identifier: Identifier reference, or None.

    Returns:
        The supervisor's user id, or None when neither form was supplied —
        which is valid and the normal case.

    Raises:
        ParentReferenceAmbiguous: 422 — both forms supplied.
        ParentNotFound: 422 — the identifier does not resolve in this tenant.
    """
    if parent_user_id is not None and parent_identifier is not None:
        raise ParentReferenceAmbiguous()
    if parent_identifier is None:
        return parent_user_id

    # Normalise first: the stored value is canonical, so "+27 82 555 2100" and
    # "+27825552100" must hit the same row rather than one silently missing.
    canonical = normalize_identifier(
        parent_identifier.identifier_type, parent_identifier.identifier_value
    )
    row = await _find_identifier(session, tenant_id, parent_identifier.identifier_type, canonical)
    if row is None:
        raise ParentNotFound()
    return row.user_id


async def _validate_type_hierarchy(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_type: str,
    parent_user_id: UUID | None,
) -> None:
    """Validate the type itself, then its parent compatibility (spec §5, §6).

    Two jobs, in this order, on EVERY path that writes or changes a user's type:

    1. The type must resolve and be active for this tenant. The
       `ck_users_user_type` CHECK was dropped when types became runtime data
       (migration 0061), so this is the only thing standing between a typo and a
       `users` row whose type no config can resolve — which would silently fall
       through to the `user_type IS NULL` default pricing and limits instead of
       being refused (spec §11).
    2. The supervisor requirement, read off the child type row's
       `parent_type_code` rather than a hardcoded map, so custom types get the
       same enforcement as the five seeded ones.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant the child user belongs to; the parent must share it.
        user_type: The child's type code, unvalidated — Pydantic no longer
            constrains it because the catalog is runtime data.
        parent_user_id: The proposed parent, or None.

    Raises:
        UnknownUserType: 422 when the type does not resolve for this tenant or
            has been retired.
        InvalidUserTypeParent: 422 when a parent is set on a type that forbids
            one, or the parent's tenant/type does not match the requirement.
    """
    child_type = await assert_user_type_valid(session, tenant_id=tenant_id, code=user_type)
    expected_parent_type = child_type.parent_type_code

    # Types with no slot in the hierarchy must never carry a parent.
    if expected_parent_type is None:
        if parent_user_id is not None:
            raise InvalidUserTypeParent()
        return

    # Child types: the parent stays OPTIONAL, but when present it must be the
    # right type AND live in the same tenant (no cross-tenant hierarchies).
    if parent_user_id is None:
        return

    result = await session.execute(
        select(User).where(User.id == parent_user_id, User.tenant_id == tenant_id)
    )
    parent = result.scalar_one_or_none()
    if parent is None or parent.user_type != expected_parent_type:
        raise InvalidUserTypeParent()


# Referral-code alphabet — unambiguous (no 0/O/1/I) so codes are easy to read
# and dictate. 8 chars over 32 symbols is ~10^12 space; collisions are rare and
# handled by the pre-check + the (tenant, code) unique constraint.
_REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_REFERRAL_CODE_LENGTH = 8


def _generate_referral_code_value() -> str:
    """Return one random referral code. Split out so tests can monkeypatch it."""
    import secrets

    return "".join(secrets.choice(_REFERRAL_CODE_ALPHABET) for _ in range(_REFERRAL_CODE_LENGTH))


async def _create_unique_referral_code(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> ReferralCode:
    """Create the user's own unique referral code within the tenant.

    Pre-checks a fresh candidate against existing codes and retries on the rare
    collision; the (tenant, code) unique constraint is the final structural
    guard. The row is flushed so a self-referral check in the same transaction
    can resolve it.

    Raises:
        RuntimeError: could not find a free code after several attempts
            (astronomically unlikely — signals a broken RNG or exhausted space).
    """
    for _ in range(10):
        candidate = _generate_referral_code_value()
        clash = await session.execute(
            select(ReferralCode.id).where(
                ReferralCode.tenant_id == tenant_id,
                ReferralCode.code == candidate,
            )
        )
        if clash.scalar_one_or_none() is None:
            code = ReferralCode(tenant_id=tenant_id, user_id=user_id, code=candidate)
            session.add(code)
            await session.flush()
            return code
    raise RuntimeError("Could not generate a unique referral code.")


async def _resolve_referrer(
    session: AsyncSession, *, tenant_id: UUID, code: str, new_user_id: UUID
) -> ReferralCode:
    """Resolve a quoted referral code to its owner in the tenant.

    Args:
        tenant_id: Tenant scope — codes never resolve across tenants.
        code: The code the new user quoted at signup.
        new_user_id: The user being created; used to reject self-referral.

    Returns:
        The owning ReferralCode row (the referrer).

    Raises:
        InvalidReferralCode: 422 — no such code in this tenant.
        SelfReferralNotAllowed: 422 — the code belongs to the new user.
    """
    result = await session.execute(
        select(ReferralCode).where(
            ReferralCode.tenant_id == tenant_id,
            ReferralCode.code == code,
        )
    )
    referrer_code = result.scalar_one_or_none()
    if referrer_code is None:
        raise InvalidReferralCode()
    if referrer_code.user_id == new_user_id:
        raise SelfReferralNotAllowed()
    return referrer_code


async def _assert_referral_code_exists(
    session: AsyncSession, *, tenant_id: UUID, code: str
) -> None:
    """Fail fast if a referral code doesn't resolve in the tenant (no user yet).

    Used at /otp/send BEFORE the per-phone OTP rate-limit quota is consumed, so a
    typo'd code returns 422 without burning the phone's ~60s quota (a subsequent
    valid send still works). Self-referral cannot arise here — the new user does
    not exist yet — so only existence is checked; `create_user` still runs the
    authoritative validation (unknown + self) atomically at registration.

    Raises:
        InvalidReferralCode: 422 — no such code in this tenant.
    """
    exists = (
        await session.execute(
            select(ReferralCode.id).where(
                ReferralCode.tenant_id == tenant_id,
                ReferralCode.code == code,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise InvalidReferralCode()


async def create_user(
    session: AsyncSession,
    request: CreateUserRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
    self_registration: bool = False,
) -> User:
    """Create a new user with one or more identifiers and optional profile.

    Tenant isolation is enforced by storing `tenant_id` on every related row.
    Identifier uniqueness is enforced by the DB constraint — we catch the
    IntegrityError and re-raise as a clean 409 (Pay-PRD-0070).

    Referral attribution is created ONLY for self-registration (the OTP
    auto-register path passes `self_registration=True`); admin-, external-, and
    maker-checker-created users IGNORE `referral_code` entirely — no referral
    link, and therefore no referral reward can ever accrue to them. NO referral
    reward is issued here in ANY case: a valid code creates a PENDING referral
    only, and the reward fires later at PIN-set (registration completion), which
    an admin-/externally-created user never runs.

    Args:
        session: Async DB session. COMMITTED here (the user, identifiers,
            referral code, and any pending referral land atomically). Callers
            that need to attach follow-on rows (e.g. an external idempotency
            mapping) must commit those separately — this fn owns its commit.
        request: Validated registration payload.
        admin: Authenticated admin (audit context). Direct-registration is
            admin-only after Phase F.4; absent for OTP-flow self-registration.
        ip_address: Caller IP (audit context).
        self_registration: True only for the end-user OTP auto-register path.
            Gates referral-code validation + PENDING-referral creation, so an
            admin/external caller never mints a rewardable referral link.

    Returns:
        The created User with identifiers and profile loaded.

    Raises:
        TenantNotFound: 404 when request.tenant_id is unknown.
        IdentifierAlreadyInUse: 409 when an identifier collides in this tenant.
        ParentReferenceAmbiguous: 422 when both `parent_user_id` and
            `parent_identifier` are supplied.
        ParentNotFound: 422 when `parent_identifier` resolves to nobody in this
            tenant. Cross-tenant and nonexistent are indistinguishable.
        UnknownUserType: 422 when `user_type` does not resolve for this tenant
            or has been retired.
        InvalidUserTypeParent: 422 when user_type / parent_user_id are
            incompatible (Decision D4).
        InvalidReferralCode: 422 (self-registration only) — the quoted code does
            not resolve in this tenant; raised BEFORE commit so no half-user lands.
        SelfReferralNotAllowed: 422 (self-registration only) — code is the new
            user's own.

    Note:
        Business-category types are accepted here, but no `merchant_profiles`
        row or collection account is provisioned anywhere today — that lands in
        Epic 17, so this endpoint does not require a profile payload.
    """
    await _assert_tenant_exists(session, request.tenant_id)
    # Collapse the two supervisor reference forms BEFORE validating, so the
    # identifier path gets exactly the same type check as a raw UUID (§7.2).
    parent_user_id = await _resolve_parent_user_id(
        session,
        tenant_id=request.tenant_id,
        parent_user_id=request.parent_user_id,
        parent_identifier=request.parent_identifier,
    )
    await _validate_type_hierarchy(
        session,
        tenant_id=request.tenant_id,
        user_type=request.user_type,
        parent_user_id=parent_user_id,
    )

    user = User(
        tenant_id=request.tenant_id,
        user_type=request.user_type,
        parent_user_id=parent_user_id,
    )
    session.add(user)
    # Flush to populate user.id before we insert identifiers that reference it.
    await session.flush()

    # Give the user their tenant's default role for this user_type. Without it
    # they hold no role at all, and `has_permission` denies by default
    # (Pay-PRD-0440) — a wallet that can never send money.
    await assign_default_role(session, user)

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

    # Flush the identifiers NOW — before the referral-code / profile / referral
    # rows below, because `_create_unique_referral_code` flushes internally. If a
    # duplicate identifier (unique on (tenant, type, value)) only tripped that
    # later flush, the IntegrityError would escape UNCAUGHT as a raw 500 instead
    # of the clean 409 below. Guarding the identifier flush here is the single
    # collision we expect on create.
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        # Pinpoint the colliding identifier (normalise to match the stored
        # canonical form) for a precise message; fall back to the first.
        for ident in request.identifiers:
            existing = await _find_identifier(
                session,
                request.tenant_id,
                ident.identifier_type,
                normalize_identifier(ident.identifier_type, ident.identifier_value),
            )
            if existing is not None:
                raise IdentifierAlreadyInUse(ident.identifier_type) from exc
        raise IdentifierAlreadyInUse(request.identifiers[0].identifier_type) from exc

    if request.profile is not None:
        session.add(_profile_for(user.id, request.profile))

    # Every user gets their own shareable referral code (flushed so a
    # self-referral quoting it in this same request resolves).
    await _create_unique_referral_code(session, tenant_id=request.tenant_id, user_id=user.id)

    # Attribution (self-registration ONLY): a quoted code creates a PENDING
    # referral (referred -> referrer). Validation (unknown / self) raises 422
    # before any commit, so a bad code rolls the whole signup back cleanly. NO
    # reward is issued here — the referral stays PENDING until the referred user
    # COMPLETES registration at PIN-set (anti-farming: an unverified phone that
    # never finishes signup is never paid). Admin/external callers pass
    # self_registration=False, so they never mint a rewardable referral link.
    if self_registration and request.referral_code:
        referrer_code = await _resolve_referrer(
            session,
            tenant_id=request.tenant_id,
            code=request.referral_code,
            new_user_id=user.id,
        )
        session.add(
            Referral(
                tenant_id=request.tenant_id,
                referrer_user_id=referrer_code.user_id,
                referred_user_id=user.id,
                code=request.referral_code,
                status=REFERRAL_STATUS_PENDING,
            )
        )

    await session.flush()

    # Provision the user's wallets INSIDE this transaction (spec 2026-08-26,
    # D12), so a failed create never leaves orphaned accounts. Every user gets
    # a main wallet per active financial currency; Retail/Business users on a
    # flag-on tenant also get a commission wallet. Local import: `provisioning`
    # imports user_types, which reaches back into identity — a module-level
    # import here would cycle.
    from app.modules.accounts.provisioning import provision_user_accounts

    await provision_user_accounts(session, tenant_id=request.tenant_id, user_id=user.id)

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

    # No referral reward is issued at creation (anti-farming): a PENDING referral
    # created above is paid only when the referred user COMPLETES registration at
    # PIN-set (see `set_pin` -> evaluate_referral_on_registration_complete).
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


# Identifier fallback preference: an operator recognises a phone before an
# email before a raw account / card token. Lower number = preferred.
_IDENTIFIER_PRIORITY = {"phone": 0, "email": 1, "account_number": 2, "card_number": 3}


async def resolve_user_names(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_ids: Iterable[UUID],
) -> dict[UUID, str]:
    """Batch-resolve user ids to human display names, tenant-scoped.

    The display name for each user is, in order of preference:
      1. The profile full name (`first_name` + `last_name`, joined and
         stripped) when the profile exists and yields a non-empty string.
      2. Otherwise the user's primary identifier value (phone preferred, then
         email, then account / card) — the value an operator would search on.
      3. Otherwise the user is omitted from the map, so the caller falls back
         to a short id.

    Mirrors `admin_profiles.resolve_admin_names`: unknown or nameless users are
    simply absent from the returned map. Runs at most two queries regardless of
    how many ids are requested.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — users in other tenants never resolve
            (NFR-0220), even when their id is passed in.
        user_ids: The user ids to resolve; duplicates and falsy ids are ignored.

    Returns:
        A `{user_id: display_name}` map for every id that resolved to a name.
    """
    wanted = {uid for uid in user_ids if uid}
    if not wanted:
        return {}

    names: dict[UUID, str] = {}

    # 1. Profile full names — tenant-scoped via the User join so a profile
    #    row can never surface a name for a user in another tenant.
    profile_rows = await session.execute(
        select(User.id, UserProfile.first_name, UserProfile.last_name)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(User.tenant_id == tenant_id, User.id.in_(wanted))
    )
    for user_id, first_name, last_name in profile_rows.all():
        full_name = " ".join(part for part in (first_name, last_name) if part).strip()
        if full_name:
            names[user_id] = full_name

    # 2. Fall back to a primary identifier for users still without a name.
    remaining = wanted - names.keys()
    if remaining:
        ident_rows = await session.execute(
            select(
                UserIdentifier.user_id,
                UserIdentifier.identifier_type,
                UserIdentifier.identifier_value,
            ).where(
                UserIdentifier.tenant_id == tenant_id,
                UserIdentifier.user_id.in_(remaining),
            )
        )
        # Keep the highest-priority identifier value seen per user.
        best: dict[UUID, tuple[int, str]] = {}
        for user_id, id_type, id_value in ident_rows.all():
            priority = _IDENTIFIER_PRIORITY.get(id_type, 99)
            current = best.get(user_id)
            if current is None or priority < current[0]:
                best[user_id] = (priority, id_value)
        for user_id, (_priority, id_value) in best.items():
            names[user_id] = id_value

    return names


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
        UnknownUserType: 422 — `new_type` does not resolve for this tenant or
            has been retired.
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

    # A promotion INTO Retail / Business earns a commission wallet (spec §6.3).
    # Deliberately one-directional: a demotion RETAINS the wallet, because the
    # ledger is append-only and its balance may be non-zero — it must stay
    # disbursable. New accruals stop on their own once config no longer
    # resolves for the new type.
    from app.modules.accounts.provisioning import provision_user_accounts

    await provision_user_accounts(session, tenant_id=tenant_id, user_id=user.id)

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


async def admin_update_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    first_name: str | None = None,
    last_name: str | None = None,
    status: str | None = None,
    user_type: str | None = None,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> User:
    """Apply admin edits to an existing user's editable fields, audit-logged.

    Editable fields: profile first/last name, account status, and user_type.
    Identifiers are NOT editable here (out of scope). Any argument left None is
    left unchanged — the caller (the user-operation apply path) passes only the
    fields the maker proposed. A user_type change re-validates the type itself
    and the D4 hierarchy against the user's EXISTING parent.

    Tenant-scoped: a user in another tenant returns 404 (no existence leak).
    Does NOT use its own commit boundary lightly — it commits once, together
    with any request-state transition the caller staged before invoking it
    (so the maker-checker APPLIED transition and this edit land atomically).

    Args:
        session: Async DB session (committed here).
        user_id: Target user.
        tenant_id: Caller's tenant; the user must belong to it.
        first_name / last_name: New profile names, or None to leave unchanged.
        status: New account status ('active' / 'suspended'), or None.
        user_type: New user type, or None to leave unchanged.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP recorded on the audit row.

    Returns:
        The user with identifiers loaded (maps to `UserOut`).

    Raises:
        UserNotFound: 404 — unknown user or a user in another tenant.
        UnknownUserType: 422 — `user_type` does not resolve for this tenant or
            has been retired.
        InvalidUserTypeParent: 422 — new user_type incompatible with the user's
            existing parent (Decision D4).

    Side effects:
        Updates users / user_profiles rows and writes one `user.updated` audit
        row with before/after state.
    """
    from app.modules.audit.service import record_audit_for_admin

    result = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()

    if user_type is not None:
        await _validate_type_hierarchy(
            session,
            tenant_id=tenant_id,
            user_type=user_type,
            parent_user_id=user.parent_user_id,
        )

    profile_q = await session.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = profile_q.scalar_one_or_none()
    if profile is None and (first_name is not None or last_name is not None):
        profile = UserProfile(user_id=user.id)
        session.add(profile)

    before = {
        "first_name": profile.first_name if profile else None,
        "last_name": profile.last_name if profile else None,
        "status": user.status,
        "user_type": user.user_type,
    }
    if first_name is not None and profile is not None:
        profile.first_name = first_name
    if last_name is not None and profile is not None:
        profile.last_name = last_name
    if status is not None:
        user.status = status
    if user_type is not None:
        user.user_type = user_type
    after = {
        "first_name": profile.first_name if profile else None,
        "last_name": profile.last_name if profile else None,
        "status": user.status,
        "user_type": user.user_type,
    }

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="user.updated",
        entity_type="user",
        entity_id=str(user.id),
        before_state=before,
        after_state=after,
        ip_address=ip_address,
    )
    await session.commit()
    return await _reload_user(session, user.id)


async def get_user_detail(
    session: AsyncSession, *, user_id: UUID, tenant_id: UUID
) -> dict[str, Any]:
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
    spendable_total: dict[str, Decimal] = {}
    for acct in accounts:
        balance, reserved = await derive_balance(session, acct.id)
        # Spendable is an explicit account-TYPE test, not "has a balance": a
        # commission wallet holds real money the user cannot transact against
        # until a disbursement run moves it (spec 2026-08-26 §5, §10).
        spendable = acct.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET
        if spendable:
            spendable_total[acct.currency] = spendable_total.get(
                acct.currency, Decimal("0")
            ) + (balance - reserved)
        account_payload.append(
            {
                "id": acct.id,
                "account_type": acct.account_type,
                "currency": acct.currency,
                "status": acct.status,
                "balance": str(balance),
                "reserved_balance": str(reserved),
                "available_balance": str(balance - reserved),
                "spendable": spendable,
            }
        )

    # Resolve the parent's display name so the UI shows "Reports to: <name>"
    # instead of a bare id. None when there is no parent or it has no name.
    parent_name: str | None = None
    if user.parent_user_id is not None:
        parent_names = await resolve_user_names(
            session, tenant_id=tenant_id, user_ids=[user.parent_user_id]
        )
        parent_name = parent_names.get(user.parent_user_id)

    # PIN-lockout state (Redis, not a DB column) — surfaced so the admin UI can
    # show a "Locked" pill + countdown and offer an Unlock action (NFR-0190).
    locked = await is_locked(user.id)
    unlocks_in = await lockout_seconds_remaining(user.id) if locked else None

    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "status": user.status,
        # Admin access-lock level derived from status (migration 0045) so the UI
        # can render the current lock state without re-deriving the mapping.
        "access_level": STATUS_TO_ACCESS_LEVEL.get(user.status, user.status),
        "user_type": user.user_type,
        "parent_user_id": user.parent_user_id,
        "parent_name": parent_name,
        "created_at": user.created_at,
        "identifiers": user.identifiers,
        "profile": profile,
        "accounts": account_payload,
        "spendable_total": {k: str(v) for k, v in spendable_total.items()},
        "is_locked": locked,
        "unlocks_in_seconds": unlocks_in,
    }


async def get_services_for_user(
    session: AsyncSession, *, user_id: UUID, tenant_id: UUID
) -> list[Service]:
    """Resolve the caller's user_type, then list the services they may initiate.

    Thin orchestrator behind `GET /me/services` so the router stays logic-free:
    it looks up the authenticated user's `user_type` (tenant-scoped) and hands
    off to `list_my_services` for the actual catalog query.

    Args:
        session: Async DB session (read-only).
        user_id: The authenticated mobile user.
        tenant_id: The session's tenant.

    Returns:
        The active, mobile-initiable services for this user, ordered by
        display_name (see `list_my_services`).

    Raises:
        UserNotFound: 404 — the token's user_id is unknown in this tenant.
    """
    result = await session.execute(
        select(User.user_type).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user_type = result.scalar_one_or_none()
    if user_type is None:
        raise UserNotFound()
    return await list_my_services(session, tenant_id=tenant_id, user_type=user_type)


async def list_my_services(
    session: AsyncSession, *, tenant_id: UUID, user_type: str
) -> list[Service]:
    """List active services a given user_type may initiate on the `mobile` channel.

    Backs the mobile home tiles. A service is returned only when it is active,
    not soft-deleted, in the tenant, AND both access dimensions permit the
    caller — the two are ANDed:
      - user_type: the service's `allowed_user_types` is unrestricted OR lists
        this user_type.
      - channel: the service's `allowed_channels` is unrestricted OR lists
        `mobile`.

    "Unrestricted" means the policy array is NULL **or empty** — both mean "all
    values allowed" per the `services` column semantics. This is expressed with
    `array_length(col, 1) IS NULL`, which is true for a NULL array AND for an
    empty array (Postgres `array_length` returns NULL for a zero-length array),
    so a single predicate covers both cases. A non-empty array is an allow-list
    checked with `value = ANY(col)`.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — services never resolve across tenants.
        user_type: The caller's user_type (consumer / agent / super_agent /
            merchant / head_merchant).

    Returns:
        Matching `Service` rows ordered by `display_name` for a stable feed.
    """
    from sqlalchemy import func, or_

    stmt = (
        select(Service)
        .where(
            Service.tenant_id == tenant_id,
            Service.status == SERVICE_STATUS_ACTIVE,
            Service.deleted_at.is_(None),
            # user_type dimension: NULL-or-empty array = unrestricted; else the
            # user_type must be a member (array_position returns NULL when absent).
            or_(
                func.array_length(Service.allowed_user_types, 1).is_(None),
                func.array_position(Service.allowed_user_types, user_type).is_not(None),
            ),
            # channel dimension: NULL-or-empty array = unrestricted; else the
            # array must list the mobile channel.
            or_(
                func.array_length(Service.allowed_channels, 1).is_(None),
                func.array_position(Service.allowed_channels, "mobile").is_not(None),
            ),
        )
        .order_by(Service.display_name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_my_wallet(session: AsyncSession, *, user_id: UUID, tenant_id: UUID) -> dict[str, Any]:
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
    # entries so both sent + received movements appear. Limit 20 — mobile
    # surfaces a short feed (shown 4-at-a-time with a "more" toggle); a
    # full statement is a separate endpoint.
    txns_payload: list[dict[str, Any]] = await _build_recent_txns_payload(
        session, tenant_id=tenant_id, user_id=user.id, account_ids=account_ids
    )

    return {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "first_name": profile.first_name if profile else None,
        "accounts": account_payload,
        "recent_transactions": txns_payload,
    }


async def _resolve_counterparty_names(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_ids: set[UUID],
) -> dict[UUID, str]:
    """Batch-resolve transaction counterparties to display names.

    Layers a merchant's TRADING name over the generic person-name resolution:
    a merchant is a user (Decision D1) so it also carries a `user_profiles`
    row, but an operator reading a cash-in needs "Acme Airtime", not the
    natural-person name behind the business. Falls back to
    `resolve_user_names` (profile full name → primary identifier) for agents
    and ordinary consumers.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — a counterparty in another tenant never
            resolves (NFR-0220).
        user_ids: Counterparty user ids.

    Returns:
        A `{user_id: display_name}` map; ids that resolve to no name at all
        are absent, so the caller renders a category label instead.
    """
    if not user_ids:
        return {}

    names = await resolve_user_names(session, tenant_id=tenant_id, user_ids=user_ids)

    business_rows = await session.execute(
        select(MerchantProfile.user_id, MerchantProfile.business_name).where(
            MerchantProfile.tenant_id == tenant_id,
            MerchantProfile.user_id.in_(user_ids),
        )
    )
    for user_id, business_name in business_rows.all():
        if business_name:
            names[user_id] = business_name

    return names


async def _resolve_counterparty_phones(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_ids: set[UUID],
) -> dict[UUID, str]:
    """Batch-resolve counterparty user ids to their phone identifier.

    ADMIN-ONLY data — see `_build_recent_txns_payload`'s
    `include_counterparty_phone` flag. Unverified numbers are included: an
    operator tracing a transfer needs the number on file, verified or not.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope (NFR-0220).
        user_ids: Counterparty user ids.

    Returns:
        A `{user_id: phone}` map; users without a phone identifier are absent.
    """
    if not user_ids:
        return {}

    rows = await session.execute(
        select(UserIdentifier.user_id, UserIdentifier.identifier_value).where(
            UserIdentifier.tenant_id == tenant_id,
            UserIdentifier.user_id.in_(user_ids),
            UserIdentifier.identifier_type == "phone",
        )
    )
    phones: dict[UUID, str] = {}
    for user_id, identifier_value in rows.all():
        # First phone wins — a user may carry several; they are equivalent for
        # display and the admin can see the full list on the user's own page.
        phones.setdefault(user_id, identifier_value)
    return phones


def _user_txns_stmt(
    stmt: Any,
    *,
    tenant_id: UUID,
    account_ids: list[UUID],
    currency: str | None = None,
    reference: str | None = None,
) -> Any:
    """Scope a Transaction query to one user's accounts, with optional filters.

    One definition for the page query and its COUNT so the two can never
    disagree about what "matching" means (a paginator whose total counts
    different rows than the page is worse than no total at all).

    Args:
        currency: Exact match, upper-cased (e.g. "ZAR", "PTS"). None = all.
        reference: Case-insensitive substring of the customer-facing
            reference (e.g. "S_20260820180829019411"). None = all.
    """
    from app.shared.models import LedgerEntry, Transaction

    stmt = stmt.join(LedgerEntry, LedgerEntry.transaction_id == Transaction.id).where(
        Transaction.tenant_id == tenant_id,
        LedgerEntry.account_id.in_(account_ids),
    )
    if currency:
        stmt = stmt.where(Transaction.currency == currency.upper())
    if reference:
        stmt = stmt.where(Transaction.reference.ilike(f"%{reference.strip()}%"))
    return stmt.distinct()


async def _count_user_txns(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_ids: list[UUID],
    currency: str | None = None,
    reference: str | None = None,
) -> int:
    """Total transactions matching the same filters as the page query."""
    from sqlalchemy import func as sa_func

    from app.shared.models import Transaction

    if not account_ids:
        return 0
    inner = _user_txns_stmt(
        select(Transaction.id),
        tenant_id=tenant_id,
        account_ids=account_ids,
        currency=currency,
        reference=reference,
    ).subquery()
    return int((await session.execute(select(sa_func.count()).select_from(inner))).scalar_one())


def _resolve_row_counterparty(
    *,
    entries: list[Any],
    own_account_set: set[UUID],
    label_by_account: dict[UUID, str],
    user_id_by_account: dict[UUID, UUID],
    name_by_user: dict[UUID, str],
    phone_by_user: dict[UUID, str],
    own_label_by_account: dict[UUID, str],
) -> tuple[str | None, str | None]:
    """Name the OTHER side of one transaction, from the caller's perspective.

    Resolves in descending specificity:
      1. the other party's display name, when a leg belongs to a different user;
      2. what the other account IS, when no leg has an owning user (a system
         pool, a bank mirror, a merchant collection account);
      3. the caller's own other wallet, when every leg is theirs — a commission
         disbursement moves between two of their own wallets.

    The account fallback follows the LARGEST other-side leg, not the first: a
    cash-out carries fee and tax legs beside the principal, and naming the
    counterparty "Fees collected" because that entry was read first would be
    actively misleading.

    Returns:
        `(name, phone)`. The phone is only ever populated when the caller asked
        for it (admin surfaces) AND the other side resolved to a real user.
    """
    counterparty_name: str | None = None
    counterparty_phone: str | None = None
    fallback_label: str | None = None
    fallback_amount = Decimal("-1")

    for e in entries:
        if e.account_id in own_account_set:
            continue
        label = label_by_account.get(e.account_id)
        amount = Decimal(str(e.amount))
        if label is not None and amount > fallback_amount:
            fallback_label = label
            fallback_amount = amount
        owner_id = user_id_by_account.get(e.account_id)
        if owner_id is None:
            continue
        counterparty_name = name_by_user.get(owner_id)
        counterparty_phone = phone_by_user.get(owner_id)
        if counterparty_name or counterparty_phone:
            break

    if counterparty_name is not None:
        return counterparty_name, counterparty_phone

    if fallback_label is None:
        # No other-side leg at all — every leg is the caller's own. Name the
        # wallet that is NOT the one this row reports on; with two legs there
        # is exactly one other, which is the disbursement case.
        own_legs = [e for e in entries if e.account_id in own_account_set]
        distinct = {e.account_id for e in own_legs}
        if len(distinct) == 2:
            # Deterministic: sorted, so the pair always resolves the same way.
            for acct_id in sorted(distinct):
                fallback_label = own_label_by_account.get(acct_id)
                if fallback_label is not None:
                    break

    return fallback_label, counterparty_phone


def _resolve_principals(
    *,
    entries: list[Any],
    user_id_by_account: dict[UUID, UUID],
    name_by_user: dict[UUID, str],
    own_account_set: set[UUID],
) -> tuple[str | None, str | None, bool]:
    """Name the SENDER and RECEIVER of a transaction, and say whether the
    caller is one of them.

    A single counterparty field assumes the viewer is one of the two sides.
    Parent commission breaks that: a supervisor earns from a transaction
    between their agent and a customer, and is a party to neither side. Such a
    row reads as "Agent Normal -> Alicia Mokoena" instead of naming one of them
    arbitrarily.

    The principals are the LARGEST user-owned debit and the LARGEST user-owned
    credit. Size is what separates the principal from the incidentals — a
    cash-in carries fee, tax and commission legs beside the money actually
    being moved, and any of them could otherwise be mistaken for a party.

    Returns:
        `(sender_name, receiver_name, caller_is_principal)`. Names are None
        when that side has no owning user (a system pool funds it).
    """
    sender_account: UUID | None = None
    receiver_account: UUID | None = None
    sender_amount = Decimal("-1")
    receiver_amount = Decimal("-1")

    for e in entries:
        owner = user_id_by_account.get(e.account_id)
        if owner is None and e.account_id not in own_account_set:
            continue  # system / pool leg — never a party
        amount = Decimal(str(e.amount))
        if e.entry_type == "DEBIT":
            if amount > sender_amount:
                sender_account, sender_amount = e.account_id, amount
        elif amount > receiver_amount:
            receiver_account, receiver_amount = e.account_id, amount

    caller_is_principal = (
        sender_account in own_account_set or receiver_account in own_account_set
    )

    def name_of(account_id: UUID | None) -> str | None:
        if account_id is None:
            return None
        owner = user_id_by_account.get(account_id)
        return name_by_user.get(owner) if owner is not None else None

    return name_of(sender_account), name_of(receiver_account), caller_is_principal


async def _build_recent_txns_payload(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    account_ids: list[UUID],
    limit: int = 20,
    offset: int = 0,
    currency: str | None = None,
    reference: str | None = None,
    include_counterparty_phone: bool = False,
    movement_account_ids: list[UUID] | None = None,
    scope_account_ids: list[UUID] | None = None,
) -> list[dict[str, Any]]:
    """Build the recent wallet-MOVEMENT list for /me/wallet.

    Loads recent transactions touching the caller's accounts and emits one row
    per (transaction, caller wallet). That shape is what the panel already
    promises — "movements on this user's wallets" — and it is the only one in
    which the amount, the direction and the wallet are each unambiguous:

      - `amount`: the caller's NET movement on THAT wallet. Never the
        transaction's headline, which for a supervisor earning parent
        commission on a large cash-in overstated their receipt by orders of
        magnitude.
      - `direction`: the sign of that wallet's net. Previously read off
        whichever leg the ledger query returned first, which was ambiguous the
        moment a user could own two legs of one transaction.
      - `wallet_account_type` / `wallet_label`: which wallet moved, so held
        commission is never mistaken for spendable money.
      - `counterparty_name`: the OTHER side's display name whenever that
        side is a user-owned account (p2p, merchant_cashin, cash_in,
        cashout) — a merchant's business name, else the person's full name
        (see `_resolve_counterparty_names`). For funds / reward issuance /
        redemption the other side is a system or provider account with no
        owning user, so the value is None and the UI falls back to a
        category label. NEVER a service name — the service is its own
        column.
      - `counterparty_phone`: the same party's phone number, included ONLY
        when `include_counterparty_phone` is set. ADMIN-ONLY: the mobile
        feed shares this builder, and one customer must never be handed
        another customer's number.
      - PER-PARTY fee / tax / commission: a transaction's charges are borne /
        earned by specific parties, not the whole transaction, so each is shown
        ONLY to the party it affected (see the per-txn loop). Two counterparties
        viewing the same transaction therefore see different, correct figures.

    Uses three additional queries (entries-by-txn batch fetch, other-
    side accounts batch fetch, user-profiles batch fetch) regardless of
    txn count — the constant-factor is fine for a feed capped at 10.

    Args:
        session: Async DB session (read-only).
        tenant_id: Caller's tenant (already validated upstream).
        user_id: The user whose PERSPECTIVE this feed is built for — decides
            who paid the fee/tax and who earned the commission on each row.
        account_ids: All accounts owned by the caller (financial + points).
        include_counterparty_phone: Admin surfaces only. Adds
            `counterparty_phone` to each row; leave False for user-facing
            callers so no customer sees another customer's number.
        movement_account_ids: Restrict which of the caller's wallets produce
            ROWS (the Main / Commission wallet filter). Deliberately separate
            from `account_ids`, which stays the full set: ownership decides
            what counts as the caller's own leg, and narrowing it would make
            the caller's OTHER wallet look like an external counterparty — a
            cash-in filtered to the commission wallet would name "Main wallet"
            as the counterparty instead of the customer.
        scope_account_ids: Which accounts decide WHICH TRANSACTIONS are worth
            fetching. Narrowed alongside `movement_account_ids` so a filtered
            page is not mostly empty, and so the page total agrees with what is
            rendered. Defaults to `account_ids`.

    Returns:
        List of dicts shaped to match `WalletTransactionOut`.
    """
    from app.shared.models import Account, LedgerEntry, Transaction

    if not account_ids:
        return []

    txns_q = await session.execute(
        _user_txns_stmt(
            select(Transaction),
            tenant_id=tenant_id,
            account_ids=scope_account_ids if scope_account_ids is not None else account_ids,
            currency=currency,
            reference=reference,
        )
        # Tie-break on id so a fixed window never duplicates or drops rows
        # created in the same instant (same contract as the queue windows).
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .offset(offset)
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

    # Map each other-side account to its OWNING user. System / provider
    # counterparts have user_id IS NULL and so never appear here — which is
    # what keeps a system leg from ever resolving to a name.
    other_account_ids: set[UUID] = set()
    own_account_set = set(account_ids)
    for entries in entries_by_txn.values():
        for e in entries:
            if e.account_id not in own_account_set:
                other_account_ids.add(e.account_id)

    user_id_by_account: dict[UUID, UUID] = {}
    # Label for every OTHER-side account, user-owned or not. A system pool or a
    # merchant collection account has no owning user and so can never produce a
    # name — without a label it left the counterparty column blank, which is
    # what made a commission withdrawal or a merchant cash-in read as "—".
    label_by_account: dict[UUID, str] = {}
    if other_account_ids:
        cp_rows = await session.execute(
            select(Account.id, Account.user_id, Account.account_type, Account.name).where(
                Account.id.in_(other_account_ids),
                Account.tenant_id == tenant_id,
            )
        )
        for acct_id, owner_id, acct_type, acct_name in cp_rows.all():
            label_by_account[acct_id] = account_label(acct_type, acct_name)
            if owner_id is not None:
                user_id_by_account[acct_id] = owner_id

    # The viewer's own accounts, labelled too: a commission disbursement moves
    # between two wallets of the SAME user, so the only meaningful counterparty
    # is the other wallet.
    own_rows = (
        await session.execute(
            select(
                Account.id, Account.account_type, Account.name, Account.currency
            ).where(Account.id.in_(account_ids))
        )
    ).all()
    own_label_by_account = {
        acct_id: account_label(acct_type, acct_name)
        for acct_id, acct_type, acct_name, _ in own_rows
    }
    own_type_by_account = {acct_id: acct_type for acct_id, acct_type, _, _ in own_rows}
    # The row reports the movement on ONE wallet, so its currency is that
    # wallet's — not the transaction's, which can differ on a mixed-unit flow.
    own_currency_by_account = {
        acct_id: currency for acct_id, _, _, currency in own_rows
    }

    counterparty_user_ids = set(user_id_by_account.values())
    name_by_user = await _resolve_counterparty_names(
        session, tenant_id=tenant_id, user_ids=counterparty_user_ids
    )
    phone_by_user: dict[UUID, str] = {}
    if include_counterparty_phone:
        phone_by_user = await _resolve_counterparty_phones(
            session, tenant_id=tenant_id, user_ids=counterparty_user_ids
        )

    movement_filter = set(movement_account_ids) if movement_account_ids is not None else None

    payload: list[dict[str, Any]] = []
    for t in txns:
        entries = entries_by_txn.get(t.id, [])

        # NET the caller's movement PER OWN ACCOUNT. One transaction can touch
        # several of their wallets — an agent's cash-in DEBITs their main wallet
        # for the principal and CREDITs their commission wallet with what they
        # earned — and it can hit the same account twice (principal + fee). One
        # row per wallet is what the panel already promises ("movements on this
        # user's wallets") and is the only shape in which the amount, the
        # direction and the wallet are each unambiguous.
        net_by_account: dict[UUID, Decimal] = {}
        for e in entries:
            if e.account_id not in own_account_set:
                continue
            signed = Decimal(str(e.amount)) if e.entry_type == "CREDIT" else -Decimal(str(e.amount))
            net_by_account[e.account_id] = net_by_account.get(e.account_id, Decimal("0")) + signed

        # A transaction reached here because it touches an account of theirs, so
        # an empty map means every leg netted to zero — nothing moved, nothing
        # to show.
        movements = [(acct_id, net) for acct_id, net in net_by_account.items() if net != 0]
        if movement_filter is not None:
            movements = [m for m in movements if m[0] in movement_filter]
        if not movements:
            continue

        # Sender / receiver, so a row the caller is NOT a party to can still be
        # read. Only surfaced in that case — a p2p sender does not need to be
        # told they were the sender.
        sender_name, receiver_name, caller_is_principal = _resolve_principals(
            entries=entries,
            user_id_by_account=user_id_by_account,
            name_by_user=name_by_user,
            own_account_set=own_account_set,
        )

        counterparty_name, counterparty_phone = _resolve_row_counterparty(
            entries=entries,
            own_account_set=own_account_set,
            label_by_account=label_by_account,
            user_id_by_account=user_id_by_account,
            name_by_user=name_by_user,
            phone_by_user=phone_by_user,
            own_label_by_account=own_label_by_account,
        )

        # Perspective rule: fee + tax are borne by the INITIATOR; commission is
        # EARNED. Each is now attached to the WALLET it actually moved through,
        # so a cash-in reports the fee against the wallet that paid it and the
        # commission against the wallet that received it.
        is_initiator = t.initiated_by == user_id
        # Did this transaction credit one of the caller's COMMISSION wallets?
        # If so the commission has a leg of its own and needs no type map.
        earned_into_commission_wallet = any(
            own_type_by_account.get(acct_id) == ACCOUNT_TYPE_COMMISSION_WALLET and net > 0
            for acct_id, net in movements
        )

        for account_id, net in movements:
            account_type = own_type_by_account.get(account_id, "")
            is_commission_wallet = account_type == ACCOUNT_TYPE_COMMISSION_WALLET

            # Charges ride the wallet that bore them, never the earning wallet.
            fee_out = str(t.fee_amount) if is_initiator and not is_commission_wallet else "0"
            tax_out = str(t.tax_amount) if is_initiator and not is_commission_wallet else "0"

            if is_commission_wallet and net > 0:
                # The leg IS the commission — no need to guess from the service
                # code, and this is what finally surfaces a supervisor's parent
                # commission, which the old cash_in/cashout map never covered.
                commission_out = str(net)
            elif earned_into_commission_wallet:
                # Already reported on its own row above; don't double-count it
                # against the wallet that merely paid the principal.
                commission_out = "0"
            elif t.transaction_type == "cash_in" and is_initiator:
                # A rule paying into the MAIN wallet has no separate leg, so the
                # pre-commission-wallet attribution still applies:
                #  - cash_in: the agent INITIATES the deposit and earns it.
                #  - cashout: the agent RECEIVES the cashed-out leg + it.
                commission_out = str(t.commission_amount)
            elif t.transaction_type == "cashout" and net > 0:
                commission_out = str(t.commission_amount)
            else:
                commission_out = "0"

            payload.append(
                {
                    "id": t.id,
                    "reference": t.reference,
                    "transaction_type": t.transaction_type,
                    "base_transaction_type": t.base_transaction_type,
                    "status": t.status,
                    # The caller's OWN movement on this wallet — NOT the
                    # transaction's headline. A supervisor earning R0.50 of
                    # parent commission on a R100 cash-in must read R0.50.
                    "amount": str(abs(net)),
                    # The headline principal, kept but clearly separate so it
                    # can never stand in for the amount again.
                    "transaction_amount": str(t.amount),
                    "fee_amount": fee_out,
                    "commission_amount": commission_out,
                    "tax_amount": tax_out,
                    "currency": own_currency_by_account.get(account_id, t.currency),
                    "created_at": t.created_at,
                    # Derived from THIS wallet's net, so it no longer depends on
                    # which leg the ledger query happened to return first.
                    "direction": "in" if net > 0 else "out",
                    "wallet_account_id": account_id,
                    "wallet_account_type": account_type,
                    "wallet_label": own_label_by_account.get(account_id),
                    "counterparty_name": counterparty_name,
                    # Populated ONLY when the caller is a third party to the
                    # transaction — the parent-commission case. Otherwise the
                    # single counterparty already says what they need.
                    "sender_name": None if caller_is_principal else sender_name,
                    "receiver_name": None if caller_is_principal else receiver_name,
                    **(
                        {"counterparty_phone": counterparty_phone}
                        if include_counterparty_phone
                        else {}
                    ),
                }
            )
        if include_counterparty_phone:
            payload[-1]["counterparty_phone"] = counterparty_phone
    return payload


async def list_user_transactions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
    currency: str | None = None,
    reference: str | None = None,
    wallet_type: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of a user's wallet movements + the total matching count.

    Resolves the user's accounts then delegates to the same payload
    builder the mobile /me/wallet endpoint uses, so the response shape
    stays consistent across admin and user surfaces.

    Args:
        tenant_id: Required for tenant isolation; cross-tenant lookups
            return UserNotFound (404).
        user_id: Target user.
        limit: Page size. The admin panel pages 20 at a time.
        offset: Rows to skip — `page * limit`.
        currency: Optional exact currency filter ("ZAR" / "INR" / "PTS").
        reference: Optional case-insensitive reference substring search.

    Returns:
        `(rows, total)`, where `rows` are WALLET MOVEMENTS shaped to match
        `AdminUserTransactionOut` (including `counterparty_phone`, which the
        user-facing feed omits) and `total` counts TRANSACTIONS.

        The two differ deliberately. Pagination is over transactions — one page
        is `limit` transactions — but a transaction that touches several of the
        caller's wallets yields one row each, so `len(rows) >= limit` is normal
        and `total` is not a row count. A caller rendering a footer should say
        "of N transactions", not "of N rows".

    Raises:
        UserNotFound: user_id is unknown or belongs to a different tenant.
    """
    from app.shared.models import Account

    user_q = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    if user_q.scalar_one_or_none() is None:
        raise UserNotFound()

    accounts_q_rows = (
        await session.execute(
            select(Account.id, Account.account_type).where(
                Account.tenant_id == tenant_id, Account.user_id == user_id
            )
        )
    ).all()
    account_ids = [acct_id for acct_id, _ in accounts_q_rows]

    # The Main / Commission wallet filter narrows which of the caller's wallets
    # may produce rows, and which transactions are worth fetching at all — but
    # NOT what counts as the caller's own leg (see `movement_account_ids`).
    movement_account_ids: list[UUID] | None = None
    scope_ids = account_ids
    if wallet_type is not None:
        movement_account_ids = [
            acct_id for acct_id, acct_type in accounts_q_rows if acct_type == wallet_type
        ]
        scope_ids = movement_account_ids

    rows = await _build_recent_txns_payload(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        account_ids=account_ids,
        limit=limit,
        offset=offset,
        currency=currency,
        reference=reference,
        # Admin surface: operators tracing a transfer need the counterparty's
        # number. The user-facing /me/wallet feed leaves this off.
        include_counterparty_phone=True,
        movement_account_ids=movement_account_ids,
        scope_account_ids=scope_ids,
    )
    total = await _count_user_txns(
        session,
        tenant_id=tenant_id,
        account_ids=scope_ids,
        currency=currency,
        reference=reference,
    )
    return rows, total


async def list_user_reports(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """The users who report to `user_id` — their downline (spec B12.2).

    The hierarchy was only ever readable upwards: a user knew their supervisor,
    but a supervisor could not see who fed them. That matters more since parent
    commission started paying supervisors off this same link — an operator
    reconciling a commission run had no way to answer "which agents feed this
    super-agent?" without querying the database.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope. A child in another tenant can never appear
            (NFR-0220) — `parent_user_id` carries no tenant of its own, so the
            filter is what enforces isolation here.
        user_id: The supervisor.
        limit / offset: Page window.

    Returns:
        `(rows, total)` — each row carries the child's id, display name, type
        and status, plus their accrued commission per currency so a supervisor's
        page answers "who feeds this?" and "by how much?" together.

    Raises:
        UserNotFound: 404 — unknown user, or one in another tenant.
    """
    from app.modules.accounts.service import derive_balance
    from app.shared.models import ACCOUNT_TYPE_COMMISSION_WALLET, Account, User

    parent = (
        await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if parent is None:
        raise UserNotFound()

    base = select(User).where(
        User.tenant_id == tenant_id, User.parent_user_id == user_id
    )
    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()

    children = list(
        (
            await session.execute(
                base.order_by(User.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not children:
        return [], total

    child_ids = [c.id for c in children]
    names = await resolve_user_names(session, tenant_id=tenant_id, user_ids=set(child_ids))

    # Accrued commission per child, so the list answers the reconciliation
    # question rather than stopping one step short of it.
    wallets = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id.in_(child_ids),
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalars().all()
    accrued: dict[UUID, dict[str, str]] = {}
    for wallet in wallets:
        # `Account.user_id` is nullable on the model (system accounts have
        # none). The query filters to child ids so it is never None here, but
        # skip rather than assert — a system account creeping in should drop
        # out of a per-user total, not crash the page.
        if wallet.user_id is None:
            continue
        balance, reserved = await derive_balance(session, wallet.id)
        accrued.setdefault(wallet.user_id, {})[wallet.currency] = str(balance - reserved)

    return [
        {
            "id": child.id,
            "name": names.get(child.id),
            "user_type": child.user_type,
            "status": child.status,
            "created_at": child.created_at,
            "accrued_commission": accrued.get(child.id, {}),
        }
        for child in children
    ], total


async def admin_reset_pin(
    session: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> dict[str, Any]:
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
    from app.auth.lockout import clear_lockout
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

    # A reset FULLY unlocks the user — clear the active lockout key AND the
    # counter (reset_failures alone only cleared the counter, so a locked user
    # stayed locked until the TTL expired despite the new PIN — a real bug).
    await clear_lockout(user_id)

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


async def admin_unlock_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Release a user's PIN lockout WITHOUT changing their PIN (admin override).

    Unlike `admin_reset_pin`, this keeps the user's existing PIN — it only
    clears the Redis lockout key + failure counter so a user locked by failed
    attempts can retry immediately. Writes an `admin.user_unlocked` audit row.

    Args:
        user_id: Target user.
        tenant_id: Caller's tenant; the user must belong to it.
        admin: Authenticated admin principal (audit actor).
        ip_address: Caller IP for audit.

    Returns:
        {"user_id", "was_locked"} — `was_locked` reflects the lock state before
        the clear, so the UI can tell the operator whether anything changed.

    Raises:
        UserNotFound: user unknown or belongs to another tenant.

    Side effects:
        Deletes the Redis lockout + counter keys; writes one audit row.
    """
    from app.auth.lockout import clear_lockout, is_locked
    from app.modules.audit.service import record_audit_for_admin

    user_q = await session.execute(
        select(User.id).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    if user_q.scalar_one_or_none() is None:
        raise UserNotFound()

    was_locked = await is_locked(user_id)
    await clear_lockout(user_id)

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="admin.user_unlocked",
        entity_type="user",
        entity_id=str(user_id),
        after_state={"was_locked": was_locked},
        ip_address=ip_address,
    )
    await session.commit()
    return {"user_id": user_id, "was_locked": was_locked}


async def set_user_access_level(
    session: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    level: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Immediately set a user's admin access level (login / transactions lock).

    Not maker-checker — this is an immediate, audited platform-admin override
    (see the separate `/unlock` route for the Redis PIN-lockout release, which
    this does NOT touch). Maps `level` to `user.status`, persists it, and when
    the new level is `login_locked` (status suspended) kills every live session
    for the user so the lock takes effect NOW rather than at token expiry.

    Args:
        session: Async DB session (committed here).
        user_id: Target user.
        tenant_id: Caller's tenant; the user must belong to it.
        level: One of `active` / `login_locked` / `transactions_locked`.
        admin: Authenticated platform-admin (audit actor).
        ip_address: Caller IP recorded on the audit row.

    Returns:
        `{"user_id", "status", "level"}` reflecting the applied state.

    Raises:
        UserNotFound: 404 — unknown user or a user in another tenant.

    Side effects:
        Updates `users.status`; on `login_locked` revokes all Redis sessions for
        the user; writes one `admin.user_access_changed` audit row with the
        before/after status and the count of sessions killed.
    """
    from app.modules.audit.service import record_audit_for_admin

    new_status = ACCESS_LEVEL_TO_STATUS[level]

    result = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()

    before_status = user.status
    user.status = new_status

    # Kill sessions BEFORE commit is fine — Redis is separate from the DB txn and
    # a login-lock must take effect immediately (invariant: locked user's live
    # session dies now). Only login_locked needs this; txn_locked can still read.
    sessions_killed = 0
    if level == "login_locked":
        sessions_killed = await invalidate_user_sessions(user_id)

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="admin.user_access_changed",
        entity_type="user",
        entity_id=str(user_id),
        before_state={"status": before_status},
        after_state={"status": new_status, "sessions_killed": sessions_killed},
        ip_address=ip_address,
    )
    await session.commit()

    return {"user_id": user_id, "status": new_status, "level": level}


async def add_user_identifier(
    session: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> UserIdentifier:
    """Add a post-registration identifier to an existing user (Epic 27, Story 27.1).

    Registration requires a contactable identifier; account_number is added
    afterwards through this admin path. The identifier is stored with
    `verified=False` — an admin-added identifier is NOT OTP/verification-proven
    (account_number gets its own verification flow in Story 27.3). `card_number`
    never reaches here: the request schema's Literal excludes it so a raw PAN is
    rejected at validation (PCI — only a tokenised ref, Phase 2).

    The value is normalised with the SAME helper `create_user` uses, so the
    canonical form is what hits the `(tenant, type, value)` unique constraint and
    every future lookup. On collision we catch the IntegrityError and re-raise a
    clean 409 (mirrors `create_user`).

    Args:
        session: Async DB session (committed here on success).
        user_id: Target user; must belong to `tenant_id`.
        tenant_id: Caller's tenant; a user in another tenant is treated as unknown.
        identifier_type: One of phone / email / account_number (card excluded).
        identifier_value: The raw value; normalised before persistence.
        admin: Authenticated platform-admin — the audit actor.
        ip_address: Caller IP recorded on the audit row.

    Returns:
        The newly-created UserIdentifier row (maps to `IdentifierOut`).

    Raises:
        UserNotFound: 404 — unknown user or a user in another tenant.
        IdentifierAlreadyInUse: 409 — the (tenant, type, value) tuple already
            maps to a user in this tenant (Pay-PRD-0070).

    Side effects:
        Inserts one `user_identifiers` row and writes one `user.identifier_added`
        audit row. The raw identifier value is NEVER written to the audit
        after_state (NFR-0170 / NFR-0240) — the type is enough.
    """
    from app.modules.audit.service import record_audit_for_admin

    # Tenant-scoped existence check — a user in another tenant returns 404 with
    # no existence leak (NFR-0220), before we touch the identifiers table.
    result = await session.execute(
        select(User.id).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise UserNotFound()

    # Normalise BEFORE persistence so the canonical form is what hits the unique
    # constraint + every future lookup (identical to create_user).
    canonical = normalize_identifier(identifier_type, identifier_value)
    session.add(
        UserIdentifier(
            user_id=user_id,
            tenant_id=tenant_id,
            identifier_type=identifier_type,
            identifier_value=canonical,
            verified=False,
        )
    )

    try:
        await session.flush()
    except IntegrityError as exc:
        # The (tenant, type, value) unique constraint is the only collision we
        # expect — roll back cleanly and surface a 409 (mirrors create_user).
        await session.rollback()
        raise IdentifierAlreadyInUse(identifier_type) from exc

    # NFR-0170 / NFR-0240: audit the fact + type, NEVER the raw value (PII).
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="user.identifier_added",
        entity_type="user",
        entity_id=str(user_id),
        after_state={"identifier_type": identifier_type, "verified": False},
        ip_address=ip_address,
    )

    await session.commit()

    # Re-select AFTER commit so the returned row is a fresh, non-expired instance
    # (mirrors `_reload_user` — attributes are safe to read for the response).
    added = await _find_identifier(session, tenant_id, identifier_type, canonical)
    if added is None:  # pragma: no cover - flush above guarantees the row exists
        raise UserNotFound()
    return added


async def verify_user_identifier(
    session: AsyncSession,
    *,
    user_id: UUID,
    identifier_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> UserIdentifier:
    """Manually mark an `account_number` identifier verified (Epic 27, Story 27.3).

    `account_number` identifiers added post-registration have NO automated
    verification flow (unlike phone/email, which the OTP flow proves), so they
    stay `verified=False` forever. This admin action is the manual stub that
    marks one verified. NOTE: this is a MANUAL stub — the real
    micro-deposit / partner-confirmation verification flow is a later phase; for
    now an admin attests the account out-of-band and flips the flag here.

    Idempotency is state-based: an already-verified identifier is a no-op — it is
    returned unchanged and NO second audit row is written, so a double-click is
    safe (chosen over a 409 so retries never surface an error).

    Args:
        session: Async DB session (committed here on a real change).
        user_id: The owning user; the identifier must belong to it.
        identifier_id: The identifier to verify.
        tenant_id: Caller's tenant; an identifier in another tenant is unknown.
        admin: Authenticated platform-admin — the audit actor.
        ip_address: Caller IP recorded on the audit row.

    Returns:
        The verified UserIdentifier row (maps to `IdentifierOut`).

    Raises:
        UserNotFound: 404 — no such identifier for this (user, tenant), whether
            the id is unknown, belongs to another user, or lives in another
            tenant (no existence leak, NFR-0220).
        IdentifierNotManuallyVerifiable: 422 — the identifier is not an
            account_number (phone/email verify via OTP; card is never a plain
            identifier).

    Side effects:
        On a real change: sets `verified=True` and writes one
        `admin.identifier_verified` audit row with before/after verified and the
        identifier TYPE only — the raw value is NEVER written (NFR-0170).
    """
    from app.modules.audit.service import record_audit_for_admin

    # Tenant- AND user-scoped lookup: a wrong tenant, wrong user, or unknown id
    # all collapse to 404 with no existence leak (NFR-0220).
    result = await session.execute(
        select(UserIdentifier).where(
            UserIdentifier.id == identifier_id,
            UserIdentifier.user_id == user_id,
            UserIdentifier.tenant_id == tenant_id,
        )
    )
    identifier = result.scalar_one_or_none()
    if identifier is None:
        raise UserNotFound()

    # Only account_number has a manual admin-verification path.
    if identifier.identifier_type != "account_number":
        raise IdentifierNotManuallyVerifiable()

    # State-based idempotency: already verified → no-op, no audit row.
    if identifier.verified:
        return identifier

    identifier.verified = True

    # NFR-0170: audit the fact + type + before/after flag, NEVER the raw value.
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="admin.identifier_verified",
        entity_type="user",
        entity_id=str(user_id),
        before_state={"identifier_type": identifier.identifier_type, "verified": False},
        after_state={"identifier_type": identifier.identifier_type, "verified": True},
        ip_address=ip_address,
    )
    await session.commit()

    # Re-select AFTER commit so the returned row is a fresh, non-expired instance.
    reloaded = await session.execute(
        select(UserIdentifier).where(UserIdentifier.id == identifier_id)
    )
    verified = reloaded.scalar_one_or_none()
    if verified is None:  # pragma: no cover - the commit above guarantees the row
        raise UserNotFound()
    return verified


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


async def _autocreate_user_with_phone(
    session: AsyncSession,
    tenant_id: UUID,
    phone: str,
    *,
    referral_code: str | None = None,
) -> User:
    """First-time user: create on-the-fly when /otp/send hits an unknown phone.

    Matches Pay-PRD-0010 semantics — registration is a side-effect of the first
    OTP for that phone. Delegates to `create_user` with `self_registration=True`
    so the new user gets their own shareable referral code and, when a
    `referral_code` is supplied, a PENDING referral link (attribution only). NO
    reward fires here — it fires later at PIN-set once the phone is verified and
    signup is complete (anti-farming).

    A bad `referral_code` raises `InvalidReferralCode` / `SelfReferralNotAllowed`
    from WITHIN `create_user` BEFORE its commit, so the whole registration rolls
    back cleanly — no half-created user is left behind.

    Args:
        referral_code: Optional referrer's code to attribute this signup to.

    Raises:
        InvalidReferralCode: 422 — the quoted code does not resolve in the tenant.
        SelfReferralNotAllowed: 422 — the code belongs to the new user (cannot
            happen here since the code is created for the referrer first).
    """
    return await create_user(
        session,
        CreateUserRequest(
            tenant_id=tenant_id,
            identifiers=[
                # verified=False — the phone is confirmed only after /otp/verify.
                IdentifierIn(identifier_type="phone", identifier_value=phone, verified=False)
            ],
            referral_code=referral_code,
        ),
        self_registration=True,
    )


async def send_otp(session: AsyncSession, request: OtpSendRequest) -> OtpSendResponse:
    """Generate, store, and 'deliver' a one-time password.

    Auto-registers the phone if it's not already known in this tenant
    (Pay-PRD-0010), attributing an optional `referral_code` on that first-time
    registration only. Rate-limited per phone via Redis.

    Args:
        session: Async DB session.
        request: Validated payload (may carry an optional `referral_code`).

    Returns:
        Response indicating delivery; in local-dev mode the OTP itself is
        included so tests and manual demos can verify without an SMS gateway.

    Raises:
        TenantNotFound: 404 when tenant is unknown.
        OtpRateLimited: 429 when this phone has requested too many OTPs.
        InvalidReferralCode: 422 when a NEW phone quotes an unresolvable code —
            the auto-registration rolls back, leaving no half-created user.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    user = await _find_user_by_phone(session, request.tenant_id, request.phone)

    # FIX 4: validate a NEW phone's referral code BEFORE consuming the OTP quota,
    # so a typo'd code 422s without locking the phone out for ~60s. Only a new
    # phone uses the code — an existing user's OTP re-request ignores it.
    if user is None and request.referral_code:
        await _assert_referral_code_exists(
            session, tenant_id=request.tenant_id, code=request.referral_code
        )

    allowed, retry_after = await consume_otp_send_quota(request.phone)
    if not allowed:
        raise OtpRateLimited(retry_after)

    if user is None:
        # New phone → register it, attributing an optional referral. An EXISTING
        # phone deliberately skips this, so `referral_code` is ignored for a
        # returning user (an OTP re-request must not alter an established user).
        user = await _autocreate_user_with_phone(
            session,
            request.tenant_id,
            request.phone,
            referral_code=request.referral_code,
        )

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
    # set_pin ONLY sets the INITIAL registration PIN — a user who already has one
    # is rejected here (PIN changes/resets go through their own paths). This makes
    # the referral reward below fire at most once per user: a later change-PIN can
    # never re-enter this branch, and the reward itself also gates on a PENDING
    # referral, so re-reward is impossible on both counts.
    if user.pin_hash is not None:
        raise PinAlreadySet()

    tenant_id = user.tenant_id
    user.pin_hash = hashing.hash_pin(request.pin)
    await session.commit()

    # Registration is now COMPLETE (phone verified via OTP + PIN set), so pay any
    # PENDING referral this user was signed up under — BOTH sides. Post-commit +
    # fail-open (NFR-0130): a reward error must never break PIN-set; the referral
    # stays PENDING and is reconcilable later. Admin/external users never reach
    # this path, so they are never rewarded.
    from app.modules.rules.referral_evaluator import (
        evaluate_referral_on_registration_complete,
    )

    try:
        await evaluate_referral_on_registration_complete(
            session, tenant_id=tenant_id, referred_user_id=user_id
        )
    except Exception:
        await session.rollback()
        log.warning(
            "referral_signup_reward_failed",
            user_id=str(user_id),
            tenant_id=str(tenant_id),
        )


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

    # Admin login-lock (migration 0045). A `suspended` or `closed` account may
    # NOT authenticate — reject before PIN verification so a locked account never
    # reaches credential checking. `txn_locked` and `active` may log in (a
    # txn_locked user can still read; their money paths are blocked separately).
    if user.status in (USER_STATUS_SUSPENDED, USER_STATUS_CLOSED):
        raise AccountSuspended()

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
