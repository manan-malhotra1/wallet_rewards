Feature: Pricing and fees
  As a platform administrator
  I want fees, commissions and taxes assembled correctly and gated on configuration
  So that customers are charged exactly what is configured and never through an unpriced path

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And a customer is making a transaction on my tenant

  Scenario: Verify a transfer's fee, commission and tax are split into the correct amounts.
    Given a fee, commission and tax are configured for the transaction
    When the customer's charge is assembled
    Then the total is split into the correct fee, commission and tax amounts

  Scenario: Verify the money charged always balances against the money credited.
    Given any combination of fee, commission and tax flags
    When the customer's charge is assembled
    Then the amounts charged and the amounts credited sum to the same total

  Scenario: Verify a transfer with no commission or tax only charges the plain fee.
    Given no commission and no tax are configured
    When the customer's charge is assembled
    Then only the principal and the plain fee are charged

  Scenario: Verify a fee that is entirely tax leaves the customer charged only the tax.
    Given a fully tax-inclusive fee that is entirely tax
    When the customer's charge is assembled
    Then the zero-fee leg is omitted and the customer is charged only the tax

  Scenario: Verify the correct fee tier applies right at a tier boundary amount.
    Given fees are configured in amount tiers
    When the transfer amount lands exactly on a tier boundary
    Then the fee from that tier is applied

  Scenario: Verify no fee tier applies to an amount above the highest configured tier.
    Given fees are configured up to a highest tier
    When the amount is above the highest tier
    Then no fee tier resolves for that amount

  Scenario: Verify a transfer at the exact top of a fee tier is charged that tier's fee.
    Given fees are configured in amount tiers
    When the transfer amount is exactly at the top of a tier
    Then that tier's fee is charged

  Scenario: Verify a transfer above every configured fee tier is blocked rather than charged nothing.
    Given fees are configured up to a highest tier
    When the transfer amount is above every configured tier
    Then the transaction is blocked rather than charged a zero fee

  Scenario: Verify the operator commission adds a fixed amount to a capped percentage.
    Given a commission of a fixed amount plus a capped percentage is configured
    When the commission is calculated
    Then the fixed amount is added to the capped percentage

  Scenario: Verify an operator type with its own commission rate is paid that rate, not the default.
    Given an operator type has its own commission rate
    When the commission for that operator type is calculated
    Then that operator's own rate is paid instead of the default

  Scenario: Verify the commission for the transaction amount comes from the matching amount tier.
    Given commission is configured in amount tiers
    When the commission for a transaction amount is calculated
    Then it comes from the tier matching that amount

  Scenario: Verify no operator commission is recorded when none is configured.
    Given no commission is configured
    When the charge is assembled
    Then no operator commission is recorded

  Scenario: Verify the fee quoted for a transfer matches the configured price.
    Given a fixed fee is configured for the service
    When a customer requests a fee quote
    Then the quoted fee matches the configured price

  Scenario: Verify a percentage-based fee grows with the transfer amount.
    Given a percentage-based fee is configured
    When a customer requests quotes for larger amounts
    Then the quoted fee grows with the amount

  Scenario: Verify a service with no configured price previews a zero fee.
    Given a service has no configured price
    When a customer requests a fee quote for it
    Then the preview shows a zero fee

  Scenario: Verify a points redemption is quoted its own configured fee.
    Given a points-currency redemption has its own configured fee
    When a customer requests a quote for a points redemption
    Then the points account's own fee is quoted

  Scenario: Verify a caller can preview the fee for a specific account type.
    Given fees differ by account type
    When a caller requests a quote for a specific account type
    Then the fee for that account type is previewed

  Scenario: Verify a fee quote cannot be requested without signing in.
    Given I am not signed in
    When I request a fee quote
    Then I am refused with an unauthorized response

  Scenario: Verify a fee quote for a zero or negative amount is rejected.
    When a customer requests a fee quote for a zero or negative amount
    Then the request is rejected

  Scenario: Verify one tenant cannot see or use another tenant's pricing.
    Given another tenant has its own pricing configured
    When a customer requests a fee quote
    Then only my tenant's pricing is visible and used

  Scenario: Verify a transaction is blocked when no price is configured for it.
    Given no price is configured for the transaction
    When the customer attempts the transaction
    Then the transaction is blocked before any charge is assembled

  Scenario: Verify a flat fee is charged regardless of the transfer amount.
    Given a flat fee is configured
    When the customer transfers any amount
    Then the same flat fee is charged

  Scenario: Verify a percentage fee never exceeds its configured cap.
    Given a percentage fee with a cap is configured
    When the customer transfers a large amount
    Then the fee is capped at the configured maximum

  Scenario: Verify an explicitly configured zero fee charges nothing.
    Given a zero fee is explicitly configured
    When the customer transacts
    Then no fee is charged

  Scenario: Verify collected fees are gathered into one account rather than duplicated.
    Given fees are collected into a system account
    When fees are collected repeatedly
    Then they are gathered into a single fee account rather than duplicated

  Scenario: Verify a transaction is blocked when neither a price nor a limit is configured.
    Given neither a price nor a limit is configured for the transaction
    When the customer attempts the transaction
    Then the transaction is blocked even with any bypass flag turned off

  Scenario: Verify a transaction is allowed once both a price and a limit are configured.
    Given both a price and a limit are configured for the transaction
    When the customer attempts the transaction
    Then the transaction is allowed

  Scenario: Verify a transaction is blocked when no limit is configured for it.
    Given a price is configured but no limit is
    When the customer attempts the transaction
    Then the transaction is blocked

  Scenario: Verify the block message says which customer type has no configuration.
    Given a customer type has no configuration
    When the transaction is blocked
    Then the block message names that customer type

  Scenario: Verify configuration for one customer type does not unblock another customer type.
    Given only one customer type is configured
    When a customer of a different type transacts
    Then that customer is still blocked

  Scenario: Verify a transaction is allowed when the customer's own type is configured.
    Given the customer's own type has both a price and a limit configured
    When the customer transacts
    Then the transaction is allowed

  Scenario: Verify the fee tier matching the transfer amount is applied.
    Given fees are configured in amount tiers
    When the customer transfers an amount within a tier
    Then that tier's fee is applied

  Scenario: Verify an amount-specific fee tier overrides the catch-all price.
    Given both an amount-specific tier and a catch-all price are configured
    When the customer transfers an amount within the specific tier
    Then the amount-specific tier overrides the catch-all price

  Scenario: Verify each customer type is charged its own configured price for a tier.
    Given a tier has its own price per customer type
    When customers of different types transfer within that tier
    Then each is charged their own type's configured price

  Scenario: Verify a single catch-all price applies to every transfer amount.
    Given only a single catch-all price is configured
    When the customer transfers any amount
    Then the catch-all price applies

  Scenario: Verify collected commission is gathered into one holding account.
    Given commission is collected into a holding account
    When commission is collected repeatedly
    Then it is gathered into a single commission holding account

  Scenario: Verify collected tax is gathered into one holding account.
    Given tax is collected into a holding account
    When tax is collected repeatedly
    Then it is gathered into a single tax holding account

  Scenario: Verify commission and tax holding accounts are not subject to customer balance limits.
    Given commission and tax holding accounts receive credits
    When those accounts are credited
    Then the customer balance ceiling guard does not apply to them

  Scenario: Verify the configured tax is added to the fee and commission.
    Given a tax percentage is configured
    When the charge is assembled
    Then the tax is added on top of the fee and commission

  Scenario: Verify tax can be configured as included in or added on top of the charge.
    Given tax can be configured as inclusive or exclusive
    When the charge is assembled
    Then the inclusive or exclusive flag is surfaced on the result

  Scenario: Verify no tax is charged when none is configured.
    Given no tax is configured
    When the charge is assembled
    Then no tax is charged

  Scenario: Verify each customer type is charged its own configured price.
    Given each customer type has its own configured price
    When customers of different types transact
    Then each is charged their own type's price

  Scenario: Verify a customer with no type-specific price falls back to the default price.
    Given a customer type has no price of its own but a default price exists
    When a customer of that type transacts
    Then the default price is charged

  Scenario: Verify a transaction is blocked when no price is configured for the customer.
    Given no price is configured for the customer
    When the customer attempts the transaction
    Then the transaction is blocked
