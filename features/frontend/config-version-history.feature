Feature: Config version history
  As an administrator reviewing configuration changes
  I want to see the version history of a configuration
  So that I understand how it reached its current state and can roll back safely.

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And I am viewing a configuration's details

  Scenario: Verify a config created during setup shows a baseline version
    Given a configuration was created during initial setup
    And it has never been edited through the approval flow
    When I open its version history
    Then I see a single "Current (baseline)" version holding its present values
    And that baseline is attributed to the system
    And it offers no "restore" option because it is already the current version

  Scenario: Verify older versions can be restored when a config has approved edit history
    Given a configuration has been changed and approved at least once
    When I open its version history
    Then I see each approved version in order, with the most recent marked active
    And I can choose an earlier version and propose restoring it
    And restoring it goes back through the normal approval flow before taking effect
