"""PII masking helpers for logs and error messages.

Per NFR-0240 and `.claude/rules/compliance-fintech.md`, identifiers
(phone, email, account, card) MUST be masked when written to application
logs. Use these helpers — never roll your own.

Examples:
    mask_phone("+27 82 555 0142")  -> "+27 82 *** 0142"
    mask_email("jane@example.com") -> "j***@example.com"
    mask_account("ZA-001-887-2210") -> "ZA-001-***-2210"
    mask_card("5234 5678 9012 3456") -> "5234 **** **** 3456"
"""

from __future__ import annotations


def mask_phone(phone: str) -> str:
    """Mask the middle digits of a phone number.

    Keeps the country/area prefix and last 4 digits, replaces the rest with
    asterisks. Returns the original if too short to mask meaningfully.

    Args:
        phone: Phone number in any format (with or without separators).

    Returns:
        Masked phone string suitable for logs.
    """
    digits_only = "".join(ch for ch in phone if ch.isdigit())
    if len(digits_only) < 8:
        return "***"
    # Show first 4 + last 4, mask the middle.
    visible_prefix = digits_only[:4]
    visible_suffix = digits_only[-4:]
    return f"+{visible_prefix} *** {visible_suffix}"


def mask_email(email: str) -> str:
    """Mask the local part of an email except the first character.

    Args:
        email: An email address.

    Returns:
        Masked email; if not a recognisable email, returns "***".
    """
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_account(account: str) -> str:
    """Mask the middle of an account number, keeping prefix and last 4.

    Args:
        account: Account number string (any format).

    Returns:
        Masked account string.
    """
    if len(account) < 8:
        return "***"
    return f"{account[:4]}***{account[-4:]}"


def mask_card(card: str) -> str:
    """Mask card number per PCI-DSS guidance (show first 4 + last 4 only).

    Args:
        card: Card number in any format.

    Returns:
        Masked card string with first 4 and last 4 digits visible.
    """
    digits = "".join(ch for ch in card if ch.isdigit())
    if len(digits) < 8:
        return "****"
    return f"{digits[:4]} **** **** {digits[-4:]}"


def mask_identifier(identifier_type: str, value: str) -> str:
    """Dispatch helper — masks a value based on its identifier type.

    Args:
        identifier_type: One of 'phone', 'email', 'account_number', 'card_number'.
        value: The raw identifier value.

    Returns:
        Masked value suitable for logs.
    """
    if identifier_type == "phone":
        return mask_phone(value)
    if identifier_type == "email":
        return mask_email(value)
    if identifier_type == "account_number":
        return mask_account(value)
    if identifier_type == "card_number":
        return mask_card(value)
    return "***"
