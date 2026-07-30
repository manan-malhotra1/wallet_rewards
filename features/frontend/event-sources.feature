Feature: Event sources — admin control
  As a platform administrator
  I want to register external event sources
  So that only trusted systems can publish reward-triggering events

  Scenario: Verify an admin can register an external event source
    Given I am an admin on the Events page for a tenant
    And I have opened the "Register event source" dialog
    When I enter a name and a source key and register the source
    Then the source is registered for the tenant with those details
    And the dialog closes

  Scenario: Verify registration is blocked when the name and source key are missing
    Given I am an admin on the Events page for a tenant
    And I have opened the "Register event source" dialog
    When I register without entering a name or source key
    Then I am told the name and source key are required
    And nothing is sent to the backend

  Scenario: Verify a malformed field mapping is refused before anything is sent
    Given I am an admin on the Events page for a tenant
    And I have opened the "Register event source" dialog
    When I enter a name and source key but an invalid field-mapping JSON
    Then I am told the field mapping must be valid JSON
    And nothing is sent to the backend

  Scenario: Verify a too-short HMAC secret is refused before anything is sent
    Given I am an admin on the Events page for a tenant
    And I have opened the "Register event source" dialog
    When I enter a name and source key but an HMAC secret under 32 characters
    Then I am told the shared secret must be at least 32 characters
    And nothing is sent to the backend

  Scenario: Verify a failed registration shows the error to the admin
    Given I am an admin on the Events page for a tenant
    And I have opened the "Register event source" dialog
    When I register a source whose source key is already taken
    Then the error code and message are shown
    And the dialog stays open
