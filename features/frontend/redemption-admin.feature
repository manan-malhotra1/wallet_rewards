Feature: Redemption administration — providers and manual review
  As a platform administrator
  I want to register redemption providers and triage stuck redemptions
  So that cash-out and voucher payouts can be configured and resolved

  Scenario: Verify an admin can register an airtime redemption provider
    Given I am an admin on the Redemption page for a tenant
    And I have opened the "Register redemption provider" dialog
    When I enter a provider name and register it
    Then the provider is registered for the tenant with the retry defaults
    And the dialog closes

  Scenario: Verify registration is blocked when the provider name is missing
    Given I am an admin on the Redemption page for a tenant
    And I have opened the "Register redemption provider" dialog
    When I register without entering a provider name
    Then I am told the provider name is required
    And nothing is sent to the backend

  Scenario: Verify a too-short HMAC secret is refused before anything is sent
    Given I am an admin on the Redemption page for a tenant
    And I have opened the "Register redemption provider" dialog
    When I enter a provider name but an HMAC secret under 32 characters
    Then I am told the shared secret must be at least 32 characters
    And nothing is sent to the backend

  Scenario: Verify a failed provider registration shows the error to the admin
    Given I am an admin on the Redemption page for a tenant
    And I have opened the "Register redemption provider" dialog
    When I register a provider whose name is already taken
    Then the error code and message are shown
    And the dialog stays open

  Scenario: Verify an admin sees a stuck redemption held for review with its details
    Given I am an admin on the Redemption page manual-review queue for a tenant
    When a redemption is held for review with an amount, retry count and failure reason
    Then I see the user, amount, retry count and failure reason
    And the status is shown as a "needs review" pill

  Scenario: Verify an admin still sees a redemption when the user's name is unavailable
    Given I am an admin on the Redemption page manual-review queue for a tenant
    When a held redemption has no resolvable user name
    Then a short prefixed user id is shown instead
    And a missing failure reason is shown as an em dash

  Scenario: Verify an admin sees every queued redemption listed for review
    Given I am an admin on the Redemption page manual-review queue for a tenant
    When multiple redemptions are held for review
    Then each one is listed with a "needs review" status
