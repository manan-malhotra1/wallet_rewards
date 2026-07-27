Feature: Browsing my rewards
  As a rewards customer
  I want to see featured campaigns, my points activity, and my rewards summary
  So that I understand what I can earn and what I have already earned and redeemed

  Background:
    Given a business is running on the rewards platform
    And I am a signed-in customer of that business

  # ---------------------------------------------------------------------------
  # Featured campaign card
  # ---------------------------------------------------------------------------

  Scenario: Verify a customer sees the active featured campaign for their tenant.
    Given my business is running an active campaign right now
    When I open the home screen
    Then I see that campaign highlighted with its name, reward, and description

  Scenario: Verify a customer with no running campaigns sees an empty card, not an error.
    Given my business has no campaigns running
    When I open the home screen
    Then I see an empty featured card rather than an error

  Scenario: Verify a customer does not see a campaign that has been switched off.
    Given my business has a campaign that has been switched off
    When I open the home screen
    Then I see no featured campaign

  Scenario: Verify a customer does not see a campaign whose dates have passed.
    Given my business has a campaign whose dates have already passed
    When I open the home screen
    Then I see no featured campaign

  Scenario: Verify a customer sees the most recently launched campaign when several run.
    Given my business is running more than one eligible campaign
    When I open the home screen
    Then I see the most recently launched one

  Scenario: Verify a customer never sees a featured campaign belonging to another tenant.
    Given another business is running a campaign
    When I open the home screen
    Then I do not see that other business's campaign

  Scenario: Verify a signed-out visitor cannot see any featured campaign.
    Given I am not signed in
    When I ask for the featured campaign
    Then the request is refused as unauthenticated
    And no campaign details are revealed

  Scenario: Verify a visitor with an invalid session cannot see any featured campaign.
    Given I present an invalid session
    When I ask for the featured campaign
    Then the request is refused as unauthenticated

  # ---------------------------------------------------------------------------
  # Points activity history
  # ---------------------------------------------------------------------------

  Scenario: Verify a customer with no points sees an empty history, not an error.
    Given I have never earned any points
    When I open my points history
    Then I see an empty history rather than an error

  Scenario: Verify each earned-points entry shows the reward that granted it.
    Given I have earned points from a named reward
    When I open my points history
    Then each earned-points entry names the reward that granted it

  Scenario: Verify a customer's points history lists the most recent activity first.
    Given I have earned and redeemed points over time
    When I open my points history
    Then my activity is listed with the most recent first

  Scenario: Verify a customer never sees points activity from another tenant.
    Given a customer of another business has points activity
    When I open my own points history
    Then I only ever see activity from my own business

  # ---------------------------------------------------------------------------
  # Rewards summary and redemption history
  # ---------------------------------------------------------------------------

  Scenario: Verify a customer who has earned no points sees a blank summary.
    Given I have never earned any points
    When I open my rewards summary
    Then I see a blank summary

  Scenario: Verify a customer's summary shows the total points they have earned.
    Given I have earned points from more than one reward
    When I open my rewards summary
    Then my summary shows the total points I have earned

  Scenario: Verify a customer's summary shows the total points they have redeemed.
    Given I have earned points and then redeemed some of them
    When I open my rewards summary
    Then my summary shows the total points I have redeemed

  Scenario: Verify a customer's redemption history lists their most recent redeems first.
    Given I have made more than one redemption
    When I open my redemption history
    Then my redemptions are listed with the most recent first
