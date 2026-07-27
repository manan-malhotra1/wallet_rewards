Feature: Ledger invariants
  As a platform operator
  I want the ledger to stay balanced and append-only at all times
  So that money can always be accounted for and history can never be rewritten

  Background:
    Given a tenant is configured on the platform
    And accounts exist to move money between

  Scenario: Verify every completed transaction balances to zero across accounts
    Given a series of balanced transactions has been posted
    When the whole ledger is totalled
    Then credits and debits net to zero across all accounts

  Scenario: Verify ledger entries can never be edited after they are written
    When the ledger entries are inspected
    Then they carry no way to be edited after being written
