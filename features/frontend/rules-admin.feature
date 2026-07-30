Feature: Rules & rewards — creating a reward rule
  As a platform administrator
  I want to stand up a reward rule through the campaign wizard
  So that qualifying customer activity is rewarded automatically

  Background:
    Given an administrator has opened the create-campaign wizard
    And at least one active service (P2P Transfer) is available

  Scenario: Verify an admin can create a milestone reward rule
    Given the admin has chosen the Milestone rule type
    When the admin names it "Weekly P2P milestone", sets a count threshold of 5 and a reward of 200 points
    And the admin activates the campaign
    Then the milestone rule is submitted for the tenant with the P2P service, count threshold 5 and a 200-point reward
    And no inline budget is attached
    And the admin sees a "Campaign activated" confirmation

  Scenario: Verify an admin can create a first-time reward rule
    Given the admin has chosen the First-time rule type
    When the admin names it "Welcome bonus" and sets a reward of 50 points
    And the admin activates the campaign
    Then a first-time rule is submitted for the tenant with the P2P service and a 50-point reward

  Scenario: Verify a campaign is blocked without a name and reward value
    Given the admin has chosen the Milestone rule type
    When the admin activates the campaign without entering a name or reward value
    Then the admin is told the name and reward value are required
    And no campaign is submitted

  Scenario: Verify a failed campaign creation shows the backend error
    Given the admin has chosen the Milestone rule type
    And the backend will reject the campaign because no pricing config resolves
    When the admin fills in a name and reward value and activates the campaign
    Then the pricing-config error is shown in the wizard
    And the wizard stays open so the admin can correct it
