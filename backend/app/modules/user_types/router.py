"""User-type catalog FastAPI router — read-only, admin-gated.

Endpoint:
  GET /api/v1/user-types?tenant_id=&include_retired=

There are deliberately NO write endpoints here. Every mutation — create,
relabel, retire, reactivate — is a maker-checker proposal through
`POST /api/v1/config-requests` with `config_type="user_type"` (spec D4), so a
direct write path on this router would be a governance bypass.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.user_types.schemas import UserTypeCategoryOut, UserTypeOut
from app.modules.user_types.service import list_user_types
from app.shared.models import UserTypeCategory

router = APIRouter(prefix="/api/v1/user-types", tags=["user-types"])


class UserTypeCatalogOut(BaseModel):
    """Categories plus the types visible to one tenant, in one round trip.

    Both halves are ordered by the categories' `display_order` (Consumers,
    Retail, Business) so the cascading picker renders the payload as-is.
    """

    categories: list[UserTypeCategoryOut]
    types: list[UserTypeOut]


@router.get("", response_model=UserTypeCatalogOut)
async def get_catalog(
    tenant_id: UUID,
    include_retired: bool = False,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> UserTypeCatalogOut:
    """Return the categories and every user type visible to `tenant_id`.

    The cascading category→type picker needs both halves together, so this is
    one endpoint rather than two.

    Args:
        tenant_id: The tenant whose custom types are included alongside the
            platform-wide system ones. Another tenant's types never appear.
        include_retired: Include retired types — used when rendering an existing
            config row so a retired type still shows its label, not a raw code.
        admin: The authenticated admin. Presence is the whole authorisation
            check; the catalog carries no tenant-private data beyond the type
            labels already scoped by `tenant_id`.
        session: Async DB session (read-only).

    Returns:
        The three fixed categories in `display_order`, and the visible types
        sectioned in that same order (see `list_user_types`).
    """
    _ = admin
    categories = (
        (await session.execute(select(UserTypeCategory).order_by(UserTypeCategory.display_order)))
        .scalars()
        .all()
    )
    types = await list_user_types(session, tenant_id, include_retired=include_retired)
    return UserTypeCatalogOut(
        categories=[UserTypeCategoryOut.model_validate(c) for c in categories],
        types=[UserTypeOut.model_validate(t) for t in types],
    )
