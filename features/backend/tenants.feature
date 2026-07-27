Feature: Managing tenant identity cards
  As a platform administrator
  I want to view and edit each tenant's identity card
  So that tenant details stay accurate and every change is accountable

  Background:
    Given I am a signed-in platform administrator
    And my platform hosts one or more tenants

  Scenario: Verify a signed-out user cannot list tenants
    Given I am not signed in
    When I ask for the list of tenants
    Then the request is refused as unauthenticated

  Scenario: Verify an admin can see the tenant in the list with its business type
    When I ask for the list of tenants
    Then the list includes my tenant along with its business type

  Scenario: Verify an admin can open a single tenant's identity card
    When I open a tenant's identity card
    Then I see that tenant's name and business type

  Scenario: Verify opening a tenant that does not exist is reported as not found
    When I open the identity card of a tenant that does not exist
    Then the request is reported as not found

  Scenario: Verify an admin can rename a tenant
    When I change a tenant's name
    Then the tenant is renamed and the new name is returned

  Scenario: Verify an admin can change a tenant's business type
    When I change a tenant's business type to rewards
    Then the tenant's business type is updated

  Scenario: Verify a tenant cannot be set to an unsupported business type
    When I try to set a tenant's business type to an unsupported value
    Then the request is rejected as invalid

  Scenario: Verify an admin cannot change protected tenant fields through an edit
    When I try to change a protected tenant field through an edit
    Then the request is rejected as invalid

  Scenario: Verify a tenant cannot be renamed to a name another tenant already uses
    Given another tenant already uses a certain name
    When I try to rename my tenant to that same name
    Then the request is refused because the name is already in use

  Scenario: Verify editing a tenant that does not exist is reported as not found
    When I try to edit a tenant that does not exist
    Then the request is reported as not found

  Scenario: Verify a signed-out user cannot edit a tenant
    Given I am not signed in
    When I try to edit a tenant
    Then the request is refused as unauthenticated

  Scenario: Verify editing a tenant is recorded in the audit trail with the old and new values
    When I rename a tenant
    Then the audit trail records the change with the old and new name
