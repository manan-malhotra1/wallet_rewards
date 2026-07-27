Feature: Customer segments
  As a rewards program administrator
  I want to group customers into segments and target rewards at them
  So that offers reach the right audience and stay isolated to my own business

  Background:
    Given a business with an active rewards program
    And an administrator who can manage customer segments
    And customers who can be placed into segments

  # --- Managing customer segments ---

  Scenario: Verify an admin can create a customer segment
    When the admin creates a customer segment with a name and description
    Then the segment is saved under the business

  Scenario: Verify a segment cannot reuse an existing segment name
    Given the business already has a segment with a given name
    When the admin tries to create another segment with the same name
    Then the request is rejected as a duplicate

  Scenario: Verify a business only sees its own customer segments
    Given each of two businesses has created a segment
    When the admin lists one business's segments
    Then only that business's segment is returned

  Scenario: Verify adding a customer to a segment twice does not duplicate them
    Given a segment in the business
    When the admin adds the same customer to it twice
    Then the customer belongs to the segment just once

  Scenario: Verify a customer cannot be added to another business's segment
    Given a segment belonging to one business
    When an administrator of a different business tries to add a customer to it
    Then the request is not found

  Scenario: Verify an unknown customer cannot be added to a segment
    Given a segment in the business
    When the admin tries to add a customer who does not exist
    Then the request is not found

  # --- Segment-targeted rewards ---

  Scenario: Verify a reward only applies to customers in the targeted segment
    Given a reward rule targeted at a specific segment
    When a customer who is not in the segment qualifies
    Then the customer earns nothing
    When the same customer is added to the segment and qualifies again
    Then the customer earns the reward
