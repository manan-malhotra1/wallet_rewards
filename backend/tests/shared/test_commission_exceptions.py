"""Commission exception shapes.

Distinct error codes so an operator can tell "this agent has not accrued that
much" apart from "this user's spendable wallet is short".
"""

from __future__ import annotations

from app.shared.exceptions import (
    AppHTTPException,
    CommissionFlagImmutable,
    InsufficientCommissionBalance,
)


def test_insufficient_commission_balance_shape() -> None:
    """409 with its own machine-readable code, not a generic InsufficientFunds."""
    exc = InsufficientCommissionBalance()
    assert isinstance(exc, AppHTTPException)
    assert exc.status_code == 409
    assert exc.error_code == "insufficient_commission_balance"


def test_commission_flag_immutable_shape() -> None:
    """422 — the flag is creation-time only (D3)."""
    exc = CommissionFlagImmutable()
    assert isinstance(exc, AppHTTPException)
    assert exc.status_code == 422
    assert exc.error_code == "commission_flag_immutable"
