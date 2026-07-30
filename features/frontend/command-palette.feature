Feature: Command palette
  As an admin operator
  I want a global command palette to navigate and switch tenant
  So that I can move around the console quickly from the keyboard.

  Background:
    Given I am signed in as an admin operator
    And more than one tenant is available to me

  Scenario: Verify the command palette opens and runs a command
    When I open the command palette
    And I select "Go to Users"
    Then I am routed to the Users page

  Scenario: Verify an admin can search the command palette to find a command
    When I open the command palette
    And I type "audit"
    Then the "Go to Audit log" command is shown
    And non-matching commands are hidden

  Scenario: Verify an admin can switch tenant from the command palette
    When I open the command palette
    And I select the tenant "Sasai ZW"
    Then that tenant becomes active
    And the server data refreshes
