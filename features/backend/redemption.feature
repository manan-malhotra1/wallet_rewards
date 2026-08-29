Feature: Redeeming points into my own wallet
  As a rewards customer
  I want to convert my points into real money in my wallet at the published rate
  So that my loyalty points have immediate, spendable value

  Background:
    Given a business is running on the rewards platform
    And a points-to-money rate is published for that business
    And I am a signed-in customer with a points balance

  # --- Converting points (customer) ---

  Scenario: Verify a customer converts points into wallet money at the published rate
    Given I have points available
    When I redeem points into my wallet
    Then my points are deducted and my wallet is credited at the published rate
    And the receipt links the points deduction to the money credited

  Scenario: Verify a redemption into a currency with no published rate is refused
    Given no rate is published for the currency I ask for
    When I try to redeem into that currency
    Then the redemption is refused because no rate is published

  Scenario: Verify a withdrawn rate does not permit redemption
    Given the rate for my currency has been withdrawn
    When I try to redeem into that currency
    Then the redemption is refused because no rate is published

  Scenario: Verify a redemption is refused when its pricing or limits have not been set up
    Given redemption pricing or limits are missing for my business
    When I try to redeem points
    Then the redemption is refused because the service is not configured
    And none of my points are deducted

  Scenario: Verify a customer cannot redeem more points than they have
    Given I have fewer points than I ask to redeem
    When I try to redeem them
    Then the redemption is refused for insufficient points

  Scenario: Verify my points are returned when the payout cannot be funded
    Given the business's payout wallet does not hold enough money
    When I redeem points
    Then the payout is refused
    And my points are returned to me

  Scenario: Verify retrying the same redemption request does not spend points twice
    Given I have points available
    When I submit the same redemption request twice with the same request key
    Then both attempts return the same receipt
    And only one lot of points is deducted

  # --- Anti-drain caps ---

  Scenario: Verify a single redemption cannot exceed the published points cap
    Given the published rate caps how many points one redemption may burn
    When I try to redeem more than that cap
    Then the redemption is refused for exceeding the per-redemption cap

  Scenario: Verify a single redemption cannot exceed the published share of my balance
    Given the published rate caps a redemption at a share of my balance
    When I try to redeem more than that share
    Then the redemption is refused for exceeding the per-redemption cap

  # --- Published rates ---

  Scenario: Verify a customer is only offered currencies with a live rate
    Given rates are published for some currencies and withdrawn for others
    When I ask which currencies I can redeem into
    Then only the currencies with a live rate are offered

  Scenario: Verify redeeming requires being signed in
    When a redemption is attempted without a signed-in customer
    Then the request is rejected as unauthorised
