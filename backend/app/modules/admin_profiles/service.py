"""Admin profile service — record and resolve Keycloak admin display names.

`record_admin` upserts the caller's identity (keyed by Keycloak `sub`) whenever
an admin performs an auditable action, so admin surfaces can later render a
human name instead of a bare ID. `resolve_admin_names` batch-maps subs to names.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.shared.models import AdminProfile


async def record_admin(session: AsyncSession, admin: AdminPrincipal) -> None:
    """Upsert the admin's display identity (idempotent, keyed by keycloak_sub).

    Refreshes username / display_name / email on every call so a renamed admin
    stays current. Does NOT commit — participates in the caller's transaction.
    """
    if not admin.id:
        return
    stmt = insert(AdminProfile).values(
        keycloak_sub=admin.id,
        username=admin.username,
        display_name=admin.display_name,
        email=admin.email,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[AdminProfile.keycloak_sub],
        set_={
            "username": stmt.excluded.username,
            "display_name": stmt.excluded.display_name,
            "email": stmt.excluded.email,
        },
    )
    await session.execute(stmt)


async def resolve_admin_names(session: AsyncSession, subs: Iterable[str]) -> dict[str, str]:
    """Return {keycloak_sub: display_name} for the known subs among `subs`.

    Unknown subs (no profile recorded yet) are simply absent from the map — the
    caller decides the fallback (e.g. a shortened id).
    """
    wanted = {s for s in subs if s}
    if not wanted:
        return {}
    rows = await session.execute(
        select(AdminProfile.keycloak_sub, AdminProfile.display_name).where(
            AdminProfile.keycloak_sub.in_(wanted)
        )
    )
    return {sub: name for sub, name in rows.all()}
