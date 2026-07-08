"""Symmetric encryption for secrets stored at rest (Epic 14).

Partner API-key secrets must stay recoverable to verify HMAC request
signatures (Decision D3), so they can't be one-way hashed. Instead we encrypt
them at rest with Fernet (AES-128-CBC + HMAC), keyed off `settings.SECRET_KEY`.
This keeps the plaintext secret out of the database while still letting
`auth.hmac.verify_signature` recompute the signature at request time.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from hashlib import sha256

from cryptography.fernet import Fernet

from app.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Build the Fernet cipher from SECRET_KEY.

    Fernet needs a 32-byte urlsafe-base64 key; we derive one deterministically
    from SECRET_KEY via SHA-256 so no separate key material has to be managed.
    Cached because the derivation is pure and SECRET_KEY is fixed per process.
    """
    key = base64.urlsafe_b64encode(sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns a urlsafe Fernet token string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Recover the plaintext secret from a stored Fernet token.

    Raises:
        cryptography.fernet.InvalidToken: token is corrupt or was produced
            under a different SECRET_KEY.
    """
    return _fernet().decrypt(token.encode()).decode()
