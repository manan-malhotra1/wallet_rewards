"""Guards the service-code registry against drift.

The registry is the single source of truth for "the platform implements this
code". If a new money flow ships without registering its code, or a code is
registered with no implementation, these tests fail — otherwise the registry
silently rots and the derived-service validation starts lying.
"""

from app.shared.services_registry import BASE_SERVICE_CODES, DERIVABLE_BASE_CODES


def test_registry_lists_every_implemented_service_code() -> None:
    """Verify the registry matches the nine codes the platform implements"""
    assert BASE_SERVICE_CODES == frozenset(
        {
            "p2p",
            "fund",
            "withdraw",
            "cash_in",
            "cashout",
            "merchant_cashin",
            "airtime_recharge",
            "redemption",
            "change_pin",
        }
    )


def test_change_pin_is_not_derivable() -> None:
    """Verify non-financial flows cannot be derived — nothing to differentiate"""
    assert "change_pin" in BASE_SERVICE_CODES
    assert "change_pin" not in DERIVABLE_BASE_CODES
    assert DERIVABLE_BASE_CODES == BASE_SERVICE_CODES - {"change_pin"}


def test_derivable_codes_are_a_subset_of_base_codes() -> None:
    """Verify every derivable code is a real implemented base"""
    assert DERIVABLE_BASE_CODES <= BASE_SERVICE_CODES
