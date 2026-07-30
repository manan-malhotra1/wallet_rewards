Feature: Pricing schedule admin
  As an administrator setting fees, I can propose a pricing schedule for a
  service through the maker-checker pipeline, and I am protected from sending an
  invalid schedule or a silent failure. Each scenario maps one-to-one to a
  Vitest interaction test co-located with create-pricing-dialog.tsx.

  Background:
    Given I am an administrator on the Pricing screen
    And a service and a currency are available to price

  Scenario: Verify an admin can propose a new fee for a service
    Given I open the new pricing schedule dialog
    When I enter a fixed fee for the band and propose the change
    Then the pricing schedule is proposed for approval with my band and scope
    And the dialog closes

  Scenario: Verify a fee proposal is blocked when a band's amounts are inverted
    Given I open the new pricing schedule dialog
    When I set a band whose upper amount is below its lower amount and propose the change
    Then I am told the upper bound must be greater than the lower bound
    And nothing is sent for approval

  Scenario: Verify a rejected fee proposal shows the error to the admin
    Given I open the new pricing schedule dialog
    And the backend will reject the proposal
    When I enter a fixed fee for the band and propose the change
    Then the returned error code and reason are shown
    And the dialog stays open so I can adjust and retry
