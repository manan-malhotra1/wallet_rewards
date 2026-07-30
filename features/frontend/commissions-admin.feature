Feature: Commission schedule admin
  As an administrator setting agent commissions, I can propose a commission
  schedule for a service through the maker-checker pipeline, and I am protected
  from sending an invalid schedule or a silent failure. Each scenario maps
  one-to-one to a Vitest interaction test co-located with
  create-commission-dialog.tsx.

  Background:
    Given I am an administrator on the Commissions screen
    And a service and a currency are available

  Scenario: Verify an admin can propose a new agent commission for a service
    Given I open the new commission schedule dialog
    When I enter a fixed commission for the band and propose the change
    Then the commission schedule is proposed for approval with my band and scope
    And the payload carries no account type
    And the dialog closes

  Scenario: Verify a commission proposal is blocked when a band's amounts are inverted
    Given I open the new commission schedule dialog
    When I set a band whose upper amount is below its lower amount and propose the change
    Then I am told the upper bound must be greater than the lower bound
    And nothing is sent for approval

  Scenario: Verify a rejected commission proposal shows the error to the admin
    Given I open the new commission schedule dialog
    And the backend will reject the proposal
    When I enter a fixed commission for the band and propose the change
    Then the returned error code and reason are shown
    And the dialog stays open so I can adjust and retry
