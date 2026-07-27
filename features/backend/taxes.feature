Feature: Tax rates
  As a platform administrator
  I want to view the tax rates configured on the platform
  So that I can confirm the taxes applied to customer charges are correct and properly scoped

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And my tenant has tax rates configured

  Scenario: Verify an admin can list the configured tax rates.
    When I open the tax rates page
    Then I see every tax rate configured for my tenant

  Scenario: Verify tax rates cannot be listed without signing in.
    Given I am not signed in
    When I request the tax rates
    Then I am refused with an unauthorized response

  Scenario: Verify only a platform admin can list tax rates.
    Given I am signed in without the platform administrator role
    When I request the tax rates
    Then I am refused with a forbidden response

  Scenario: Verify one tenant cannot see another tenant's tax rates.
    Given another tenant has its own tax rates configured
    When I list the tax rates
    Then I see only my own tenant's tax rates and none belonging to the other tenant
