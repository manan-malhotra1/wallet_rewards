Feature: Reconciliation sweep — admin control
  As a platform administrator
  I want to run a reconciliation sweep on demand
  So that stuck redemptions are re-checked and escalated

  Scenario: Verify an admin can run a reconciliation sweep
    Given I am an admin on the Reconciliation page for a tenant
    When I click "Sweep now"
    Then the sweep runs for the active tenant
    And I see the result counts of scanned, bumped and escalated redemptions
    And the button re-enables once the sweep resolves

  Scenario: Verify an admin sees an error when a reconciliation sweep fails
    Given I am an admin on the Reconciliation page for a tenant
    When I click "Sweep now" and the backend is unreachable
    Then I see a failure notice with the error code
