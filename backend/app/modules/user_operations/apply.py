"""Execute an approved user-operation request against the identity service.

Once N-eyes quorum is reached, `apply_user_operation` dispatches on `operation`
to the matching identity service function (reused verbatim — `create_user`
enforces identifier uniqueness / hierarchy, `admin_update_user` applies editable
fields). The MAKER who proposed is passed as the acting admin so the identity
audit row is attributed to whoever authored the change.

The identity fn commits internally — persisting the request→APPLIED transition
the caller staged beforehand, in the SAME commit. `applied_user_id` is then
written in a small follow-up commit, since the created user's id only exists once
that commit has run (for update_user it is the known target).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.identity.schemas import CreateUserRequest
from app.modules.identity.service import admin_update_user, create_user
from app.modules.user_operations.schemas import CreateUserPayload, UpdateUserPayload
from app.shared.models import (
    USER_OP_CREATE,
    USER_OP_UPDATE,
    UserOperationRequest,
)


def _maker_principal(request: UserOperationRequest) -> AdminPrincipal:
    """Reconstruct the proposing maker as the acting admin for audit attribution.

    Only the `id` (Keycloak sub) is needed downstream — the identity audit
    writer reads `admin.id`. Username/roles aren't available at apply time and
    aren't used, so they are left empty.
    """
    return AdminPrincipal(id=request.maker_admin_id, username="", roles=frozenset())


async def apply_user_operation(
    session: AsyncSession,
    request: UserOperationRequest,
    *,
    ip_address: str | None = None,
) -> UserOperationRequest:
    """Execute an APPLIED user-operation request via its identity function.

    Dispatches on `request.operation`, threading the maker as the acting admin.
    Sets `applied_user_id` to the created / edited user.

    Returns:
        The same request, with `applied_user_id` set.

    Side effects:
        Commits via the identity fn (user create/edit + staged request
        mutations), then commits once more to persist `applied_user_id`.
    """
    admin = _maker_principal(request)

    if request.operation == USER_OP_CREATE:
        create_payload = CreateUserPayload.model_validate(request.payload)
        user = await create_user(
            session,
            CreateUserRequest(
                tenant_id=request.tenant_id,
                identifiers=create_payload.identifiers,
                profile=create_payload.profile,
                user_type=create_payload.user_type,
                # Re-resolved and re-validated by create_user against the type
                # row's `parent_type_code` — an approval that silently dropped
                # the supervisor would misdirect that person's commission.
                parent_identifier=create_payload.parent_identifier,
            ),
            admin=admin,
            ip_address=ip_address,
        )
        request.applied_user_id = user.id
    else:  # USER_OP_UPDATE
        assert request.operation == USER_OP_UPDATE
        update_payload = UpdateUserPayload.model_validate(request.payload)
        await admin_update_user(
            session,
            user_id=update_payload.target_user_id,
            tenant_id=request.tenant_id,
            first_name=update_payload.first_name,
            last_name=update_payload.last_name,
            status=update_payload.status,
            user_type=update_payload.user_type,
            admin=admin,
            ip_address=ip_address,
        )
        request.applied_user_id = update_payload.target_user_id

    # Persist the applied_user_id linkage (the created id only exists post-commit).
    await session.commit()
    return request
