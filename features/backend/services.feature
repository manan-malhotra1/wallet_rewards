Feature: Managing the service catalog
  As a platform administrator
  I want to manage the catalog of services offered to a tenant
  So that each tenant offers the right services and every change is accountable

  Background:
    Given I am a signed-in platform administrator
    And each tenant has its own catalog of services

  Scenario: Verify a signed-out user cannot list services
    Given I am not signed in
    When I ask for a tenant's service catalog
    Then the request is refused as unauthenticated

  Scenario: Verify the catalog lists both active and disabled services by default
    Given a tenant has one active service and one disabled service
    When I ask for the catalog without a status filter
    Then both the active and the disabled service are listed

  Scenario: Verify filtering the catalog by active status shows only active services
    Given a tenant has one active service and one disabled service
    When I ask for the catalog filtered to active services
    Then only the active service is listed

  Scenario: Verify one tenant cannot see another tenant's service catalog
    Given two tenants each have a service with the same code
    When I ask for one tenant's catalog
    Then only that tenant's service is listed

  Scenario: Verify an admin can add a new service to the catalog
    When I add a new service to a tenant's catalog
    Then the service is created and starts out active

  Scenario: Verify a service code cannot be reused within the same tenant
    Given a tenant already has a service with a certain code
    When I try to add another service with the same code
    Then the request is refused because the code is already in use

  Scenario: Verify a service code must follow the allowed format
    When I try to add a service whose code is not in the allowed format
    Then the request is rejected as invalid

  Scenario: Verify an admin can rename a service and change its status without changing its code
    Given a tenant has a service
    When I change the service's display name and status
    Then the display name and status are updated while the code stays the same

  Scenario: Verify editing a service that does not exist is reported as not found
    When I try to edit a service that does not exist
    Then the request is reported as not found

  Scenario: Verify an admin cannot change a service's code through an edit
    Given a tenant has a service
    When I try to change the service's code through an edit
    Then the request is rejected as invalid

  Scenario: Verify a deleted service no longer appears in the catalog
    Given a tenant has a service
    When I delete the service
    Then the service no longer appears in the catalog

  Scenario: Verify a deleted service code can be added again
    Given a tenant had a service that was deleted
    When I add a new service with the same code
    Then the new service is created

  Scenario: Verify adding a service is recorded in the audit trail
    When I add a new service
    Then the audit trail records the creation

  Scenario: Verify editing a service is recorded in the audit trail with the old and new values
    Given a tenant has a service
    When I change the service's status
    Then the audit trail records the change with the old and new status

  Scenario: Verify deleting a service is recorded in the audit trail
    Given a tenant has a service
    When I delete the service
    Then the audit trail records the deletion
