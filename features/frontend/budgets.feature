Feature: Rules & rewards — managing reward budgets
  As a platform administrator
  I want to cap how much reward can be issued in a window
  So that reward spend stays within agreed limits

  Background:
    Given an administrator has opened the new-budget dialog

  Scenario: Verify an admin can create a tenant-wide reward budget
    When the admin accepts the tenant-wide defaults and creates the budget
    Then a tenant-scoped budget is submitted in PTS with a lifetime window and a 10000 cap
    And the admin sees a "Budget created" confirmation
    And the dialog closes

  Scenario: Verify a budget cannot be created without a positive cap
    When the admin clears the cap amount and tries to create the budget
    Then the admin is told the cap must be a positive number
    And no budget is submitted

  Scenario: Verify a rejected budget shows the reason and keeps the form open
    Given the backend will reject the budget because one already exists for this tenant
    When the admin creates the budget
    Then the "budget already exists" reason is shown
    And the dialog stays open
