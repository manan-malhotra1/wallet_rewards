Feature: Tenant management — create a new tenant
  As a platform administrator
  I want to provision a new tenant with its identity and optional branding
  So that a new business can go live with baseline instruments and services

  Scenario: Verify the create-tenant form renders its name, business type and currency fields
    Given I am a platform admin on the tenants page
    And I have opened the "New tenant" dialog
    Then the form shows the name, business type and base currency fields

  Scenario: Verify a valid submit creates the tenant with the entered name, currency and brand colours
    Given I am a platform admin on the tenants page
    And I have opened the "New tenant" dialog
    When I enter a name and a base currency and create the tenant
    Then the create action is called with the entered name, upper-cased currency and default brand colours

  Scenario: Verify an empty name blocks creating the tenant
    Given I am a platform admin on the tenants page
    And I have opened the "New tenant" dialog
    When I leave the name empty
    Then the Create button is disabled so no tenant is created

  Scenario: Verify a duplicate-name rejection surfaces in the dialog
    Given I am a platform admin on the tenants page
    And I have opened the "New tenant" dialog
    When I create a tenant whose name already exists
    Then the dialog shows a friendly duplicate-name error
