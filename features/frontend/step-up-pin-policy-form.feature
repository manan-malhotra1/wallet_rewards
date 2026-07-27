Feature: Step-up PIN policy form
  As an administrator managing step-up PIN policies
  I want the policy dialog to preserve the policy's own service and derive the right currency
  So that a proposed change never silently mismatches its scope

  Background:
    Given I am an administrator using the admin portal
    And the step-up PIN policy dialog is open

  Scenario: Verify editing a policy keeps its own service instead of resetting it
    Given I am editing a live "cash_in" step-up policy of "500" "ZAR"
    When I propose the change without altering it
    Then the proposed update keeps the transaction type "cash_in", currency "ZAR" and threshold "500"

  Scenario: Verify a money transfer policy defaults to Rand (ZAR)
    Given I am creating a new step-up policy
    When I propose the change without picking a different service
    Then the proposed policy is a "p2p" money transfer defaulting to currency "ZAR"

  Scenario: Verify a rewards redemption policy uses points, not currency
    Given I am creating a new step-up policy
    When I choose the "Redemption (points)" service and propose the change
    Then the proposed policy is a "redemption" using currency "PTS" instead of a money currency
