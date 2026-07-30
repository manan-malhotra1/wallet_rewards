Feature: Rules & rewards — editing, deactivating and reviewing campaigns
  As a platform administrator
  I want to edit, deactivate and inspect existing campaigns
  So that I can keep reward programmes accurate and under control

  # --- Editing a campaign -------------------------------------------------

  Scenario: Verify an admin can rename a campaign and change its reward value
    Given an administrator is editing the "Weekly P2P milestone" campaign
    When the admin renames it to "Weekly P2P milestone v2" and sets the reward value to 350
    And the admin saves the changes
    Then the campaign is updated for the tenant with the new name, a 350 reward value and active status
    And the admin sees a "Campaign updated" confirmation
    And the dialog closes

  Scenario: Verify editing is blocked when the reward value is not positive
    Given an administrator is editing the "Weekly P2P milestone" campaign
    When the admin sets the reward value to 0 and saves
    Then the admin is told the reward value must be a positive number
    And no update is submitted

  Scenario: Verify a rejected edit shows the reason and keeps the form open
    Given an administrator is editing the "Weekly P2P milestone" campaign
    And the backend will reject the edit because the campaign is locked
    When the admin saves the changes
    Then the "campaign is locked" reason is shown
    And the dialog stays open

  # --- Deactivating a campaign -------------------------------------------

  Scenario: Verify deactivating a campaign asks for confirmation first
    Given an administrator has opened the deactivate dialog for the "Weekly P2P milestone" campaign
    Then the campaign name is shown and nothing has been deactivated yet
    When the admin cancels
    Then no deactivation is submitted and the dialog closes

  Scenario: Verify an admin can deactivate a campaign after confirming
    Given an administrator has opened the deactivate dialog for the "Weekly P2P milestone" campaign
    When the admin confirms the deactivation
    Then the campaign is deactivated for the tenant
    And the admin sees a "Campaign deactivated" confirmation
    And the dialog closes

  Scenario: Verify a failed deactivation shows the reason and keeps the dialog open
    Given an administrator has opened the deactivate dialog for the "Weekly P2P milestone" campaign
    And the backend will reject the deactivation because the campaign no longer exists
    When the admin confirms the deactivation
    Then the "no longer exists" reason is shown
    And the dialog stays open

  # --- Reviewing a campaign ----------------------------------------------

  Scenario: Verify an admin can review a campaign's full configuration and performance
    Given an administrator has opened the detail panel for the "Weekly P2P milestone" campaign
    Then the panel shows the milestone type, 200-point reward and count threshold of 5
    And the panel shows 1,234 total fires and 456 unique users rewarded
    And the panel describes the budget as both per-campaign and tenant-wide caps

  Scenario: Verify a campaign with no recorded activity shows placeholders
    Given an administrator has opened the detail panel for a campaign with no recorded activity
    Then the budget line shows a placeholder dash
    And no performance metrics are shown

  Scenario: Verify closing the detail panel dismisses it
    Given an administrator has opened the detail panel for the "Weekly P2P milestone" campaign
    When the admin closes the panel
    Then the panel is dismissed
