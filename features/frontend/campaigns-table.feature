Feature: Campaigns table row actions
  As a rewards admin
  I want per-row View, Edit and Deactivate actions on the campaigns list
  So that I can inspect and manage each campaign in place.

  Background:
    Given I am signed in as an admin operator
    And I am on the Campaigns page with at least one campaign

  Scenario: Verify an admin can open a campaign's details from its row
    When I click the View action on a campaign's row
    Then the campaign detail drawer opens
    And no other campaign surface is open

  Scenario: Verify an admin can open the edit dialog for a campaign from its row
    When I click the Edit action on a campaign's row
    Then the edit campaign dialog opens
    And no other campaign surface is open

  Scenario: Verify an admin can open the deactivate dialog for a campaign from its row
    When I click the Deactivate action on a campaign's row
    Then the deactivate campaign dialog opens
    And no other campaign surface is open
