Feature: Instruments catalog — admin control
  As a platform administrator
  I want to add value units to the tenant catalog
  So that wallets and points accounts can reference them

  Scenario: Verify an admin can add a new instrument to the tenant catalog
    Given I am an admin on the Instruments page for a tenant
    And I have opened the "New instrument" dialog
    When I enter a code, symbol and display name and create the instrument
    Then the instrument is created for the tenant with the code upper-cased
    And the dialog closes

  Scenario: Verify an admin can backfill accounts for existing users when adding an instrument
    Given I am an admin on the Instruments page for a tenant
    And I have opened the "New instrument" dialog
    When I fill the instrument details and tick "create accounts for existing users"
    Then the instrument is created with the backfill flag set

  Scenario: Verify an invalid instrument code is rejected before anything is sent
    Given I am an admin on the Instruments page for a tenant
    And I have opened the "New instrument" dialog
    When I enter a code that does not start with a letter
    Then I am told the code format is invalid
    And nothing is sent to the backend

  Scenario: Verify a failed instrument creation shows the error to the admin
    Given I am an admin on the Instruments page for a tenant
    And I have opened the "New instrument" dialog
    When I create an instrument whose code is already taken
    Then the error code and message are shown
    And the dialog stays open
