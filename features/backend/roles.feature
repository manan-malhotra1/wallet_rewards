Feature: Roles and permissions
  As a platform administrator
  I want to manage roles and the permissions that govern who may move money
  So that only authorised customers can transact and every change is accountable

  Background:
    Given I am a signed-in platform administrator
    And my platform hosts one or more tenants

  # ---------------------------------------------------------------------------
  # Permission gate on money movement
  # ---------------------------------------------------------------------------

  Scenario: Verify a customer with no role assigned cannot send money.
    Given a funded customer who has no role assigned
    When that customer tries to send money to someone
    Then the transfer is refused as not authorised

  Scenario: Verify a customer whose role does not allow transfers is blocked.
    Given a funded customer whose role does not permit transfers
    When that customer tries to send money to someone
    Then the transfer is refused as not authorised

  Scenario: Verify a customer whose role has been deactivated cannot transfer.
    Given a funded customer whose role has been deactivated
    When that customer tries to send money to someone
    Then the transfer is refused as not authorised

  Scenario: Verify a customer can transfer when any one of their roles allows it.
    Given a funded customer holding several roles, one of which permits transfers
    When that customer sends money to someone
    Then the transfer is accepted

  Scenario: Verify a customer without redemption permission cannot redeem points.
    Given a customer with points but whose role does not permit redemption
    When that customer tries to redeem points
    Then the redemption is refused as not authorised before any points are touched

  # ---------------------------------------------------------------------------
  # Role administration
  # ---------------------------------------------------------------------------

  Scenario: Verify an admin can create a role for a tenant.
    When I create a role for a tenant
    Then the role is created and returned as active

  Scenario: Verify an admin cannot create two roles with the same name in a tenant.
    Given a role with a certain name already exists in a tenant
    When I try to create another role with that same name in the tenant
    Then the request is refused because the role already exists

  Scenario: Verify an admin cannot create a role for a tenant that does not exist.
    When I try to create a role for a tenant that does not exist
    Then the request is reported as not found

  Scenario: Verify an admin only sees the roles belonging to their own tenant.
    Given roles exist in more than one tenant
    When I list the roles for one tenant
    Then I see only that tenant's roles

  Scenario: Verify an admin can deactivate a role.
    Given a role exists in a tenant
    When I set that role to inactive
    Then the role is marked inactive

  Scenario: Verify an admin can grant a permission and then change it in place.
    Given a role exists in a tenant
    When I grant a permission on the role and then change it
    Then the role has a single permission reflecting the latest change

  Scenario: Verify an admin can remove a permission from a role.
    Given a role that has a permission granted
    When I remove that permission from the role
    Then the role has no permissions left

  Scenario: Verify an admin can assign a role to a user.
    Given a role exists in a tenant
    When I assign that role to a user
    Then the user's role list includes that role

  Scenario: Verify assigning a role a user already has does not create a duplicate.
    Given a user who already holds a role
    When I assign that same role to the user again
    Then the same assignment is returned and no duplicate is created

  Scenario: Verify an admin can remove a role from a user.
    Given a user who holds a role
    When I remove that role from the user
    Then the user's role list no longer includes it

  Scenario: Verify an admin cannot assign a role to a user in another tenant.
    Given a role that belongs to another tenant
    When I try to assign it to a user under that other tenant's scope
    Then the request is reported as user not found

  Scenario: Verify a non-admin cannot manage roles.
    Given I am signed in without administrator rights
    When I try to create a role
    Then the request is refused for insufficient permissions

  # ---------------------------------------------------------------------------
  # Audit trail
  # ---------------------------------------------------------------------------

  Scenario: Verify creating a role is recorded in the audit trail.
    When I create a role
    Then the audit trail records who created it and its new state

  Scenario: Verify editing a role records both its old and new state.
    Given a role exists in a tenant
    When I change the role's status
    Then the audit trail records both the old and new status

  Scenario: Verify granting a permission to a role is recorded in the audit trail.
    Given a role exists in a tenant
    When I grant a permission on the role
    Then the audit trail records the grant

  Scenario: Verify revoking a permission from a role is recorded in the audit trail.
    Given a role that has a permission granted
    When I revoke that permission
    Then the audit trail records the revoke with the previous state

  Scenario: Verify assigning a role to a user is recorded in the audit trail.
    Given a role exists in a tenant
    When I assign the role to a user
    Then the audit trail records the assignment

  Scenario: Verify re-assigning a role a user already has adds no duplicate audit record.
    Given a user who already holds a role
    When I assign that same role again
    Then the audit trail still holds a single assignment record

  Scenario: Verify removing a role from a user is recorded in the audit trail.
    Given a user who holds a role
    When I remove that role from the user
    Then the audit trail records the removal with the previous state
