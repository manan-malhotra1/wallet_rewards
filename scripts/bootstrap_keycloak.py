#!/usr/bin/env python3
"""Bootstrap the Keycloak realm for Sasai Wallet & Rewards Platform.

Idempotent — safe to re-run. Creates:
  - Realm: wallet-platform
  - Client: admin-ui          (confidential, auth-code flow, for Next.js)
  - Client: backend-service   (service-account, client-credentials, for backend)
  - Realm roles: platform-admin, finance-reviewer, support-agent

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

REALM_ROLES = ["platform-admin", "finance-reviewer", "support-agent"]


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
    kc_id = find_client(token, client_id)
    if kc_id:
        print(f"  - Client '{client_id}' already exists ({kc_id})")
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
            "standardFlowEnabled": True,         # Authorization Code Flow
            "directAccessGrantsEnabled": False,
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


if __name__ == "__main__":
    main()
