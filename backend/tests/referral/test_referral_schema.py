"""Referral rule setup validation.

Covers the cross-field rules the evaluator relies on:
  - a referral rule REQUIRES referral_trigger
  - 'nth_transaction' REQUIRES referral_trigger_n >= 1
  - referral-only fields are rejected on non-referral rule types
  - a well-formed referral rule validates
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.rules.schemas import RuleCreateRequest

_TENANT = "00000000-0000-4000-8000-000000000001"


def test_referral_rule_without_trigger_is_rejected() -> None:
    """Verify a referral rule is rejected when its trigger is missing"""
    with pytest.raises(ValidationError, match="referral_trigger"):
        RuleCreateRequest(
            tenant_id=_TENANT,
            name="ref no trigger",
            rule_type="referral",
            reward_type="points",
            reward_value=Decimal("50"),
        )


def test_nth_transaction_referral_without_n_is_rejected() -> None:
    """Verify a transaction-count referral rule is rejected when the required count is missing"""
    with pytest.raises(ValidationError, match="referral_trigger_n"):
        RuleCreateRequest(
            tenant_id=_TENANT,
            name="ref nth no n",
            rule_type="referral",
            referral_trigger="nth_transaction",
            reward_type="points",
            reward_value=Decimal("50"),
        )


def test_referral_fields_rejected_on_non_referral_rule() -> None:
    """Verify referral settings are rejected on a non-referral rule"""
    with pytest.raises(ValidationError, match="referral_trigger"):
        RuleCreateRequest(
            tenant_id=_TENANT,
            name="milestone with referral trigger",
            rule_type="milestone",
            transaction_type="p2p",
            count_threshold=3,
            referral_trigger="signup",
            reward_type="points",
            reward_value=Decimal("50"),
        )


def test_well_formed_signup_referral_rule_validates() -> None:
    """Verify a well-formed signup referral rule is accepted"""
    req = RuleCreateRequest(
        tenant_id=_TENANT,
        name="invite a friend",
        rule_type="referral",
        referral_trigger="signup",
        referee_reward_value=Decimal("100"),
        reward_type="cashback",
        reward_value=Decimal("50"),
    )
    assert req.referral_trigger == "signup"
    assert req.referee_reward_value == Decimal("100")
