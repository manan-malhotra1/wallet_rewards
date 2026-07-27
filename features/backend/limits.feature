Feature: Transaction limits
  As a platform administrator
  I want per-transaction, rolling-window and wallet-balance limits enforced on customers
  So that customers stay within the configured amounts and limits never leak across tenants

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And a customer is transacting on my tenant

  Scenario: Verify a transaction is allowed through when no limit is configured for it.
    Given no limit is configured for the transaction type
    When the customer transacts
    Then the transaction is allowed through

  Scenario: Verify a transfer below the minimum amount is rejected.
    Given a minimum amount is configured for the transaction
    When the customer transacts for less than the minimum
    Then the transaction is rejected

  Scenario: Verify a transfer above the maximum amount is rejected.
    Given a maximum amount is configured for the transaction
    When the customer transacts for more than the maximum
    Then the transaction is rejected

  Scenario: Verify a customer cannot exceed their daily number of transactions.
    Given a daily transaction count cap is configured
    When the customer transacts more times than the daily cap allows
    Then the transaction over the cap is rejected

  Scenario: Verify each customer type is held to its own configured limits.
    Given a customer type has its own configured limit
    When a customer of that type transacts
    Then the customer's own type limit is applied rather than the default

  Scenario: Verify a customer with no type-specific limit falls back to the default limit.
    Given a customer type has no limit of its own but a default limit exists
    When a customer of that type transacts
    Then the default limit is applied

  Scenario: Verify the default limit applies to every customer type without its own limit.
    Given only a default limit is configured
    When customers of any type transact
    Then the default limit is applied to all of them

  Scenario: Verify a duplicate default limit for the same transaction cannot be created.
    Given a default limit already exists for the transaction
    When I try to create a second default limit for the same transaction
    Then the creation is rejected as a duplicate

  Scenario: Verify one tenant cannot see or use another tenant's wallet limits.
    Given another tenant has its own wallet limits configured
    When I resolve wallet limits for my tenant
    Then only my tenant's wallet limits are visible and used

  Scenario: Verify money coming in is allowed through when no wallet limit is configured.
    Given no wallet limit is configured for incoming money
    When money is credited to the customer's wallet
    Then the credit is allowed through

  Scenario: Verify money coming in that would push a wallet over its balance ceiling is rejected.
    Given a wallet balance ceiling is configured
    When incoming money would push the balance above the ceiling
    Then the credit is rejected

  Scenario: Verify money coming in that keeps a wallet at or under its balance ceiling is allowed.
    Given a wallet balance ceiling is configured
    When incoming money keeps the balance at or below the ceiling
    Then the credit is allowed

  Scenario: Verify a customer cannot exceed the number of times they can receive money in a day.
    Given a daily receive count cap is configured
    When the customer receives money more times than the daily cap allows
    Then the receipt over the cap is rejected

  Scenario: Verify a customer cannot exceed the total amount they can receive in a week.
    Given a weekly receive value cap is configured
    When the customer's received total for the week would exceed the cap
    Then the receipt over the cap is rejected

  Scenario: Verify a transfer to a full recipient wallet is declined without revealing the balance.
    Given a recipient wallet is at its balance ceiling
    When a sender transfers money to that recipient
    Then the transfer is declined without disclosing the recipient's balance

  Scenario: Verify a transfer to a recipient at their limit is declined without revealing it.
    Given a recipient is at their receive limit
    When a sender transfers money to that recipient
    Then the transfer is declined with a recipient-limit-reached message that reveals nothing further

  Scenario: Verify money received more than a week ago no longer counts toward the weekly limit.
    Given a weekly receive value cap is configured
    And the customer received money more than seven days ago
    When the customer receives money now
    Then the older receipts do not count toward the weekly limit

  Scenario: Verify money going out is allowed through when no wallet limit is configured.
    Given no wallet limit is configured for outgoing money
    When money is debited from the customer's wallet
    Then the debit is allowed through

  Scenario: Verify a customer cannot exceed the number of times they can send money in a day.
    Given a daily send count cap is configured
    When the customer sends money more times than the daily cap allows
    Then the send over the cap is rejected

  Scenario: Verify a customer cannot exceed the total amount they can send in a week.
    Given a weekly send value cap is configured
    When the customer's sent total for the week would exceed the cap
    Then the send over the cap is rejected

  Scenario: Verify fees are not counted toward how much a customer can send.
    Given a weekly send value cap is configured
    When the customer sends money and a fee is charged on top
    Then only the sent principal counts toward the cap, not the fee

  Scenario: Verify a single send counts once toward the customer's limit even when a fee is charged.
    Given a daily send count cap is configured
    When the customer makes one send that also charges a fee
    Then it counts as a single transaction toward the cap

  Scenario: Verify a customer's send limit applies across all the ways they can send money.
    Given a send limit is configured
    When the customer sends money through different services
    Then all of those sends count together toward the same limit

  Scenario: Verify money sent more than a week ago no longer counts toward the weekly limit.
    Given a weekly send value cap is configured
    And the customer sent money more than seven days ago
    When the customer sends money now
    Then the older sends do not count toward the weekly limit

  Scenario: Verify a customer cannot exceed their weekly number of transactions.
    Given a weekly transaction count cap is configured
    When the customer transacts more times than the weekly cap allows
    Then the transaction over the cap is rejected

  Scenario: Verify a customer cannot exceed their weekly transaction total.
    Given a weekly transaction value cap is configured
    When the customer's transaction total for the week would exceed the cap
    Then the transaction over the cap is rejected

  Scenario: Verify a customer cannot exceed their monthly number of transactions.
    Given a monthly transaction count cap is configured
    When the customer transacts more times than the monthly cap allows
    Then the transaction over the cap is rejected

  Scenario: Verify transactions older than a week no longer count toward the weekly limit.
    Given a weekly cap is configured
    And the customer has transactions older than seven days
    When the weekly usage is calculated
    Then transactions older than the week are excluded

  Scenario: Verify transactions too old for the weekly limit still count toward the monthly limit.
    Given both a weekly and a monthly cap are configured
    And the customer has transactions older than a week but within the month
    When the caps are evaluated
    Then those transactions are excluded from the weekly count but still counted monthly

  Scenario: Verify only the limits a tenant has actually configured are enforced.
    Given a tenant has configured only some of the available limit windows
    When the customer transacts
    Then only the configured windows are checked and the rest are ignored
