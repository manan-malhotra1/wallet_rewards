Feature: Configuration identity rules
  As an administrator managing pricing, commissions, limits and policies
  I want configurations that apply to the same situation to be treated as one
  So that I never create conflicting or duplicate rules for the same case.

  Background:
    Given I am signed in to the admin portal as a platform administrator

  Scenario: Verify a commission cannot be duplicated for the same service, currency and customer type
    Given a commission is already configured for a service, currency and customer type
    When I add another commission for that same service, currency and customer type
    Then it is treated as the same configuration rather than a second, conflicting one

  Scenario: Verify two pricing configs count as the same only when service, account type, currency and customer type all match
    Given a price is configured for a service, account type, currency and customer type
    When I add a price that differs in any one of those four
    Then it is kept as a separate price
    And only a price matching all four is treated as the same configuration

  Scenario: Verify a tiered pricing config is scoped by its first tier
    Given a price is set up as several amount tiers
    When the system decides which situation the price applies to
    Then it reads the service and customer from the first tier, so all tiers stay together

  Scenario: Verify a step-up policy cannot be duplicated for the same service and currency
    Given a PIN step-up policy exists for a service and currency
    When I add another step-up policy for that same service and currency
    Then it is treated as the same policy rather than a duplicate

  Scenario: Verify step-up policies for different services are kept as separate configs
    Given a PIN step-up policy exists for one service
    When I add a step-up policy for a different service in the same currency
    Then both are kept as separate policies, each applying to its own service

  Scenario: Verify a tax configuration cannot be duplicated for the same currency
    Given a tax is already configured for a currency
    When I add another tax for that same currency
    Then it is treated as the same configuration rather than a duplicate

  Scenario: Verify a wallet limit is scoped by currency and customer type, defaulting to all customers
    Given a wallet limit is configured for a currency
    When no customer type is specified on that limit
    Then it applies to all customer types in that currency by default
