Feature: Reward budget caps
  As a business administrator
  I want to cap how many points my business gives away
  So that a rewards programme cannot overspend its budget

  Background:
    Given a business is running on the rewards platform
    And customers can earn points from reward rules

  Scenario: Verify rewards are issued normally when no budget limit is set
    Given no reward budget has been set for my business
    When a customer qualifies for a reward
    Then the reward is issued normally with no budget getting in the way

  Scenario: Verify rewards stop once the business reward budget is exhausted
    Given my business has a lifetime reward budget of 500 points
    When a reward of 600 points would be issued
    Then the reward is refused because it would exceed the budget

  Scenario: Verify an admin can see how much of a reward budget has been used
    Given my business has a reward budget of 1000 points
    When I view the budget
    Then I can see how much has been used, how much remains, and the percentage consumed
