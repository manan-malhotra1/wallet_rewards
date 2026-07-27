Feature: Partner and merchant money movement
  As a partner integrating with the wallet
  I want to fund, withdraw, create customers, and let merchants cash customers in
  So that money moves safely, only once, and only within my own tenant

  Background:
    Given a tenant is configured on the platform
    And the partner holds a valid signing key for that tenant
    And a customer exists in that tenant

  Scenario: Verify a partner can top up a customer from their float
    Given the fund service is set up with pricing and limits
    When the partner sends a signed request to top up the customer
    Then the customer's wallet balance increases by that amount

  Scenario: Verify an unsigned fund request is rejected
    When the partner sends a fund request with no signature
    Then the request is rejected as unauthorised

  Scenario: Verify replaying a fund request tops up the wallet only once
    Given the fund service is set up with pricing and limits
    When the partner sends the same top-up request twice with one idempotency key
    Then the wallet is credited only once
    And both responses describe the same transaction

  Scenario: Verify a partner cannot fund a customer who is not in its own tenant
    When the partner tries to fund a customer that only exists in another tenant
    Then the request is rejected as not found

  Scenario: Verify a partner can withdraw from a customer's wallet
    Given the withdraw service is set up with pricing and limits
    And the customer's wallet is funded
    When the partner sends a signed request to withdraw an amount
    Then the customer's wallet balance decreases by that amount

  Scenario: Verify a partner can withdraw a customer's entire balance
    Given the withdraw service is set up with pricing and limits
    And the customer's wallet is funded
    When the partner sends a signed request to withdraw everything
    Then the full balance is withdrawn and the wallet is left empty

  Scenario: Verify a withdrawal for more than the balance is rejected
    Given the withdraw service is set up with pricing and limits
    And the customer's wallet holds less than the requested amount
    When the partner sends a signed withdrawal for more than the balance
    Then the request is rejected for insufficient funds

  Scenario: Verify a withdrawal with an invalid signature is rejected
    When the partner sends a withdrawal signed with the wrong secret
    Then the request is rejected as unauthorised

  Scenario: Verify a withdrawal cannot request both a fixed amount and the full balance
    When the partner sends a withdrawal asking for both a set amount and everything
    Then the request is rejected as invalid

  Scenario: Verify replaying a withdrawal takes the money only once
    Given the withdraw service is set up with pricing and limits
    And the customer's wallet is funded
    When the partner sends the same withdrawal twice with one idempotency key
    Then money leaves the wallet only once
    And both responses describe the same transaction

  Scenario: Verify a withdrawal above the configured limit is rejected
    Given a maximum withdrawal amount is configured
    When the partner sends a withdrawal above that maximum
    Then the request is rejected

  Scenario: Verify an idempotency key used for a fund cannot be reused for a withdrawal
    Given the partner has already funded a customer with an idempotency key
    When the partner reuses that key for a withdrawal
    Then the request is rejected as a conflict

  Scenario: Verify two simultaneous withdrawals cannot overdraw the wallet
    Given the withdraw service is set up with pricing and limits
    And the customer's wallet holds exactly one withdrawal's worth
    When two withdrawals for the full balance arrive at the same time
    Then only one succeeds and the other is refused for insufficient funds
    And the wallet never goes negative

  Scenario: Verify two simultaneous full withdrawals cannot drain the wallet twice
    Given the withdraw service is set up with pricing and limits
    And the customer's wallet is funded
    When two withdraw-everything requests arrive at the same time
    Then only one drains the wallet and the other is refused
    And the wallet is emptied exactly once

  Scenario: Verify two simultaneous top-ups cannot push a wallet past its balance ceiling
    Given a maximum wallet balance is configured
    When two top-ups that together exceed the ceiling arrive at the same time
    Then only one is accepted and the other is refused
    And the wallet never exceeds its ceiling

  Scenario: Verify a fund is refused when the service has no pricing or limit set up
    Given the fund service has no pricing or limit configured
    When the partner sends a signed fund request
    Then the request is refused and no money moves

  Scenario: Verify a fund is refused when a limit is not set up
    Given the fund service has pricing but no limit configured
    When the partner sends a signed fund request
    Then the request is refused and no money moves

  Scenario: Verify a fund goes through once pricing and limits are set up
    Given the fund service has both pricing and a limit configured
    When the partner sends a signed fund request
    Then the top-up succeeds

  Scenario: Verify a withdrawal is refused when the service has no pricing or limit set up
    Given the withdraw service has no pricing or limit configured
    When the partner sends a signed withdrawal
    Then the request is refused and the balance is untouched

  Scenario: Verify a withdrawal is refused when pricing is not set up
    Given the withdraw service has a limit but no pricing configured
    When the partner sends a signed withdrawal
    Then the request is refused and the balance is untouched

  Scenario: Verify a partner can create a customer in its own tenant
    When the partner sends a signed request to create a customer
    Then a customer is created in the partner's own tenant

  Scenario: Verify a partner-created customer is recorded in the audit trail
    When the partner creates a customer
    Then an audit entry records the creation against the partner's key

  Scenario: Verify retrying a customer creation does not record a second audit entry
    Given the partner has created a customer with an idempotency key
    When the partner retries with the same key
    Then no second audit entry is recorded

  Scenario: Verify an unsigned customer-creation request is rejected
    When the partner sends a customer-creation request with no signature
    Then the request is rejected as unauthorised

  Scenario: Verify a customer-creation request with an invalid signature is rejected
    When the partner sends a customer-creation request signed with the wrong secret
    Then the request is rejected as unauthorised

  Scenario: Verify a customer-creation request without an idempotency key is rejected
    When the partner sends a customer-creation request with no idempotency key
    Then the request is rejected as invalid

  Scenario: Verify a partner-created customer must have an email or phone
    When the partner creates a customer with neither an email nor a phone
    Then the request is rejected as invalid

  Scenario: Verify retrying a customer creation returns the same customer, not a second one
    Given the partner has created a customer with an idempotency key
    When the partner retries with the same key
    Then the original customer is returned and no second customer is created

  Scenario: Verify a newly created customer is recorded so a later retry can replay it
    When the partner creates a customer with an idempotency key
    Then the key-to-customer mapping is recorded for later replay

  Scenario: Verify creating a customer with an already-used contact detail is rejected as a conflict
    Given a customer already exists with a contact detail
    When the partner creates another customer with the same contact detail under a new key
    Then the request is rejected as a conflict and no new customer is created

  Scenario: Verify two simultaneous retries create a single customer
    When two requests with the same idempotency key race to create a customer
    Then only one customer is created and both requests return it

  Scenario: Verify the same idempotency key in two tenants creates two separate customers
    Given two partners in two different tenants
    When each creates a customer using the same idempotency key
    Then two independent customers are created, one per tenant

  Scenario: Verify a partner exceeding its request quota is throttled
    Given the partner has reached its request quota
    When the partner sends another request
    Then the request is throttled

  Scenario: Verify a partner cannot set privileged fields when creating a customer
    When the partner tries to create a customer with privileged fields set
    Then the customer is created as an ordinary unverified consumer and the privileged fields are ignored

  Scenario: Verify a merchant can cash a customer in from the merchant's own wallet
    Given a funded merchant with a merchant key
    And the cash-in service is set up with pricing and limits
    When the merchant cashes the customer in
    Then the merchant's wallet is debited and the customer's wallet is credited

  Scenario: Verify a cash-in fee is borne by the merchant and not the customer
    Given a funded merchant and a cash-in fee configured
    When the merchant cashes the customer in
    Then the merchant is charged the amount plus the fee
    And the customer receives only the amount

  Scenario: Verify a cash-in is refused when the service has no pricing or limit set up
    Given the cash-in service has no pricing or limit configured
    When the merchant tries to cash the customer in
    Then the request is refused and no money moves

  Scenario: Verify a cash-in is refused when a limit is not set up
    Given the cash-in service has pricing but no limit configured
    When the merchant tries to cash the customer in
    Then the request is refused and no money moves

  Scenario: Verify a cash-in is refused when pricing is not set up
    Given the cash-in service has a limit but no pricing configured
    When the merchant tries to cash the customer in
    Then the request is refused and no money moves

  Scenario: Verify a merchant with too little balance cannot cash a customer in
    Given the cash-in service is set up with pricing and limits
    And the merchant has too little balance
    When the merchant tries to cash the customer in
    Then the request is refused for insufficient funds and no money moves

  Scenario: Verify an ordinary partner key cannot perform a merchant cash-in
    Given the cash-in service is set up with pricing and limits
    When a key with no merchant binding attempts a cash-in
    Then the request is refused as not a merchant key

  Scenario: Verify an unsigned cash-in request is rejected
    When a cash-in request is sent with no signature
    Then the request is rejected as unauthorised

  Scenario: Verify a cash-in request with an invalid signature is rejected
    When a cash-in request is signed with the wrong secret
    Then the request is rejected as unauthorised

  Scenario: Verify a cash-in request without an idempotency key is rejected
    When a cash-in request is sent with no idempotency key
    Then the request is rejected as invalid

  Scenario: Verify a cash-in to an unknown customer is rejected
    Given the cash-in service is set up with pricing and limits
    When the merchant tries to cash in a customer that does not exist
    Then the request is rejected as not found

  Scenario: Verify replaying a cash-in credits the customer only once
    Given the cash-in service is set up with pricing and limits
    When the merchant sends the same cash-in twice with one idempotency key
    Then the customer is credited only once
    And both responses describe the same transaction

  Scenario: Verify a merchant cannot cash in a customer from another tenant
    Given the cash-in service is set up with pricing and limits
    When the merchant tries to cash in a customer that only exists in another tenant
    Then the request is rejected as not found
