"""Give existing users their tenant's default role.

Why a script and not a migration: this grants permission to move money. That
should be a deliberate, reviewable act with a printed before/after, not a side
effect of `alembic upgrade head` running unattended on a deploy.

Context: until the default-role work, `provision_tenant_defaults` created no
roles and nothing assigned one at user creation. Because `has_permission` denies
by default (Pay-PRD-0440), every user in a tenant provisioned before that change
is unable to send money, cash out, redeem or buy airtime. This backfills them.

Usage:
    python scripts/backfill_default_roles.py            # dry run, prints a plan
    python scripts/backfill_default_roles.py --apply    # writes

Idempotent: a user who already holds any role is left alone, so re-running is
safe and will not stack duplicate assignments or override a deliberate choice.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.modules.roles.service import assign_default_role  # noqa: E402
from app.modules.tenants.service import DEFAULT_ROLE_BY_USER_TYPE  # noqa: E402
from app.shared.models import Role, Tenant, User, UserRole  # noqa: E402


async def _users_without_a_role(session: AsyncSession) -> list[User]:
    """Return users holding no role at all, oldest first.

    Only users with NO role are candidates. Someone deliberately placed on a
    restricted role (or deliberately given none) must not be silently widened by
    a backfill.
    """
    assigned = select(UserRole.user_id).distinct().scalar_subquery()
    result = await session.execute(
        select(User).where(User.id.not_in(assigned)).order_by(User.created_at)
    )
    return list(result.scalars().all())


async def _tenants_missing_default_roles(session: AsyncSession) -> list[Tenant]:
    """Return tenants that have none of the default roles provisioned.

    These need `provision_tenant_defaults` re-run before any user in them can be
    backfilled — there is no role to assign yet.
    """
    wanted = set(DEFAULT_ROLE_BY_USER_TYPE.values())
    result = await session.execute(select(Tenant).where(Tenant.deleted_at.is_(None)))
    missing = []
    for tenant in result.scalars().all():
        names = set(
            (await session.execute(select(Role.name).where(Role.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        if not (wanted & names):
            missing.append(tenant)
    return missing


async def main(apply: bool) -> None:
    """Report, and optionally perform, the default-role backfill."""
    async with SessionLocal() as session:
        blocked = await _tenants_missing_default_roles(session)
        if blocked:
            print("Tenants with NO default roles provisioned:")
            for tenant in blocked:
                print(f"  ! {tenant.name} ({tenant.id})")
            print(
                "  -> run provision_tenant_defaults for these first; their users "
                "cannot be backfilled until a role exists.\n"
            )

        candidates = await _users_without_a_role(session)
        if not candidates:
            print("No users are missing a role. Nothing to do.")
            return

        by_type: dict[str, int] = {}
        for user in candidates:
            by_type[user.user_type] = by_type.get(user.user_type, 0) + 1

        total_users = (await session.execute(select(func.count(User.id)))).scalar_one()
        print(f"{len(candidates)} of {total_users} users hold no role:")
        for user_type, count in sorted(by_type.items()):
            target = DEFAULT_ROLE_BY_USER_TYPE.get(user_type)
            verdict = f"-> {target}" if target else "-> (none needed; API-key flow)"
            print(f"  {count:>6}  {user_type:<14} {verdict}")

        if not apply:
            print("\nDry run. Re-run with --apply to write these assignments.")
            return

        assigned = 0
        for user in candidates:
            before = len(
                (await session.execute(select(UserRole).where(UserRole.user_id == user.id)))
                .scalars()
                .all()
            )
            await assign_default_role(session, user)
            await session.commit()
            after = len(
                (await session.execute(select(UserRole).where(UserRole.user_id == user.id)))
                .scalars()
                .all()
            )
            if after > before:
                assigned += 1

        print(f"\nAssigned a default role to {assigned} user(s).")
        skipped = len(candidates) - assigned
        if skipped:
            print(
                f"{skipped} left without a role — merchant user types need none, "
                "and tenants missing their default roles are listed above."
            )


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
