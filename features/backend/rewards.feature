Feature: Earning points rewards
  As a rewards customer
  I want to receive points when I do something the business rewards
  So that I am recognised and can build up a balance to redeem later

  Background:
    Given a business is running on the rewards platform
    And a reward rule grants points for a qualifying action
    And I am a customer of that business

  Scenario: Verify a customer's points balance increases when they earn a reward
    Given I have a points account
    When I complete an action that qualifies for the reward
    Then the configured points are added to my balance

  Scenario: Verify a repeated reward event does not award points twice
    Given I have already earned points for a qualifying action
    When the same qualifying action is processed again
    Then I keep my original reward
    And no extra points are added

  Scenario: Verify a reward cannot be granted to a customer without a points account
    Given I do not have a points account set up
    When an action that qualifies for a reward is processed
    Then the reward is refused
    And no points are issued
