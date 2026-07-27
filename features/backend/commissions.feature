Feature: Operator commissions
  As a platform administrator
  I want to view the operator commission rates and see them applied at the right tiers
  So that partners are paid the agreed commission and rates stay scoped to my tenant

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And my tenant has operator commission rates configured

  Scenario: Verify the correct commission tier applies right at a tier boundary amount.
    Given commission is configured in amount tiers
    When a transaction amount lands exactly on a tier's upper boundary
    Then the commission from that tier is applied

  Scenario: Verify an admin can list the configured commission rates.
    When I open the commission rates page
    Then I see every commission rate configured for my tenant

  Scenario: Verify commission rates cannot be listed without signing in.
    Given I am not signed in
    When I request the commission rates
    Then I am refused with an unauthorized response

  Scenario: Verify only a platform admin can list commission rates.
    Given I am signed in without the platform administrator role
    When I request the commission rates
    Then I am refused with a forbidden response

  Scenario: Verify one tenant cannot see another tenant's commission rates.
    Given another tenant has its own commission rates configured
    When I list the commission rates
    Then I see only my own tenant's commission rates and none belonging to the other tenant
