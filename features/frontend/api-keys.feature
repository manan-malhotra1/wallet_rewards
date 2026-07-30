Feature: API keys — admin control
  As a platform administrator
  I want to mint API keys for partners and merchants
  So that external systems can call the tenant's APIs securely

  Scenario: Verify an admin can mint a partner API key and see its one-time secret
    Given I am an admin on the API keys page for a tenant
    And I have opened the "New API key" dialog
    When I enter a label and create the key without binding a merchant
    Then the key is minted for the tenant with no merchant bound
    And the one-time secret and key id are revealed for me to copy

  Scenario: Verify an admin can bind a merchant so the key can call cash-in
    Given I am an admin on the API keys page for a tenant
    And I have opened the "New API key" dialog
    When I look up a merchant by identifier and the lookup resolves a merchant
    And I create the key
    Then the key is minted bound to that merchant's user id

  Scenario: Verify minting is blocked when the looked-up user is not a merchant
    Given I am an admin on the API keys page for a tenant
    And I have opened the "New API key" dialog
    When I look up an identifier that resolves to a consumer
    Then I am warned that the user is not a merchant
    And the Create button is disabled so no key is minted

  Scenario: Verify a failed key creation shows the error to the admin
    Given I am an admin on the API keys page for a tenant
    And I have opened the "New API key" dialog
    When I create the key and the backend rejects the request
    Then the error code and message are shown
    And the dialog stays open so I can retry
