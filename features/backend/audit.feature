Feature: Reading the audit trail
  As an operator
  I want every recorded action to name the people involved and page reliably
  So that the trail is readable years later without decoding raw identifiers

  Background:
    Given a tenant is configured on the platform
    And a customer exists in that tenant

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

  Scenario: Verify the audit log pages in stable newest-first windows
    Given several audit entries were recorded in order
    When the audit log is read one window at a time
    Then each window returns the next entries newest first with none repeated or skipped

  Scenario: Verify an invalid page position is rejected rather than silently corrected
    When the audit log is read from a negative page position
    Then the request is rejected as invalid
