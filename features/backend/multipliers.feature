Feature: Bonus point multipliers
  As a business administrator
  I want to run promotions that multiply the points customers earn
  So that I can drive engagement during special campaigns

  Background:
    Given a business is running on the rewards platform
    And customers earn points from reward rules

  Scenario: Verify points are earned at the normal rate when no bonus is active
    Given no bonus multiplier is active
    When a customer earns points
    Then the points are earned at the normal rate

  Scenario: Verify a business-wide bonus increases the points every customer earns
    Given a business-wide bonus multiplier is active
    When any customer earns points
    Then the points earned are increased by the bonus

  Scenario: Verify a bonus multiplier stops applying after the promotion ends
    Given a bonus multiplier whose promotion has already ended
    When a customer earns points
    Then the points are earned at the normal rate

  Scenario: Verify a targeted bonus only boosts points for customers in the chosen group
    Given a bonus multiplier targeted at a specific group of customers
    When a customer outside the group earns points
    Then the points are earned at the normal rate
    But when a customer in the group earns points the bonus is applied

  Scenario: Verify only the largest bonus applies when several could apply at once
    Given several bonus multipliers could apply to the same customer
    When the customer earns points
    Then only the largest bonus is applied and the bonuses do not stack

  Scenario: Verify an admin can create a bonus multiplier
    Given I am an administrator
    When I create a bonus multiplier for my business
    Then the multiplier is created

  Scenario: Verify a bonus multiplier with an end date before its start date is rejected
    Given I am an administrator
    When I try to create a bonus multiplier whose end date is before its start date
    Then the request is rejected as invalid

  Scenario: Verify a bonus multiplier that is zero or negative is rejected
    Given I am an administrator
    When I try to create a bonus multiplier of zero or a negative value
    Then the request is rejected as invalid
