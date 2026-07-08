"""Services catalog FastAPI router (Phase 2 — admin-gated).

Endpoints:
  GET    /api/v1/services?tenant_id=&status=
  POST   /api/v1/services
  PATCH  /api/v1/services/{id}?tenant_id=
  DELETE /api/v1/services/{id}?tenant_id=  (soft-delete)

The catalog backs the admin UI dropdowns that replaced the free-text
transaction_type inputs on Limits / Pricing / Campaigns pages.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.services.schemas import (
    ServiceCreateRequest,
    ServiceOut,
    ServiceUpdateRequest,
)
from app.modules.services.service import (
    create_service,
    list_services,
    soft_delete_service,
    update_service,
)

router = APIRouter(prefix="/api/v1/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
async def get_services(
    tenant_id: uuid.UUID,
    status: Literal["active", "disabled"] | None = None,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[ServiceOut]:
    """List services for the tenant.

    The admin UI calls this with `status=active` when populating dropdowns
    in Limits / Pricing / Campaigns and omits the filter on the catalog
    management page.
    """
    _ = admin
    services = await list_services(session, tenant_id, status=status)
    return [ServiceOut.model_validate(s) for s in services]


@router.post("", response_model=ServiceOut, status_code=201)
async def post_service(
    payload: ServiceCreateRequest,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> ServiceOut:
    """Create a new service in the tenant catalog."""
    _ = admin
    service = await create_service(session, payload)
    return ServiceOut.model_validate(service)


@router.patch("/{service_id}", response_model=ServiceOut)
async def patch_service(
    service_id: uuid.UUID,
    tenant_id: uuid.UUID,
    payload: ServiceUpdateRequest,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> ServiceOut:
    """Update display_name / description / status on a service."""
    _ = admin
    service = await update_service(session, tenant_id, service_id, payload)
    return ServiceOut.model_validate(service)


@router.delete("/{service_id}", response_model=ServiceOut)
async def delete_service(
    service_id: uuid.UUID,
    tenant_id: uuid.UUID,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> ServiceOut:
    """Soft-delete the service so it disappears from dropdowns."""
    _ = admin
    service = await soft_delete_service(session, tenant_id, service_id)
    return ServiceOut.model_validate(service)
