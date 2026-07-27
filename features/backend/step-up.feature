Feature: Step-up PIN policies
  As a platform administrator
  I want high-value transactions to require the customer to re-enter their PIN
  So that risky transfers are protected and the policy fails closed when misconfigured

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And a customer with a PIN set is making a transaction

  Scenario: Verify the PIN is required by default when no step-up policy exists.
    Given no step-up policy is configured for the transaction type
    And the customer supplies no PIN
    When the customer attempts the transaction
    Then the transaction is blocked and the customer is asked for their PIN

  Scenario: Verify a transaction proceeds with the correct PIN when no policy is set.
    Given no step-up policy is configured for the transaction type
    When the customer submits the transaction with the correct PIN
    Then the transaction proceeds

  Scenario: Verify a transaction is blocked when the customer enters the wrong PIN.
    Given no step-up policy is configured for the transaction type
    When the customer submits the transaction with an incorrect PIN
    Then the transaction is blocked as an invalid PIN

  Scenario: Verify no PIN is asked for an amount at or below the configured threshold.
    Given a step-up policy with an amount threshold is configured
    When the customer transacts for an amount at or below the threshold
    Then the transaction proceeds without asking for a PIN

  Scenario: Verify the customer is asked to re-enter their PIN above the configured amount.
    Given a step-up policy with an amount threshold is configured
    When the customer transacts for an amount above the threshold without a PIN
    Then the transaction is blocked and the customer is asked to re-enter their PIN

  Scenario: Verify no PIN is needed for a transfer at or below the configured amount.
    Given a step-up policy for peer transfers with an amount threshold is configured
    When the customer sends a transfer at or below the threshold
    Then the transfer proceeds without asking for a PIN

  Scenario: Verify a transfer is blocked when the customer enters the wrong PIN.
    Given a step-up policy for peer transfers requires a PIN above the threshold
    When the customer sends a transfer above the threshold with an incorrect PIN
    Then the transfer is blocked as an invalid step-up PIN

  Scenario: Verify a transfer completes when the customer re-enters the correct PIN.
    Given a step-up policy for peer transfers requires a PIN above the threshold
    When the customer sends a transfer above the threshold with the correct PIN
    Then the transfer completes

  Scenario: Verify a transfer completes with the correct PIN even when no step-up policy exists.
    Given no step-up policy is configured for peer transfers
    When the customer sends a transfer with the correct PIN
    Then the transfer completes

  Scenario: Verify one tenant cannot see another tenant's step-up policies.
    Given another tenant has its own step-up policies configured
    When I list the step-up policies
    Then I see only my own tenant's step-up policies

  Scenario: Verify viewing step-up policies requires an admin sign-in.
    Given I am not signed in
    When I request the step-up policies
    Then I am refused with an unauthorized response

  Scenario: Verify step-up policies can no longer be created directly, only through the approval flow.
    When I try to create a step-up policy directly
    Then the request is rejected because policies must go through the approval workflow

  Scenario: Verify step-up policies can no longer be deleted directly, only through the approval flow.
    When I try to delete a step-up policy directly
    Then the request is rejected because policies must go through the approval workflow
