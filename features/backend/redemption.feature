Feature: Redeeming points for rewards
  As a rewards customer
  I want to exchange my points for airtime, vouchers and other rewards through a provider
  So that my loyalty points have real, tangible value

  Background:
    Given a business is running on the rewards platform
    And a redemption provider has been onboarded for that business
    And I am a signed-in customer with a points balance

  # --- Provider setup (admin) ---

  Scenario: Verify registering a redemption provider sets up its rewards wallet automatically
    Given I am an administrator onboarding a new reward partner
    When I register the provider for my business
    Then the provider is created and marked active
    And a matching points wallet is set up for the provider automatically

  Scenario: Verify a provider cannot be registered under a business that does not exist
    Given I am an administrator
    When I try to register a provider for a business that does not exist
    Then the request is rejected as not found

  # --- Starting a redemption (customer) ---

  Scenario: Verify a customer can start redeeming points and the spent points are held aside
    Given I have 150 points available
    When I start a redemption of 100 points with the provider
    Then the redemption is created and waiting on the provider
    And 100 of my points are held aside so my available balance drops to 50

  Scenario: Verify a customer cannot redeem more points than they have
    Given I have only 50 points available
    When I try to redeem 200 points
    Then the redemption is refused for insufficient points
    And none of my points are held aside

  Scenario: Verify a customer cannot redeem through a provider that does not exist
    Given I have points available
    When I try to redeem through a provider that does not exist
    Then the redemption is refused as not found

  Scenario: Verify retrying the same redemption request does not spend points twice
    Given I have 100 points available
    When I submit the same redemption request twice with the same request key
    Then both attempts return the same redemption
    And only one lot of points is held aside

  Scenario: Verify two redemptions submitted at once cannot spend the same points twice
    Given I have exactly 100 points available
    When I submit two full-balance redemptions at the same time
    Then only one redemption succeeds
    And the other is refused

  Scenario: Verify a customer cannot redeem through another business's provider
    Given a provider belongs to a different business
    When I try to redeem through that provider
    Then the redemption is refused as not found with no hint the provider exists

  Scenario: Verify a redemption is refused when the service has not been set up
    Given redemption has not been configured for my business
    When I try to redeem 100 points
    Then the redemption is refused because the service is not configured
    And none of my points are held aside

  Scenario: Verify a redemption is refused when its pricing has not been set up
    Given redemption limits are set up but its pricing is missing
    When I try to redeem 100 points
    Then the redemption is refused because the service is not configured
    And none of my points are held aside

  # --- Completing or failing a redemption (admin) ---

  Scenario: Verify confirming a redemption permanently deducts the customer's points
    Given I have a pending redemption of 80 points from a balance of 200
    When an administrator confirms the redemption as delivered
    Then the redemption is marked completed
    And my points balance permanently drops to 120

  Scenario: Verify a failed redemption returns the held points to the customer
    Given I have a pending redemption of 75 points from a balance of 100
    When an administrator marks the redemption as failed
    Then the redemption is marked failed
    And my held points are returned so my balance is 100 again

  Scenario: Verify a confirmed redemption shows which customer it belongs to
    Given I have a pending redemption
    When an administrator confirms it
    Then the confirmation shows which customer the redemption belongs to

  Scenario: Verify a failed redemption shows which customer it belongs to
    Given I have a pending redemption
    When an administrator marks it as failed
    Then the response shows which customer the redemption belongs to

  Scenario: Verify a redemption cannot be confirmed twice
    Given a redemption has already been confirmed
    When an administrator tries to confirm it again
    Then the second confirmation is refused because it is no longer pending

  Scenario: Verify one business cannot confirm another business's redemption
    Given a redemption belongs to my business
    When an administrator from a different business tries to confirm it
    Then the request is refused as not found

  Scenario: Verify one business cannot fail another business's redemption
    Given a redemption belongs to my business
    When an administrator from a different business tries to mark it failed
    Then the request is refused as not found

  Scenario: Verify a completed redemption can no longer be marked as failed
    Given a redemption has already been completed
    When an administrator tries to mark it as failed
    Then the request is refused because it is no longer pending

  # --- Provider callbacks ---

  Scenario: Verify a provider confirming delivery completes the customer's redemption
    Given I have a pending redemption of 80 points from a balance of 200
    When the provider sends a trusted callback confirming delivery
    Then the redemption is marked completed
    And my points balance permanently drops to 120
    And the confirmation is recorded in the audit trail

  Scenario: Verify a provider reporting failure returns the held points to the customer
    Given I have a pending redemption of 60 points from a balance of 100
    When the provider sends a trusted callback reporting failure
    Then the redemption is marked failed
    And my held points are returned so my balance is 100 again

  Scenario: Verify a redemption callback with an altered message is rejected
    Given I have a pending redemption
    When a callback arrives whose contents were changed after it was signed
    Then the callback is rejected as unauthorised
    And the redemption is left unchanged

  Scenario: Verify an out-of-date redemption callback is rejected
    Given I have a pending redemption
    When a callback arrives that was signed too long ago
    Then the callback is rejected as unauthorised
    And the redemption is left unchanged

  Scenario: Verify a redemption callback without a signature is rejected
    Given I have a pending redemption
    When a callback arrives with no signature at all
    Then the callback is rejected as invalid

  Scenario: Verify a callback for a provider with no signing secret is rejected
    Given I have a pending redemption from a provider that has no signing secret
    When a signed callback arrives for that redemption
    Then the callback is rejected as unauthorised

  Scenario: Verify a repeated redemption callback cannot change an already-finished redemption
    Given a redemption has already been completed by a valid callback
    When the same valid callback is sent again
    Then the repeat is refused because the redemption is no longer pending

  Scenario: Verify a provider's signing secret is stored encrypted rather than in plain text
    Given a provider was registered with a signing secret
    When I inspect how the secret is stored
    Then the stored secret is encrypted and never the plain text value
    And signed callbacks still verify correctly against it

  Scenario: Verify a callback for a redemption that does not exist is rejected
    When a signed callback arrives for a redemption that does not exist
    Then the callback is rejected as not found
