"""Tests for POST /api/v1/identity/auth/start — anonymous phone lookup.

The endpoint is a pure read-only check the mobile app calls right after
the user enters a phone number. It branches the auth flow:

  - `{"status": "needs_otp"}` — no user in this tenant for that phone;
    route the user through OTP → set-PIN registration.
  - `{"status": "needs_pin"}` — a user already exists; route to PIN entry.

Critical invariants exercised here:
  - Pure lookup. Unlike /otp/send, this endpoint MUST NOT create any rows
    in `users` or `user_identifiers`.
  - Tenant isolation (NFR-0220). A phone known in tenant B looks unknown
    from tenant A.
  - Phone normalisation. Whitespace / dashes / parens variants of the
    same number resolve identically.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, User, UserIdentifier

# -----------------------------------------------------------------------------
# Happy paths
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_start_returns_needs_pin_for_known_phone(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Phone that belongs to a user in the tenant → needs_pin."""
    # test_user has exactly one phone identifier (see conftest).
    phone = test_user.identifiers[0].identifier_value

    response = await async_client.post(
        "/api/v1/identity/auth/start",
        json={"tenant_id": str(test_tenant.id), "phone": phone},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "needs_pin"}


@pytest.mark.asyncio
async def test_auth_start_returns_needs_otp_for_unknown_phone(
    async_client: AsyncClient,
    test_tenant: Tenant,
    db_session: AsyncSession,
) -> None:
    """Phone not in the tenant → needs_otp and NO side effects.

    Asserts that no `users` or `user_identifiers` row is created — this
    is what differentiates /auth/start from /otp/send.
    """
    new_phone = "+27 82 555 7777"

    users_before = (
        await db_session.execute(select(func.count(User.id)))
    ).scalar_one()
    identifiers_before = (
        await db_session.execute(select(func.count(UserIdentifier.id)))
    ).scalar_one()

    response = await async_client.post(
        "/api/v1/identity/auth/start",
        json={"tenant_id": str(test_tenant.id), "phone": new_phone},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "needs_otp"}

    users_after = (
        await db_session.execute(select(func.count(User.id)))
    ).scalar_one()
    identifiers_after = (
        await db_session.execute(select(func.count(UserIdentifier.id)))
    ).scalar_one()
    assert users_after == users_before, "auth/start must not create users"
    assert identifiers_after == identifiers_before, (
        "auth/start must not create user_identifiers"
    )


@pytest.mark.asyncio
async def test_auth_start_normalises_phone_whitespace(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """`+27 82 ...` and `+2782...` lookups resolve to the same user.

    The canonical form on disk is the normalised version (no spaces). A
    client that submits the visually-formatted version must still get
    `needs_pin`.
    """
    canonical = test_user.identifiers[0].identifier_value  # already normalised
    # Re-insert spaces every few digits to simulate a UI-formatted value.
    spaced = canonical[:3] + " " + canonical[3:5] + " " + canonical[5:8] + " " + canonical[8:]

    response = await async_client.post(
        "/api/v1/identity/auth/start",
        json={"tenant_id": str(test_tenant.id), "phone": spaced},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "needs_pin"}


# -----------------------------------------------------------------------------
# Tenant isolation (NFR-0220)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_start_does_not_leak_across_tenants(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """A phone registered in tenant B is invisible from tenant A.

    Per NFR-0220, cross-tenant existence checks must return the
    "doesn't exist" answer — `needs_otp`. If we returned `needs_pin`
    here, tenant A would be able to enumerate users from tenant B.
    """
    # Seed a user in `other_tenant` only.
    foreign_phone = "+27825558888"
    other_user = User(tenant_id=other_tenant.id)
    db_session.add(other_user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=other_user.id,
            tenant_id=other_tenant.id,
            identifier_type="phone",
            identifier_value=foreign_phone,
            verified=True,
        )
    )
    await db_session.commit()

    response = await async_client.post(
        "/api/v1/identity/auth/start",
        json={"tenant_id": str(test_tenant.id), "phone": foreign_phone},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "needs_otp"}


# -----------------------------------------------------------------------------
# Failure modes
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_start_unknown_tenant_returns_404(
    async_client: AsyncClient,
) -> None:
    """Unknown tenant_id → 404 tenant_not_found (mirrors /otp/send)."""
    response = await async_client.post(
        "/api/v1/identity/auth/start",
        json={"tenant_id": str(uuid4()), "phone": "+27 82 555 0000"},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error_code"] == "tenant_not_found"


@pytest.mark.asyncio
async def test_auth_start_rejects_malformed_phone(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Empty / too-short phone → 422 validation error.

    Matches the Field(min_length=5) constraint used by every other public
    identity endpoint — no per-endpoint divergence in phone validation.
    """
    response = await async_client.post(
        "/api/v1/identity/auth/start",
        json={"tenant_id": str(test_tenant.id), "phone": "x"},
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_auth_start_missing_phone_returns_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Missing `phone` field → 422 (Pydantic required-field)."""
    response = await async_client.post(
        "/api/v1/identity/auth/start",
        json={"tenant_id": str(test_tenant.id)},
    )

    assert response.status_code == 422, response.text
