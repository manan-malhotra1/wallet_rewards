"""Tests for the Fernet secret-at-rest helper (Epic 14, api-key secrets).

The api_keys table stores partner key secrets encrypted (Decision D3) so
they are recoverable for HMAC verification but never sit in the clear.
"""

from __future__ import annotations

from app.auth.secret_box import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_round_trip() -> None:
    """A secret survives an encrypt -> decrypt round trip unchanged, and the
    ciphertext is not the plaintext (nothing stored in the clear)."""
    plaintext = "sak_secret_9f3c2b1a-not-a-real-key"
    token = encrypt_secret(plaintext)
    assert token != plaintext
    assert decrypt_secret(token) == plaintext


def test_encrypt_is_non_deterministic() -> None:
    """Fernet embeds an IV + timestamp, so encrypting the same value twice
    yields different ciphertexts — an attacker can't match equal secrets."""
    assert encrypt_secret("same-value") != encrypt_secret("same-value")
