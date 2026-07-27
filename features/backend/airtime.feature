Feature: Airtime recharge
  As a customer
  I want to buy airtime through the wallet
  So that my phone is topped up and I am only charged when it succeeds

  Background:
    Given a tenant is configured on the platform
    And an active airtime merchant is set up for the tenant
    And the airtime service is set up with pricing and limits
    And the customer's wallet is funded

  Scenario: Verify a provider success callback completes a pending airtime recharge
    Given a recharge is left pending awaiting the provider
    When a signed success callback arrives from the provider
    Then the recharge is marked completed
    And the reserved money settles to the merchant

  Scenario: Verify a provider failure callback refunds the customer
    Given a recharge is left pending awaiting the provider
    When a signed failure callback arrives from the provider
    Then the recharge is reversed
    And the customer is refunded in full

  Scenario: Verify an airtime callback with an invalid signature is rejected
    Given a recharge is left pending awaiting the provider
    When a callback arrives signed with the wrong secret
    Then the callback is rejected as unauthorised

  Scenario: Verify an airtime callback without a signature is rejected
    Given a recharge is left pending awaiting the provider
    When a callback arrives with no signature
    Then the callback is rejected as invalid

  Scenario: Verify a callback on an already-settled recharge is rejected
    Given a recharge has already settled
    When a later callback arrives for it
    Then the callback is rejected as already settled

  Scenario: Verify a callback for an unknown recharge is rejected
    When a callback arrives for a recharge that does not exist
    Then the callback is rejected as not found

  Scenario: Verify an operator can force a stuck pending recharge to complete
    Given a recharge is stuck pending with no provider callback
    When an operator resolves it as completed
    Then the recharge is marked completed

  Scenario: Verify a customer cannot force-resolve a recharge
    Given a recharge is stuck pending
    When a customer tries to resolve it
    Then the request is refused

  Scenario: Verify an operator cannot resolve an already-settled recharge
    Given a recharge has already settled
    When an operator tries to resolve it again
    Then the request is rejected as already settled

  Scenario: Verify a normal airtime top-up succeeds with a provider reference
    When a top-up is sent for an ordinary number
    Then it succeeds and returns a provider reference

  Scenario: Verify a failing airtime top-up returns a failure with no reference
    When a top-up is sent for a number the provider rejects
    Then it fails and returns no provider reference

  Scenario: Verify an airtime top-up can come back as still pending
    When a top-up is sent for a number the provider holds
    Then it comes back as still pending

  Scenario: Verify a forced outcome overrides the default airtime result
    Given the provider is told to force a specific outcome
    When a top-up is sent that would normally succeed
    Then the forced outcome is returned instead

  Scenario: Verify simulator mode uses the simulated airtime provider
    When the provider is selected in simulator mode
    Then the simulated airtime provider is used

  Scenario: Verify live airtime mode is refused until a real provider is wired in
    When the provider is selected in live mode
    Then the request is refused because no real provider is wired in

  Scenario: Verify a successful airtime recharge debits the customer and credits the merchant
    When the customer recharges and the provider succeeds
    Then the recharge completes
    And the customer is debited and the merchant is credited

  Scenario: Verify a failed airtime recharge is reversed and the customer is refunded
    When the customer recharges and the provider fails
    Then the recharge is reversed
    And the customer is refunded in full

  Scenario: Verify an airtime recharge awaiting the provider is left pending
    When the customer recharges and the provider holds the request
    Then the recharge is left pending
    And looking it up still shows it pending

  Scenario: Verify an airtime recharge requires the customer to be signed in
    When a recharge is attempted without signing in
    Then the request is refused as unauthorised

  Scenario: Verify a customer without airtime permission cannot recharge
    Given a customer whose role does not permit airtime
    When that customer attempts a recharge
    Then the request is refused

  Scenario: Verify an airtime recharge without an idempotency key is rejected
    When a recharge is sent with no idempotency key
    Then the request is rejected as invalid

  Scenario: Verify an airtime recharge is refused when no airtime merchant is set up
    Given no active airtime merchant is set up for the tenant
    When the customer attempts a recharge
    Then the request is refused

  Scenario: Verify a customer with too little balance cannot buy airtime
    Given the customer's wallet is unfunded
    When the customer attempts a recharge
    Then the request is refused for insufficient funds

  Scenario: Verify replaying an airtime recharge charges the customer only once
    When the customer sends the same recharge twice with one idempotency key
    Then the same recharge is returned both times
    And the customer is charged only once

  Scenario: Verify a recharge cannot be viewed from another tenant
    Given a recharge created in the tenant
    When someone in another tenant tries to view it
    Then it is not found

  Scenario: Verify looking up an unknown recharge is rejected
    When a customer looks up a recharge that does not exist
    Then it is not found

  Scenario: Verify a customer cannot view another customer's recharge
    Given a recharge created by one customer
    When another customer in the same tenant tries to view it
    Then it is not found

  Scenario: Verify an airtime recharge is refused when the service has no pricing or limit set up
    Given the airtime service has no pricing or limit configured
    When the customer attempts a recharge
    Then the request is refused and no money moves

  Scenario: Verify an airtime recharge is refused when a limit is not set up
    Given the airtime service has pricing but no limit configured
    When the customer attempts a recharge
    Then the request is refused and no money moves

  Scenario: Verify an airtime recharge goes through once pricing and limits are set up
    Given the airtime service has both pricing and a limit configured
    When the customer recharges
    Then the recharge completes

  Scenario: Verify a new airtime recharge is saved and starts as pending
    When a recharge record is created
    Then it is saved and starts as pending

  Scenario: Verify two recharges with the same idempotency key in a tenant are rejected
    Given a recharge already exists with an idempotency key
    When another recharge with the same key is saved in that tenant
    Then it is rejected

  Scenario: Verify a recharge in one tenant is invisible to another tenant
    Given a recharge exists in one tenant
    When another tenant lists its recharges
    Then that recharge does not appear
