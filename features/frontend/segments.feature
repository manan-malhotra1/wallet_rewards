Feature: Rules & rewards — managing customer segments
  As a platform administrator
  I want to create static customer cohorts
  So that I can target rewards at specific groups of users

  Background:
    Given an administrator has opened the new-segment dialog

  Scenario: Verify an admin can create a customer segment
    When the admin names it "vip-users" with the description "Top 1% by lifetime spend."
    And the admin creates the segment
    Then the segment is submitted for the tenant with that name and description
    And the admin sees a "Segment created" confirmation
    And the dialog closes

  Scenario: Verify a segment cannot be created without a name
    When the admin tries to create the segment without a name
    Then the admin is told the name is required
    And no segment is submitted

  Scenario: Verify a rejected segment shows the reason and keeps the form open
    Given the backend will reject the segment because the name is already taken
    When the admin names it "vip-users" and creates the segment
    Then the "name already exists" reason is shown
    And the dialog stays open
