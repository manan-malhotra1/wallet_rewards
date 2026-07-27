"""Encrypting API key secrets at rest.

The api_keys table stores partner key secrets encrypted (Decision D3) so
they are recoverable for HMAC verification but never sit in the clear.
"""

from __future__ import annotations

from app.auth.secret_box import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_round_trip() -> None:
    """Verify a stored API key secret can be recovered but is never kept in the clear"""
    plaintext = "sak_secret_9f3c2b1a-not-a-real-key"
    token = encrypt_secret(plaintext)
    assert token != plaintext
    assert decrypt_secret(token) == plaintext


def test_encrypt_is_non_deterministic() -> None:
    """Verify two identical secrets are stored as different ciphertexts"""
    assert encrypt_secret("same-value") != encrypt_secret("same-value")
