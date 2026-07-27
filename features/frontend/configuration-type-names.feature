Feature: Configuration type names
  As an administrator using the admin portal
  I want every configuration type to appear under a readable name
  So that a raw internal code never leaks onto a maker-checker surface

  Background:
    Given I am an administrator using the admin portal

  Scenario: Verify every configuration type shows a readable name, not a raw code (pricing)
    Given a configuration of type "pricing"
    When I view it on a maker-checker surface
    Then it is shown with a friendly name, not the raw code "pricing"
    And that name contains no underscores

  Scenario: Verify every configuration type shows a readable name, not a raw code (limit)
    Given a configuration of type "limit"
    When I view it on a maker-checker surface
    Then it is shown with a friendly name, not the raw code "limit"
    And that name contains no underscores

  Scenario: Verify every configuration type shows a readable name, not a raw code (wallet_limit)
    Given a configuration of type "wallet_limit"
    When I view it on a maker-checker surface
    Then it is shown with a friendly name, not the raw code "wallet_limit"
    And that name contains no underscores

  Scenario: Verify every configuration type shows a readable name, not a raw code (commission)
    Given a configuration of type "commission"
    When I view it on a maker-checker surface
    Then it is shown with a friendly name, not the raw code "commission"
    And that name contains no underscores

  Scenario: Verify every configuration type shows a readable name, not a raw code (tax)
    Given a configuration of type "tax"
    When I view it on a maker-checker surface
    Then it is shown with a friendly name, not the raw code "tax"
    And that name contains no underscores

  Scenario: Verify every configuration type shows a readable name, not a raw code (step_up)
    Given a configuration of type "step_up"
    When I view it on a maker-checker surface
    Then it is shown with a friendly name, not the raw code "step_up"
    And that name contains no underscores

  Scenario: Verify a step-up policy shows as 'Step-up PIN policy'
    Given a configuration of type "step_up"
    When I view its type name
    Then it reads "Step-up PIN policy"

  Scenario: Verify admins see 'Service charge' instead of a raw pricing code
    Given a configuration of type "pricing"
    When I view its type name
    Then it reads "Service charge" rather than the raw pricing code
