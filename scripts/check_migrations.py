#!/usr/bin/env python3
"""Verify SQLAlchemy models are in sync with the database schema.

Wraps `alembic check` (Alembic 1.9+). Exits non-zero if models drift from
the migration head.

Usage:
    python scripts/check_migrations.py
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"

result = subprocess.run(
    ["alembic", "check"],
    cwd=BACKEND,
    capture_output=True,
    text=True,
)

print(result.stdout)
if result.returncode != 0:
    print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
