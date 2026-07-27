Feature: Ledger and wallet balances
  As a platform operator running a wallet
  I want every money movement recorded safely with clear balance limits
  So that customer and operator balances always stay correct and trustworthy

  Background:
    Given a customer has a wallet
    And every money movement is recorded as a balanced ledger entry

  # --- Wallet balance limits ---

  Scenario: Verify a customer cannot hold more than their wallet's maximum balance
    Given the wallet has a maximum balance set
    When money is added that would push the wallet above that maximum
    Then the top-up is refused and the wallet balance is unchanged

  Scenario: Verify a refund can be received even when it pushes a wallet past its maximum balance
    Given the wallet has a maximum balance set
    When a refund is paid back into the wallet that takes it above the maximum
    Then the refund is allowed and the money lands in the wallet

  Scenario: Verify a merchant collection account has no balance ceiling
    Given a merchant collection account and a currency maximum are set up
    When a large amount is collected into the merchant account
    Then the money lands in full because collection accounts have no ceiling

  Scenario: Verify a customer cannot spend more than their wallet balance
    Given the wallet is empty
    When the customer tries to spend money from it
    Then the payment is refused and the wallet balance is unchanged

  # --- Agent commission payouts ---

  Scenario: Verify an agent receives earned commission even at their wallet's maximum balance
    Given an agent's wallet is already at its maximum balance
    When the agent is paid commission they have earned
    Then the commission still lands in the agent's wallet

  Scenario: Verify an ordinary top-up over the wallet maximum is still refused
    Given a wallet is already at its maximum balance
    When an ordinary top-up over the maximum is attempted
    Then the top-up is refused and the wallet balance is unchanged

  # --- Operator float safeguards ---

  Scenario: Verify a payout is blocked when the operator float has run out
    Given the operator float is empty
    When an admin tries to pay out money to a customer from the float
    Then the payout is blocked and nothing moves

  Scenario: Verify a payout succeeds once the operator float has been topped up from the bank
    Given the operator float has been topped up from the bank
    When an admin pays out money to a customer from the float
    Then the payout succeeds and the float is drawn down by that amount

  Scenario: Verify a partner top-up is turned away without revealing that the operator float is empty
    Given the operator float is empty
    When a partner tries to top up a customer's wallet
    Then the request is turned away with only a generic unavailable message
    And nothing about the operator's float balance is revealed

  Scenario: Verify reversing a payout returns the money to the operator float
    Given a payout has been made from the operator float
    When that payout is reversed
    Then the money is returned to the operator float

  Scenario: Verify a customer overdraft is reported as insufficient funds, not as an empty float
    Given a customer wallet is empty
    When the customer tries to spend more than they hold
    Then the request is refused as insufficient customer funds

  Scenario: Verify two payouts at once can never drain the operator float below zero
    Given the operator float can only cover one of two payouts happening at once
    When both payouts are attempted at the same time
    Then only one payout succeeds and the float never goes below zero

  # --- Core ledger posting ---

  Scenario: Verify a balanced transaction is recorded and its entries appear
    When a balanced money movement is recorded
    Then the transaction is saved and both of its entries appear

  Scenario: Verify a transaction whose credits and debits do not match is refused
    When a money movement whose ins and outs do not match is recorded
    Then the transaction is refused

  Scenario: Verify a transaction with only one side is refused
    When a money movement is recorded with only one side
    Then the transaction is refused

  Scenario: Verify a transaction naming an account that does not exist is refused
    When a money movement names an account that does not exist
    Then the transaction is refused

  Scenario: Verify submitting the same transaction twice records it only once
    Given a transaction has already been recorded
    When the same transaction is submitted again
    Then the original transaction is returned and it is recorded only once

  Scenario: Verify a transaction that moves no money is refused
    When a money movement is recorded that moves no money at all
    Then the transaction is refused

  # --- Customer transaction receipts ---

  Scenario: Verify a transaction receipt number follows the expected format
    When a receipt number is produced for a transaction
    Then it follows the expected format

  Scenario: Verify every generated receipt number follows the expected format
    When a receipt number is produced for any transaction
    Then it always follows the expected format

  Scenario: Verify a receipt number keeps all its digits for high transaction counts
    When a receipt number is produced for a very high transaction count
    Then it keeps all of its digits

  Scenario: Verify every new transaction is given a customer receipt number
    When a new transaction is recorded
    Then it is given a customer receipt number

  Scenario: Verify each new transaction gets the next receipt number in sequence
    Given a transaction already has a receipt number
    When the next transaction is recorded for the same tenant
    Then its receipt number is the next one in sequence

  Scenario: Verify each tenant numbers its own transaction receipts independently
    Given two different tenants each record their first transaction
    When their receipt numbers are compared
    Then each tenant starts its own numbering from the beginning

  Scenario: Verify resubmitting a transaction keeps the same receipt number without skipping any
    Given a transaction has a receipt number
    When the same transaction is resubmitted
    Then it keeps the same receipt number and no numbers are skipped

  Scenario: Verify no two transactions within a tenant share a receipt number
    When several transactions are recorded for one tenant
    Then no two of them share the same receipt number
