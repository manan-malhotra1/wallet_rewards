Feature: Merchant profiles
  As an operator
  I want merchant profiles kept consistent and tenant-scoped
  So that each service has a single active merchant within its tenant

  Background:
    Given a tenant is configured on the platform
    And a merchant user exists in that tenant

  Scenario: Verify a new merchant profile is saved with sensible defaults
    When a merchant profile is created without specifying mode or status
    Then it is saved with its default mode, active status, and empty provider settings

  Scenario: Verify a merchant profile in one tenant is invisible to another tenant
    Given a merchant profile exists in one tenant
    When another tenant lists its merchant profiles
    Then that profile does not appear

  Scenario: Verify only one active merchant can serve a given service in a tenant
    Given an active merchant already serves a service in the tenant
    When a second active merchant is added for the same service
    Then it is rejected
