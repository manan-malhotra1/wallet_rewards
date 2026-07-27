Feature: Reconciliation of pending redemptions
  As an operator
  I want stuck redemptions retried, escalated, and resolvable
  So that no payout is left hanging and every action is recorded and readable

  Background:
    Given a tenant is configured on the platform
    And a customer with points exists in that tenant

  Scenario: Verify an audit entry shows the operator's name
    Given an audit entry recorded against an operator with a profile
    When the audit log is read
    Then the entry shows the operator's display name

  Scenario: Verify an audit entry shows the acting customer's name
    Given an audit entry recorded against a customer
    When the audit log is read
    Then the entry shows the customer's name

  Scenario: Verify a system-generated audit entry shows a friendly system name
    Given an audit entry recorded by the system
    When the audit log is read
    Then the entry shows a friendly system name

  Scenario: Verify an audit entry from a partner key shows an API key name
    Given an audit entry recorded against a partner key
    When the audit log is read
    Then the entry shows an API key name

  Scenario: Verify an audit entry for an unknown operator shows no name
    Given an audit entry recorded against an operator with no profile
    When the audit log is read
    Then the entry shows no operator name

  Scenario: Verify an audit entry shows the name of the affected customer
    Given an audit entry whose affected record is a customer
    When the audit log is read
    Then the entry shows the affected customer's name

  Scenario: Verify an audit entry for a non-customer record shows no affected name and does not fail
    Given an audit entry whose affected record is not a customer
    When the audit log is read
    Then the entry shows no affected name and the read does not fail

  Scenario: Verify audit-log names are never resolved across a tenant boundary
    Given an audit entry about a customer in one tenant
    When the audit log is read under a different tenant
    Then that entry is not returned and its name is not exposed

  Scenario: Verify an operator can mark a stuck redemption as completed
    Given a redemption awaiting manual review
    When the operator resolves it as completed
    Then the redemption is finalised and the customer's balance stays reduced

  Scenario: Verify an operator can reverse a stuck redemption and restore the customer's balance
    Given a redemption awaiting manual review
    When the operator resolves it as reversed
    Then the redemption is failed and the customer's balance is restored

  Scenario: Verify only a redemption awaiting review can be manually resolved
    Given a redemption that is still pending and not under review
    When the operator tries to resolve it
    Then the request is rejected

  Scenario: Verify a redemption cannot be resolved from another tenant
    Given a redemption awaiting manual review in one tenant
    When an operator resolves it under a different tenant
    Then the request is rejected as not found

  Scenario: Verify manually resolving a redemption is recorded in the audit trail
    Given a redemption awaiting manual review
    When the operator resolves it
    Then an audit entry records the before and after state, the operator, and the reason

  Scenario: Verify the audit log only returns entries for the requested tenant
    Given a redemption was resolved in one tenant
    When the audit log is queried under a different tenant
    Then no entries are returned

  Scenario: Verify a stuck pending redemption is retried during reconciliation
    Given a pending redemption older than the threshold
    When a reconciliation sweep runs
    Then the redemption's retry count is increased and it stays pending

  Scenario: Verify a recent pending redemption is left alone during reconciliation
    Given a pending redemption newer than the threshold
    When a reconciliation sweep runs
    Then the redemption is not touched

  Scenario: Verify a completed redemption is left alone during reconciliation
    Given a redemption that has already completed
    When a reconciliation sweep runs
    Then the redemption is not touched

  Scenario: Verify a redemption that keeps failing is escalated for manual review
    Given a pending redemption that has reached its retry limit
    When a reconciliation sweep runs
    Then the redemption is escalated for manual review

  Scenario: Verify each reconciliation action is recorded in the audit trail
    Given a pending redemption older than the threshold
    When a reconciliation sweep runs
    Then exactly one audit entry records the action

  Scenario: Verify the pending-redemption list only shows the requested tenant's items
    Given a pending redemption exists in one tenant
    When the pending list is requested under a different tenant
    Then no items are returned

  Scenario: Verify the pending-redemption list shows each customer's name
    Given a pending redemption exists
    When the pending list is requested
    Then each item shows the customer's name and identifier

  Scenario: Verify the manual-review queue shows each customer's name
    Given a redemption has been escalated to manual review
    When the manual-review queue is requested
    Then each item shows the customer's name

  Scenario: Verify a reconciliation sweep for an unknown tenant is rejected
    When a reconciliation sweep is requested for a tenant that does not exist
    Then the request is rejected as not found
