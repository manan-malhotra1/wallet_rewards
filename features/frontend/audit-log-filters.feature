Feature: Audit log filtering
  As a compliance admin
  I want to narrow the audit log by the entity that was changed
  So that I can trace exactly what happened to a specific record.

  Background:
    Given I am signed in as an admin operator
    And I am on the Audit log page

  Scenario: Verify an admin can filter the audit log by entity type
    When I enter the entity type "redemption"
    And I press Filter
    Then the page reloads showing only "redemption" entries

  Scenario: Verify an admin can filter the audit log by entity type and ID together
    When I enter the entity type "redemption"
    And I enter the entity ID "abc-123"
    And I press Filter
    Then the page reloads showing only that entity's entries

  Scenario: Verify an admin can clear the audit log filters
    Given the audit log is filtered to entity type "redemption" and ID "abc-123"
    When I press Clear
    Then both filter fields are emptied
    And the page returns to the unfiltered audit log
