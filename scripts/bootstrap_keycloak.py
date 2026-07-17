#!/usr/bin/env python3
"""Bootstrap the Keycloak realm for Sasai Wallet & Rewards Platform.

Idempotent — safe to re-run. Creates:
  - Realm: wallet-platform
  - Client: admin-ui          (confidential, auth-code flow, for Next.js)
  - Client: backend-service   (service-account, client-credentials, for backend)
  - Realm roles: platform-admin, finance-reviewer, support-agent, config-approver

Outputs the client secrets so they can be pasted into .env files.

Usage:
    python scripts/bootstrap_keycloak.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK_URL = "http://localhost:8080"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"
REALM = "wallet-platform"

# Fixed local-dev secrets. Rotate for any non-local environment.
ADMIN_UI_SECRET = "dev-admin-ui-secret-local-only"
BACKEND_SERVICE_SECRET = "dev-backend-service-secret-local-only"

# `config-approver` (Pricing v2 Epic 22) is the four-eyes checker role: it
# approves / requests-changes on config-change requests, and must be held by a
# DIFFERENT admin than the maker who proposed the change.
REALM_ROLES = ["platform-admin", "finance-reviewer", "support-agent", "config-approver"]

# Local-dev admin users — rotate / remove for any non-local environment.
# All share one dev password. BOTH admins hold `platform-admin` (propose /
# maker) AND `config-approver` (four-eyes checker), so either can raise a
# config request and the OTHER can approve it — matching "any admin can
# approve any other admin's request". A single admin still cannot approve
# their OWN request (SelfApprovalForbidden), so two accounts are needed to
# exercise the maker-checker flow end to end.
DEV_ADMIN_PASSWORD = "admin-test-pass"  # noqa: S105 — local-dev only
DEV_ADMINS = [
    {
        "username": "admin-test",
        "first_name": "Admin",
        "last_name": "Test",
        "roles": ["platform-admin", "config-approver"],
    },
    {
        "username": "admin-approver",
        "first_name": "Approver",
        "last_name": "Admin",
        "roles": ["platform-admin", "config-approver"],
    },
]


def http(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    form: dict | None = None,
) -> tuple[int, dict | list | str]:
    headers = {"Accept": "application/json"}
    body: bytes | None = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode()
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, raw


def get_admin_token() -> str:
    code, body = http(
        "POST",
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASS,
        },
    )
    if code != 200 or not isinstance(body, dict):
        sys.exit(f"Failed to get admin token: {code} {body}")
    return body["access_token"]


def ensure_realm(token: str) -> None:
    code, _ = http("GET", f"{KEYCLOAK_URL}/admin/realms/{REALM}", token=token)
    if code == 200:
        print(f"  - Realm '{REALM}' already exists")
        return
    code, body = http(
        "POST",
        f"{KEYCLOAK_URL}/admin/realms",
        token=token,
        json_body={
            "realm": REALM,
            "enabled": True,
            "displayName": "Sasai Wallet Platform",
            "registrationAllowed": False,
            "loginWithEmailAllowed": True,
            "sslRequired": "none",
        },
    )
    if code != 201:
        sys.exit(f"Failed to create realm: {code} {body}")
    print(f"  + Realm '{REALM}' created")


def find_client(token: str, client_id: str) -> str | None:
    code, body = http(
        "GET",
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients?clientId={client_id}",
        token=token,
    )
    if code == 200 and isinstance(body, list) and body:
        return body[0]["id"]
    return None


def ensure_client(token: str, client_id: str, config: dict) -> str:
    """Create the client if missing, or update its config in place.

    Idempotent — re-running with a different config (e.g. flipping
    `directAccessGrantsEnabled`) brings Keycloak into sync.
    """
    kc_id = find_client(token, client_id)
    if kc_id:
        # Update the existing client so config drift in the script propagates.
        update_code, update_body = http(
            "PUT",
            f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{kc_id}",
            token=token,
            json_body={**config, "id": kc_id},
        )
        if update_code not in (200, 204):
            sys.exit(
                f"Failed to update client {client_id}: {update_code} {update_body}"
            )
        print(f"  ~ Client '{client_id}' updated ({kc_id})")
        return kc_id

    code, body = http(
        "POST",
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients",
        token=token,
        json_body=config,
    )
    if code != 201:
        sys.exit(f"Failed to create client {client_id}: {code} {body}")

    kc_id = find_client(token, client_id)
    if not kc_id:
        sys.exit(f"Client {client_id} created but cannot be found")
    print(f"  + Client '{client_id}' created ({kc_id})")
    return kc_id


def get_client_secret(token: str, kc_id: str) -> str:
    code, body = http(
        "GET",
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{kc_id}/client-secret",
        token=token,
    )
    if code != 200 or not isinstance(body, dict):
        sys.exit(f"Failed to read client secret: {code} {body}")
    return body.get("value", "<unknown>")


def _find_user_id(token: str, username: str) -> str | None:
    """Return Keycloak's UUID for a username in our realm, or None."""
    code, body = http(
        "GET",
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={username}&exact=true",
        token=token,
    )
    if code == 200 and isinstance(body, list) and body:
        return body[0]["id"]
    return None


def ensure_admin_user(token: str, spec: dict) -> str:
    """Idempotently create one local-dev admin user in the wallet-platform realm.

    Creates the user with a known dev password + email, always (re-)sets the
    password so the demo stays deterministic, and assigns the realm roles in
    `spec["roles"]` (Keycloak ignores duplicate assignments).

    Args:
        token: A master-realm admin token.
        spec: {username, first_name, last_name, roles}.

    Returns:
        The Keycloak UUID of the user.
    """
    username = spec["username"]
    existing = _find_user_id(token, username)
    if existing is not None:
        print(f"  - User '{username}' already exists ({existing})")
        user_id = existing
    else:
        code, body = http(
            "POST",
            f"{KEYCLOAK_URL}/admin/realms/{REALM}/users",
            token=token,
            json_body={
                "username": username,
                "enabled": True,
                "email": f"{username}@example.test",
                "emailVerified": True,
                "firstName": spec["first_name"],
                "lastName": spec["last_name"],
                "credentials": [
                    {
                        "type": "password",
                        "value": DEV_ADMIN_PASSWORD,
                        "temporary": False,
                    }
                ],
            },
        )
        if code not in (201, 204):
            sys.exit(f"Failed to create admin user {username}: {code} {body}")
        user_id = _find_user_id(token, username)
        if user_id is None:
            sys.exit(f"Failed to look up newly-created admin user {username}")
        print(f"  + User '{username}' created ({user_id})")

    # Always (re-)set the password — keeps the demo deterministic.
    code, body = http(
        "PUT",
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/reset-password",
        token=token,
        json_body={
            "type": "password",
            "value": DEV_ADMIN_PASSWORD,
            "temporary": False,
        },
    )
    # 204 No Content on success.
    if code not in (200, 204):
        sys.exit(f"Failed to reset password for {username}: {code} {body}")

    # Assign realm roles. Keycloak ignores duplicates so this is idempotent.
    for role_name in spec["roles"]:
        role_code, role_body = http(
            "GET",
            f"{KEYCLOAK_URL}/admin/realms/{REALM}/roles/{role_name}",
            token=token,
        )
        if role_code != 200 or not isinstance(role_body, dict):
            sys.exit(f"Could not fetch role '{role_name}' to assign: {role_body}")
        assign_code, assign_body = http(
            "POST",
            f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/role-mappings/realm",
            token=token,
            json_body=[role_body],
        )
        if assign_code not in (200, 204):
            sys.exit(
                f"Failed to assign role '{role_name}' to {username}: "
                f"{assign_code} {assign_body}"
            )
    print(f"  + User '{username}' has roles: {', '.join(spec['roles'])}")
    return user_id


def ensure_role(token: str, role_name: str) -> None:
    code, _ = http(
        "GET",
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/roles/{role_name}",
        token=token,
    )
    if code == 200:
        print(f"  - Role '{role_name}' already exists")
        return
    code, body = http(
        "POST",
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/roles",
        token=token,
        json_body={"name": role_name},
    )
    if code != 201:
        sys.exit(f"Failed to create role {role_name}: {code} {body}")
    print(f"  + Role '{role_name}' created")


def main() -> None:
    print("Bootstrapping Keycloak realm + clients + roles...")
    print()
    token = get_admin_token()

    print("Realm:")
    ensure_realm(token)
    print()

    print("Clients:")
    admin_ui_id = ensure_client(
        token,
        "admin-ui",
        {
            "clientId": "admin-ui",
            "enabled": True,
            "publicClient": False,
            "standardFlowEnabled": True,         # Authorization Code Flow (real admin UI login)
            "directAccessGrantsEnabled": True,   # Password grant — for CLI/test token issuance (Phase F.1 demo)
            "serviceAccountsEnabled": False,
            "redirectUris": [
                "http://localhost:3000/*",
            ],
            "webOrigins": ["http://localhost:3000"],
            "secret": ADMIN_UI_SECRET,
            "attributes": {
                "post.logout.redirect.uris": "http://localhost:3000/*",
            },
        },
    )
    backend_id = ensure_client(
        token,
        "backend-service",
        {
            "clientId": "backend-service",
            "enabled": True,
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,      # Client Credentials Flow
            "secret": BACKEND_SERVICE_SECRET,
        },
    )
    print()

    print("Realm roles:")
    for role in REALM_ROLES:
        ensure_role(token, role)
    print()

    print("Admin users (local-dev only):")
    for admin_spec in DEV_ADMINS:
        ensure_admin_user(token, admin_spec)
    print()

    # Fetch effective secrets (in case Keycloak regenerated)
    admin_ui_effective = get_client_secret(token, admin_ui_id)
    backend_effective = get_client_secret(token, backend_id)

    print("=" * 64)
    print(" Keycloak bootstrap complete.")
    print("=" * 64)
    print()
    print(" Admin console : http://localhost:8080    (admin / admin)")
    print(f" Realm         : {REALM}")
    print()
    print(" Paste into backend/.env :")
    print(f"   KEYCLOAK_URL=http://localhost:8080")
    print(f"   KEYCLOAK_REALM={REALM}")
    print(f"   KEYCLOAK_CLIENT_ID=backend-service")
    print(f"   KEYCLOAK_CLIENT_SECRET={backend_effective}")
    print()
    print(" Paste into admin-ui/.env.local :")
    print(f"   KEYCLOAK_URL=http://localhost:8080")
    print(f"   KEYCLOAK_REALM={REALM}")
    print(f"   KEYCLOAK_CLIENT_ID=admin-ui")
    print(f"   KEYCLOAK_CLIENT_SECRET={admin_ui_effective}")
    print()
    admin_list = ", ".join(a["username"] for a in DEV_ADMINS)
    print(f" Admin logins (all password '{DEV_ADMIN_PASSWORD}'): {admin_list}")
    print("   - admin-test      : platform-admin + config-approver (maker & checker)")
    print("   - admin-approver  : platform-admin + config-approver (maker & checker)")
    print()
    print(" Get a test admin JWT (local-dev only):")
    print()
    print("   TOKEN=$(curl -s -X POST \\")
    print(f"     http://localhost:8080/realms/{REALM}/protocol/openid-connect/token \\")
    print("     -d grant_type=password \\")
    print("     -d client_id=admin-ui \\")
    print(f"     -d client_secret={admin_ui_effective} \\")
    print(f"     -d username={DEV_ADMINS[0]['username']} \\")
    print(f"     -d password={DEV_ADMIN_PASSWORD} \\")
    print("     | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"access_token\"])')")
    print()
    print("   curl -H \"Authorization: Bearer $TOKEN\" http://localhost:8000/api/v1/reconciliation/pending?tenant_id=...")
    print()


if __name__ == "__main__":
    main()
