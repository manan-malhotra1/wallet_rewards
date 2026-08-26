"""User-type catalog service — lookup, visibility, validation and mutation.

A tenant's visible types are the platform-wide system types (tenant_id IS NULL)
plus its own. Retired types are excluded from pickers but stay resolvable, so an
existing user or config row referencing one never falls through to the
`user_type IS NULL` default (spec §11).

The two mutation entry points (`create_user_type`, `replace_user_type_for_scope`)
match the `_CreateFn` / `_ReplaceFn` signatures in `config_requests/apply.py`, so
every write arrives through maker-checker (spec D4). Both commit, exactly like
every sibling config service: `approve_config_request` stages the request's
PENDING → APPLIED transition, the review row and the audit row *before* handing
off, and relies on the config service's single commit to persist all of it
atomically. Without that commit an approved change would silently not persist.
There is deliberately no delete: spec D3 retires types instead.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.shared.exceptions import (
    AppHTTPException,
    CategoryDoesNotSupportHierarchy,
    ParentTypeNotFound,
    ParentTypeNotTopLevel,
    ParentTypeWrongCategory,
    UnknownUserType,
    UnknownUserTypeCategory,
    UserTypeCategoryImmutable,
    UserTypeCodeAlreadyExists,
    UserTypeCodeReserved,
    UserTypeHasActiveChildren,
    UserTypeHasChildren,
)
from app.shared.models import (
    CATEGORY_BUSINESS,
    CATEGORY_RETAIL,
    USER_TYPE_STATUS_ACTIVE,
    USER_TYPE_STATUS_RETIRED,
    UserTypeCategory,
    UserTypeDef,
)


def _visible_to_tenant(tenant_id: UUID) -> ColumnElement[bool]:
    """Build the visibility predicate: platform-wide system types plus a tenant's own.

    The single definition of what a tenant may see. A system type has
    `tenant_id IS NULL` and belongs to everyone; anything else belongs to
    exactly one tenant and must never leak across the boundary (NFR-0220).

    Args:
        tenant_id: The acting tenant.

    Returns:
        A SQLAlchemy boolean expression for a `WHERE` clause over `user_types`.
    """
    return or_(UserTypeDef.tenant_id.is_(None), UserTypeDef.tenant_id == tenant_id)


async def list_user_types(
    session: AsyncSession, tenant_id: UUID, *, include_retired: bool = False
) -> list[UserTypeDef]:
    """Return every user type visible to a tenant.

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant.
        include_retired: When True, retired types are included. Use this when
            rendering an existing config row so a retired type still shows its
            label rather than a raw code.

    Returns:
        System types plus the tenant's own, grouped into category sections in
        the categories' `display_order` (Consumers, Retail, Business) and
        alphabetical by label within each section.
    """
    # Ordering by `category_code` would sort the sections alphabetically
    # (business, consumer, retail). Spec §9 wants them in the operator-facing
    # `display_order`, so the caller renders the list as-is without re-sorting.
    stmt = (
        select(UserTypeDef)
        .join(UserTypeCategory, UserTypeCategory.code == UserTypeDef.category_code)
        .where(_visible_to_tenant(tenant_id))
    )
    if not include_retired:
        stmt = stmt.where(UserTypeDef.status == USER_TYPE_STATUS_ACTIVE)
    stmt = stmt.order_by(UserTypeCategory.display_order, UserTypeDef.label)
    return list((await session.execute(stmt)).scalars().all())


async def get_user_type(session: AsyncSession, tenant_id: UUID, code: str) -> UserTypeDef | None:
    """Resolve one type code for a tenant, retired included, or None.

    Retired types deliberately still resolve here. If they did not, an existing
    user carrying a retired type would fall through to the `user_type IS NULL`
    default config row and silently get default pricing and limits instead of
    being refused (spec §11).

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant — another tenant's custom type never resolves.
        code: The type code as stored on `users.user_type` / config rows.

    Returns:
        The matching row, preferring the tenant's own over a system type of the
        same code, or None when the code is not visible to this tenant.
    """
    stmt = (
        select(UserTypeDef)
        .where(UserTypeDef.code == code, _visible_to_tenant(tenant_id))
        # A tenant row sorts before the system row (NULLs last), so a tenant
        # override wins if one somehow exists.
        .order_by(UserTypeDef.tenant_id.is_(None))
    )
    return (await session.execute(stmt)).scalars().first()


async def is_commission_wallet_eligible(
    session: AsyncSession, tenant_id: UUID, code: str
) -> bool:
    """Does a user of this type hold a commission wallet? (spec 2026-08-26, D4)

    Eligibility is a CATEGORY question: Retail and Business hold commission
    wallets, Consumers never do. Reading the category rather than a hardcoded
    type list is what lets an operator-created Business type work with no code
    change — the exact coupling the configurable-user-types edition removed.

    A RETIRED type is still eligible: an agent onboarded under a type the
    operator has since retired must keep accruing, exactly as `get_user_type`
    keeps existing users working (user-types spec §11).

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant.
        code: The user's `user_type`.

    Returns:
        True when the type resolves to the Retail or Business category. False —
        never an exception — for a type that does not resolve, so provisioning
        degrades to "no commission wallet" instead of failing with a 500.
    """
    row = await get_user_type(session, tenant_id, code)
    return row is not None and row.category_code in (CATEGORY_RETAIL, CATEGORY_BUSINESS)


async def assert_user_type_valid(
    session: AsyncSession, *, tenant_id: UUID, code: str
) -> UserTypeDef:
    """Refuse a type that cannot be WRITTEN onto a user or a config row (spec §6).

    This is the application-level replacement for the dropped
    `ck_users_user_type` CHECK. It must run on every path that writes or changes
    a `user_type`, because nothing at the database level stops a bogus string
    reaching the `users` table any more. A user carrying an unresolvable type
    would fall through to the `user_type IS NULL` default config row and quietly
    get default pricing and limits instead of being refused (spec §11).

    Stricter than `get_user_type`: a RETIRED type still resolves for reads (an
    existing user must keep working) but may not be assigned to anything new.

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant. Another tenant's custom type is refused
            identically to a nonexistent one — no existence leak.
        code: The proposed type code.

    Returns:
        The resolved, active `UserTypeDef` row, so the caller can read
        `parent_type_code` / `category_code` without a second query.

    Raises:
        UnknownUserType: 422 — the code does not resolve for this tenant, or it
            resolves to a retired type.
    """
    row = await get_user_type(session, tenant_id, code)
    if row is None or row.status != USER_TYPE_STATUS_ACTIVE:
        raise UnknownUserType()
    return row


async def assert_optional_user_type_valid(
    session: AsyncSession, *, tenant_id: UUID, code: str | None
) -> None:
    """Validate the `user_type` on a config row, treating None as "everyone".

    The config-write half of spec §6. Every limit / wallet-limit / pricing /
    commission create and update calls this, because config resolution matches
    `user_type` as a bare string: a row written against a typo'd or nonexistent
    type never matches anything, and the transaction silently falls through to
    the `user_type IS NULL` default row (spec §11). The operator is left staring
    at a saved config that does nothing.

    Args:
        session: Async DB session (read-only).
        tenant_id: The tenant the config belongs to.
        code: The type the config is scoped to, or None for the default row that
            applies to every type — which is always valid and skips the lookup.

    Raises:
        UnknownUserType: 422 — a code was given but does not resolve to an
            active type for this tenant.
    """
    if code is None:
        return
    await assert_user_type_valid(session, tenant_id=tenant_id, code=code)


async def _assert_code_available(session: AsyncSession, *, code: str) -> None:
    """Refuse a code already owned by a platform-wide system type.

    Split out from `assert_type_definition_valid` so an UPDATE — which keeps the
    row's existing, immutable code — can re-run the hierarchy rules alone
    without the row colliding with itself.

    Args:
        session: Async DB session (read-only).
        code: The proposed code.

    Raises:
        UserTypeCodeReserved: a system type already owns the code.
    """
    system = (
        await session.execute(
            select(UserTypeDef).where(UserTypeDef.code == code, UserTypeDef.tenant_id.is_(None))
        )
    ).scalar_one_or_none()
    if system is not None:
        raise UserTypeCodeReserved()


async def _assert_hierarchy_valid(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    category_code: str,
    parent_type_code: str | None,
) -> None:
    """Enforce the cross-row hierarchy rules that look at the NAMED PARENT (spec §5).

    Half of the two-level cap. This end of the edge asks "is the parent I am
    being attached to a valid, top-level, same-category type?". The other end —
    "is the row being attached itself a parent?" — is `_assert_has_no_children`,
    which only the re-parent path needs (a freshly created type has no children).

    Args:
        session: Async DB session (read-only).
        tenant_id: The tenant the type belongs to.
        category_code: The category the type sits in.
        parent_type_code: The parent type, or None for a top-level type.

    Raises:
        UnknownUserTypeCategory: the category code does not exist.
        CategoryDoesNotSupportHierarchy: a parent was given for a flat category.
        ParentTypeNotFound: the parent does not resolve, or is retired.
        ParentTypeWrongCategory: the parent is in a different category.
        ParentTypeNotTopLevel: the parent is itself a child (two-level cap).
    """
    category = (
        await session.execute(
            select(UserTypeCategory).where(UserTypeCategory.code == category_code)
        )
    ).scalar_one_or_none()
    if category is None:
        raise UnknownUserTypeCategory()

    if parent_type_code is None:
        return

    if not category.supports_hierarchy:
        raise CategoryDoesNotSupportHierarchy()

    parent = await get_user_type(session, tenant_id, parent_type_code)
    if parent is None or parent.status != USER_TYPE_STATUS_ACTIVE:
        raise ParentTypeNotFound()
    if parent.category_code != category_code:
        raise ParentTypeWrongCategory()
    # Half the two-level guarantee: a parent must itself be top-level. No depth
    # counter, no recursion. The other half is `_assert_has_no_children`, without
    # which a parent could simply be moved under another parent instead.
    if parent.parent_type_code is not None:
        raise ParentTypeNotTopLevel()


async def assert_type_definition_valid(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    code: str,
    category_code: str,
    parent_type_code: str | None = None,
) -> None:
    """Enforce the code-collision and named-parent hierarchy rules from spec §5.

    The full rule set that applies to a NEW type. An update calls
    `_assert_hierarchy_valid` on its own instead, because an existing row's code
    is immutable (spec D5) and re-checking it here would trip the collision rule
    on the row itself; it also adds `_assert_has_no_children`, which is
    vacuously true for a row that does not exist yet.

    Args:
        session: Async DB session.
        tenant_id: The tenant proposing the type.
        code: The proposed code.
        category_code: The category the type sits in.
        parent_type_code: The parent type, or None for a top-level type.

    Raises:
        UserTypeCodeReserved: the code belongs to a system type.
        UnknownUserTypeCategory: the category code does not exist.
        CategoryDoesNotSupportHierarchy: a parent was given for a flat category.
        ParentTypeNotFound: the parent does not resolve, or is retired.
        ParentTypeWrongCategory: the parent is in a different category.
        ParentTypeNotTopLevel: the parent is itself a child (two-level cap).
    """
    await _assert_code_available(session, code=code)
    await _assert_hierarchy_valid(
        session,
        tenant_id=tenant_id,
        category_code=category_code,
        parent_type_code=parent_type_code,
    )


def _type_state(row: UserTypeDef) -> dict[str, object]:
    """Serialise the mutable half of a type row for an audit snapshot.

    Args:
        row: The type row.

    Returns:
        The fields an update may change, plus the code that identifies the row.
    """
    return {
        "code": row.code,
        "label": row.label,
        "status": row.status,
        "parent_type_code": row.parent_type_code,
    }


async def create_user_type(
    session: AsyncSession,
    request: UserTypeCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> UserTypeDef:
    """Create a tenant-scoped user type after validating it (spec §5).

    Signature matches `_CreateFn` in `config_requests/apply.py` so this is
    callable directly from the maker-checker dispatch table.

    Args:
        session: Async DB session.
        request: The validated proposed type.
        admin: The approving admin, when called from maker-checker — drives the
            audit row. None skips the audit (direct/service use).
        ip_address: Caller IP, recorded on the audit row.

    Returns:
        The persisted `UserTypeDef` row.

    Raises:
        UserTypeCodeReserved, UnknownUserTypeCategory, ParentTypeNotFound,
        ParentTypeWrongCategory, ParentTypeNotTopLevel,
        CategoryDoesNotSupportHierarchy: see spec §5.
        UserTypeCodeAlreadyExists: this tenant already owns the code.

    Side effects:
        Inserts a `user_types` row and one `user_type.created` audit row, then
        commits once. The commit also persists whatever the caller staged
        beforehand — for maker-checker that is the request's PENDING → APPLIED
        transition, its review row and its audit row, so the approval and the
        config write land atomically or not at all.
    """
    await assert_type_definition_valid(
        session,
        tenant_id=request.tenant_id,
        code=request.code,
        category_code=request.category_code,
        parent_type_code=request.parent_type_code,
    )
    row = UserTypeDef(
        tenant_id=request.tenant_id,
        code=request.code,
        label=request.label,
        category_code=request.category_code,
        is_system=False,
        status=request.status,
        parent_type_code=request.parent_type_code,
    )
    session.add(row)
    # `_assert_code_available` only guards platform-wide system codes, so a
    # tenant reusing its OWN code reaches `uq_user_types_tenant_code`. Left
    # unhandled the IntegrityError is a 500 AND poisons the session, rolling
    # back the approval this call was staged inside and stranding the request
    # on PENDING. Catching it here turns that into the 409 spec §12 requires.
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise UserTypeCodeAlreadyExists(request.code) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="user_type.created",
            entity_type="user_type",
            entity_id=str(row.id),
            after_state=_type_state(row),
            ip_address=ip_address,
        )

    await session.commit()
    return row


async def _load_mutable_type(session: AsyncSession, *, tenant_id: UUID, code: str) -> UserTypeDef:
    """Load the tenant's own type row for `code`, refusing system and missing ones.

    Args:
        session: Async DB session (read-only).
        tenant_id: The tenant that owns the type.
        code: The immutable join key identifying the row.

    Returns:
        The tenant-scoped `UserTypeDef` row.

    Raises:
        AppHTTPException 403: the code resolves, but only to a system type
            (tenant_id IS NULL), which is immutable (spec D2).
        AppHTTPException 404: no such type is visible to this tenant.
    """
    row = (
        await session.execute(
            select(UserTypeDef).where(UserTypeDef.tenant_id == tenant_id, UserTypeDef.code == code)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    # A system type has tenant_id IS NULL, so the tenant-scoped lookup above
    # misses it; distinguish "system, immutable" from "does not exist".
    if await get_user_type(session, tenant_id, code) is not None:
        raise AppHTTPException(403, "user_type_is_system", "System user types cannot be modified.")
    raise AppHTTPException(404, "user_type_not_found", "No such user type.")


async def _assert_no_active_children(
    session: AsyncSession, *, tenant_id: UUID, parent_code: str
) -> None:
    """Refuse retiring a parent that still has active children (spec §5 rule 4).

    Retiring it would strand the children under an inactive parent, and D3
    forbids deleting them as a way out — so the children must be retired first.

    Args:
        session: Async DB session (read-only).
        tenant_id: The tenant whose types are considered, alongside system ones.
        parent_code: The code of the type being retired.

    Raises:
        UserTypeHasActiveChildren: at least one active child points at it.
    """
    children = (
        (
            await session.execute(
                select(UserTypeDef.code).where(
                    UserTypeDef.parent_type_code == parent_code,
                    UserTypeDef.status == USER_TYPE_STATUS_ACTIVE,
                    # Includes system rows, which is unreachable and harmless:
                    # only a tenant row can be retired, and no system type can
                    # name a tenant type as its parent.
                    _visible_to_tenant(tenant_id),
                )
            )
        )
        .scalars()
        .all()
    )
    if children:
        raise UserTypeHasActiveChildren(list(children))


async def _assert_has_no_children(
    session: AsyncSession, *, tenant_id: UUID, parent_code: str
) -> None:
    """Refuse giving a parent to a type that is already a parent itself.

    The other half of the two-level cap (spec §5 / D7). `_assert_hierarchy_valid`
    only inspects the NAMED PARENT, so it catches "you may not hang a leaf off a
    child" but not "you may not turn a parent into a child": create Q and P
    top-level, hang C off P, then move P under Q, and `C -> P -> Q` exists with
    every individual step legal. Nothing in provisioning or identity validation
    walks a tree, so that chain resolves wrongly rather than erroring.

    Sibling of `_assert_no_active_children`, with a deliberately different rule:
    that guard blocks a RETIRE and counts only ACTIVE children, this one blocks a
    RE-PARENT and counts ANY child. A retired child is reactivatable (D4), so
    letting the move through while it is retired only defers the same chain.

    Args:
        session: Async DB session (read-only).
        tenant_id: The tenant whose types are considered, alongside system ones.
        parent_code: The code of the type being moved under a parent.

    Raises:
        UserTypeHasChildren: at least one type, of any status, points at it.
    """
    children = (
        (
            await session.execute(
                select(UserTypeDef.code).where(
                    UserTypeDef.parent_type_code == parent_code,
                    _visible_to_tenant(tenant_id),
                )
            )
        )
        .scalars()
        .all()
    )
    if children:
        raise UserTypeHasChildren(list(children))


async def replace_user_type_for_scope(
    session: AsyncSession,
    requests: list[UserTypeCreateRequest],
    *,
    target_config_id: UUID | None = None,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Update a user type IN PLACE. Scope = (tenant_id, code).

    Signature matches `_ReplaceFn` in `config_requests/apply.py`.

    Unlike every other config type, this does NOT delete-and-reinsert. Spec D3
    forbids deleting a user type, and a delete+insert would churn the row id and
    lose `created_at` for a record that `users.user_type` and every config table
    reference by code string with no foreign key. Only `label`, `status` and
    `parent_type_code` are mutable; `code` is the join key and never changes.

    Args:
        session: Async DB session.
        requests: A one-element list holding the full desired row.
        target_config_id: The live row the maker edited (audit traceability).
        admin: The approving admin — drives the audit row. None skips the audit.
        ip_address: Caller IP, recorded on the audit row.

    Raises:
        AppHTTPException 403: the target is a system type.
        AppHTTPException 404: no such type for this tenant.
        UserTypeCategoryImmutable: the payload names a different category.
        UserTypeHasActiveChildren: retiring a parent that still has active children.
        UserTypeHasChildren: giving a parent to a type that has children of its
            own, which would make the tree three levels deep.
        UnknownUserTypeCategory, CategoryDoesNotSupportHierarchy, ParentTypeNotFound,
        ParentTypeWrongCategory, ParentTypeNotTopLevel: re-parenting or
            reactivating broke a hierarchy rule (spec §5).

    Side effects:
        Updates one `user_types` row and appends one `user_type.updated` audit
        row, then commits once. The commit also persists whatever the caller
        staged beforehand — for maker-checker that is the request's
        PENDING → APPLIED transition, its review row and its audit row, so the
        approval and the config write land atomically or not at all.
    """
    first = requests[0]
    row = await _load_mutable_type(session, tenant_id=first.tenant_id, code=first.code)
    before = _type_state(row)

    # The write block below never assigns `category_code` — it is immutable, like
    # `code`. Refuse a payload that disagrees rather than ignoring the field: an
    # approved maker-checker request that silently does nothing is its own bug,
    # and validating the hierarchy against a category the row will never adopt is
    # how a Business parent used to land on a Retail row.
    if first.category_code != row.category_code:
        raise UserTypeCategoryImmutable()

    retiring = first.status == USER_TYPE_STATUS_RETIRED and row.status != USER_TYPE_STATUS_RETIRED
    if retiring:
        await _assert_no_active_children(session, tenant_id=first.tenant_id, parent_code=row.code)

    reparenting = first.parent_type_code != row.parent_type_code
    # A status-only reactivation must re-check the hierarchy too. Retiring a
    # child, then its now-childless parent, then reactivating the child is four
    # individually legal steps that compose into the active-child-under-a-
    # retired-parent state rule 4 exists to prevent. D4 makes reactivate a
    # first-class operation, so this path is live, not hypothetical.
    reactivating = (
        first.status == USER_TYPE_STATUS_ACTIVE and row.status == USER_TYPE_STATUS_RETIRED
    )
    if reparenting or reactivating:
        # Guard the OTHER end of the edge. `_assert_hierarchy_valid` below only
        # asks whether the named parent is top-level; this asks whether the row
        # being moved is a parent itself, which is the half that lets a
        # three-level chain be assembled one legal step at a time. Only a move
        # UNDER a parent can add a level — clearing the parent removes one, so
        # it is left open as the repair path for any chain that predates this.
        if first.parent_type_code is not None:
            await _assert_has_no_children(session, tenant_id=first.tenant_id, parent_code=row.code)
        # Only the hierarchy half of the rule set: the row keeps its own
        # (immutable) code, so the collision check would trip on itself. The
        # category comes off the ROW, never the payload.
        await _assert_hierarchy_valid(
            session,
            tenant_id=first.tenant_id,
            category_code=row.category_code,
            parent_type_code=first.parent_type_code,
        )

    row.label = first.label
    row.status = first.status
    row.parent_type_code = first.parent_type_code
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=first.tenant_id,
            action="user_type.updated",
            entity_type="user_type",
            entity_id=str(target_config_id or row.id),
            before_state=before,
            after_state=_type_state(row),
            ip_address=ip_address,
        )

    await session.commit()
