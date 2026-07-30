Feature: Limits admin
  As an administrator setting transaction and wallet limits, I can propose a
  service limit or a wallet limit through the maker-checker pipeline, and I am
  protected from proposing an empty limit or missing a silent failure. Each
  scenario maps one-to-one to a Vitest interaction test co-located with
  create-limit-dialog.tsx and create-wallet-limit-dialog.tsx.

  Background:
    Given I am an administrator on the Limits screen
    And a service and a currency are available

  # --- Service limits (create-limit-dialog.tsx) ---------------------------

  Scenario: Verify an admin can propose a per-transaction cap for a service
    Given I open the new service limit dialog
    When I enter a max amount and a daily count cap and propose the change
    Then the service limit is proposed for approval with those caps and my scope
    And a blank cap is omitted rather than sent empty
    And the dialog closes

  Scenario: Verify a limit proposal is blocked when no cap is set
    Given I open the new service limit dialog
    When I propose the change without entering any cap
    Then I am told to set at least one cap
    And nothing is sent for approval

  Scenario: Verify a rejected limit proposal shows the error to the admin
    Given I open the new service limit dialog
    And the backend will reject the proposal
    When I enter a max amount and propose the change
    Then the returned error code and reason are shown
    And the dialog stays open so I can adjust and retry

  # --- Wallet limits (create-wallet-limit-dialog.tsx) ---------------------

  Scenario: Verify an admin can propose a max wallet balance and a send cap
    Given I open the new wallet limit dialog
    When I enter a max balance and a daily send count cap and propose the change
    Then the wallet limit is proposed for approval with the count cap coerced to a number
    And the dialog closes

  Scenario: Verify a wallet-limit proposal is blocked when nothing is set
    Given I open the new wallet limit dialog
    When I propose the change without a max balance or any cap
    Then I am told to set a max balance or at least one cap
    And nothing is sent for approval

  Scenario: Verify a rejected wallet-limit proposal shows the error to the admin
    Given I open the new wallet limit dialog
    And the backend will reject the proposal
    When I enter a max balance and propose the change
    Then the returned error code and reason are shown
    And the dialog stays open so I can adjust and retry
