"""Export the partner-facing OpenAPI spec for the external API (Epic 14 S6).

Writes docs/api/external-openapi.json containing only the `external`-tagged
operations (plus all component schemas they may reference). Regenerate after
changing any external endpoint.

Run from backend/:  python ../scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# The package lives in backend/; make it importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app  # noqa: E402  (import after sys.path setup)

TAG = "external"
OUT = Path(__file__).resolve().parent.parent / "docs" / "api" / "external-openapi.json"


def build_external_spec() -> dict[str, Any]:
    """Return an OpenAPI doc restricted to the external-tagged operations."""
    spec = app.openapi()
    paths: dict[str, Any] = {}
    for path, operations in spec["paths"].items():
        kept = {
            method: op
            for method, op in operations.items()
            if isinstance(op, dict) and TAG in op.get("tags", [])
        }
        if kept:
            paths[path] = kept

    return {
        "openapi": spec["openapi"],
        "info": {
            "title": "Sasai Wallet — Partner API",
            "version": spec["info"]["version"],
            "description": (
                "Partner-facing external API. Authenticate with X-Sasai-Api-Key "
                "plus an HMAC X-Sasai-Signature over the raw request body."
            ),
        },
        "paths": paths,
        # Ship all component schemas — a superset is harmless and keeps $refs valid.
        "components": spec.get("components", {}),
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build_external_spec(), indent=2) + "\n")
    print(f"Wrote {OUT} ({len(build_external_spec()['paths'])} path(s))")


if __name__ == "__main__":
    main()
