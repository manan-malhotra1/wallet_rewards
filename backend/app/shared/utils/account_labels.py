"""Operator-facing labels for ledger account types.

A transaction always has two sides, so a statement row should always be able to
name the other one. When that side is a real user we show their name; when it is
a system pool, a merchant collection account, or another of the SAME user's own
wallets, there is no person to name and we show what the account IS instead.

Kept in step with `admin-ui/lib/account-type-label.ts`, which labels the same
keys for the wallets table. The two lists are duplicated deliberately rather
than generated: the backend one feeds a statement's counterparty column and the
frontend one feeds a balances table, and they are allowed to word things
differently if those surfaces ever need it.
"""

from __future__ import annotations

from app.shared.models import (
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
    ACCOUNT_TYPE_CASHBACK_PROVIDER,
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_POINTS_REDEMPTION,
    ACCOUNT_TYPE_PROVIDER_REDEMPTION,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ACCOUNT_TYPE_TAX_COMMISSION,
    ACCOUNT_TYPE_TAX_SERVICE,
)

ACCOUNT_TYPE_LABEL: dict[str, str] = {
    ACCOUNT_TYPE_FINANCIAL_WALLET: "Main wallet",
    ACCOUNT_TYPE_COMMISSION_WALLET: "Commission wallet",
    ACCOUNT_TYPE_POINTS: "Points",
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW: "Cash float",
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED: "Fees collected",
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE: "Points issuance pool",
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT: "Bank mirror",
    ACCOUNT_TYPE_COMMISSION: "Commission pool",
    ACCOUNT_TYPE_TAX_SERVICE: "Tax collected on service charges",
    ACCOUNT_TYPE_TAX_COMMISSION: "Tax collected on commissions",
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING: "Airtime merchant holding",
    ACCOUNT_TYPE_CASHBACK_PROVIDER: "Cashback & redemption wallet",
    ACCOUNT_TYPE_POINTS_REDEMPTION: "Points redemption wallet",
    ACCOUNT_TYPE_PROVIDER_REDEMPTION: "Provider redemption wallet",
}


def account_label(account_type: str, name: str | None = None) -> str:
    """Human label for one account, used as a statement's counterparty.

    Args:
        account_type: The ledger `accounts.account_type` key.
        name: The operator-chosen label. Only bank mirrors carry one today, and
            several may coexist per currency, so the name is what actually tells
            two of them apart — it is appended rather than replacing the type.

    Returns:
        A label safe to show an operator. An unknown future type falls back to
        its raw key rather than an empty cell, so a new account type surfaces
        as something readable instead of silently reintroducing a blank
        counterparty.
    """
    base = ACCOUNT_TYPE_LABEL.get(account_type, account_type)
    if name:
        return f"{base} · {name}"
    return base
