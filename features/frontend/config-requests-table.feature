Feature: Config change requests table
  As an admin approver
  I want to open a config change request's details from the list
  So that I can review and act on pending configuration changes.

  Background:
    Given I am signed in as an admin operator
    And I am on the Config requests page with at least one pending request

  Scenario: Verify an admin can open a config request's details from the table
    When I click the View action on a request's row
    Then the full request is loaded for that request
    And the request detail drawer opens

  Scenario: Verify a failed request load shows an error and leaves the drawer closed
    Given loading the full request will fail
    When I click the View action on a request's row
    Then an error notification is shown
    And the request detail drawer stays closed
