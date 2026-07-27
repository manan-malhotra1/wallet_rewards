Feature: Currency catalog
  As an operator
  I want to manage the tenant's currencies and see them provisioned correctly
  So that every currency is ready to use and every change is auditable

  Background:
    Given a tenant is configured on the platform
    And the operator is signed in

  Scenario: Verify adding a money currency sets up its five system accounts
    When the operator adds a new money currency
    Then the five system accounts for that currency are created

  Scenario: Verify adding a money currency does not create the bank-mirror account
    When the operator adds a new money currency
    Then the bank-mirror account is deliberately not created

  Scenario: Verify adding a points currency sets up its points-issuance account
    When the operator adds a new points currency
    Then its points-issuance account is created
    And no money system accounts are created

  Scenario: Verify adding a points currency records one provisioned account in the audit trail
    When the operator adds a new points currency
    Then the audit entry records that one account was provisioned

  Scenario: Verify adding a money currency records five provisioned accounts in the audit trail
    When the operator adds a new money currency
    Then the audit entry records that five accounts were provisioned

  Scenario: Verify adding a currency does not duplicate system accounts that already exist
    Given some system accounts for the currency already exist
    When the operator adds that currency
    Then no duplicate system accounts are created

  Scenario: Verify the first transaction reuses the system account already provisioned
    Given a currency has been added and its system accounts provisioned
    When the first transaction needs a system account
    Then it reuses the existing account rather than creating a new one

  Scenario: Verify adding a currency is recorded in the audit trail
    When the operator adds a currency
    Then an audit entry records the creation with the operator as actor

  Scenario: Verify editing a currency records its before and after state
    Given a currency exists
    When the operator changes its status
    Then an audit entry records the state before and after the change

  Scenario: Verify removing a currency is recorded in the audit trail
    Given a currency exists
    When the operator removes it
    Then an audit entry records the removal

  Scenario: Verify the currency catalog cannot be listed without signing in
    When someone requests the catalog without signing in
    Then the request is refused

  Scenario: Verify the currency catalog lists both active and disabled currencies
    Given the tenant has both active and disabled currencies
    When the operator lists the catalog with no filter
    Then both active and disabled currencies are returned

  Scenario: Verify the currency catalog can be filtered to active currencies
    Given the tenant has both active and disabled currencies
    When the operator filters the catalog to active only
    Then only active currencies are returned

  Scenario: Verify one tenant's currency catalog does not show another tenant's currencies
    Given two tenants each have a currency
    When the operator lists one tenant's catalog
    Then only that tenant's currency is returned

  Scenario: Verify a new currency can be added to the catalog
    When the operator adds a new currency
    Then it is created and active in the catalog

  Scenario: Verify a currency code cannot be added twice in a tenant
    Given a currency code already exists in the tenant
    When the operator adds another currency with the same code
    Then the request is rejected as a conflict

  Scenario: Verify a currency code must be uppercase
    When the operator adds a currency with a lowercase code
    Then the request is rejected as invalid

  Scenario: Verify adding a currency can give every existing customer an account for it
    Given the tenant has an existing customer
    When the operator adds a currency and asks to assign it to existing customers
    Then that customer gets an account for the new currency

  Scenario: Verify adding a currency leaves existing customers without an account unless requested
    Given the tenant has an existing customer
    When the operator adds a currency without asking to assign it
    Then that customer gets no account for the new currency

  Scenario: Verify a currency's name, symbol, and status can be edited
    Given a currency exists
    When the operator edits its name, symbol, and status
    Then those fields are updated while the code and type stay the same

  Scenario: Verify a currency's code cannot be changed after creation
    Given a currency exists
    When the operator tries to change its code
    Then the request is rejected as invalid

  Scenario: Verify editing an unknown currency is rejected
    When the operator edits a currency that does not exist
    Then the request is rejected as not found

  Scenario: Verify a removed currency no longer appears in the catalog
    Given a currency exists
    When the operator removes it
    Then it no longer appears in the catalog

  Scenario: Verify a removed currency code can be added again
    Given a currency has been removed
    When the operator adds a currency with the same code again
    Then it is created successfully
