#!/usr/bin/env python3
"""Backfill `admin_profiles` from Keycloak realm users (Epic 24 display names).

Admin display names are normally recorded lazily when an admin acts on a config
request. This one-shot backfill pre-populates the cache for EVERY realm admin so
existing requests (whose maker acted before the feature landed) resolve to a
name immediately. Idempotent — safe to re-run; run after `alembic upgrade`.

Usage:
    python scripts/backfill_admin_profiles.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
import urllib.request

# Reuse the local-dev Keycloak coordinates from the bootstrap script.
KEYCLOAK_URL = "http://localhost:8080"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"
REALM = "wallet-platform"


def _get_admin_token() -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASS,
        }
    ).encode()
    req = urllib.request.Request(
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())["access_token"]


def _list_realm_users(token: str) -> list[dict]:
    req = urllib.request.Request(
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/users?max=1000",
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def _display_name(user: dict) -> str:
    full = " ".join(p for p in (user.get("firstName"), user.get("lastName")) if p).strip()
    return full or user.get("username", "")


async def _main() -> None:
    # Imported here so the module docstring/usage still works without a DB.
    from app.auth.principals import AdminPrincipal
    from app.database import SessionLocal
    from app.modules.admin_profiles import record_admin

    token = _get_admin_token()
    users = _list_realm_users(token)
    if not users:
        print("No realm users found — nothing to backfill.")
        return

    async with SessionLocal() as session:
        for user in users:
            principal = AdminPrincipal(
                id=user["id"],
                username=user.get("username", ""),
                roles=frozenset(),
                name=_display_name(user),
                email=user.get("email"),
            )
            await record_admin(session, principal)
            print(f"  + {principal.display_name} ({principal.id})")
        await session.commit()
    print(f"Backfilled {len(users)} admin profile(s).")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001 — CLI: surface any failure clearly
        sys.exit(f"Backfill failed: {exc}")
