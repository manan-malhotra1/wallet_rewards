Feature: Customer cash-out to an agent
  As a customer using the wallet
  I want to cash out my wallet money through an agent
  So that I can collect cash safely while the agent earns their commission

  Background:
    Given I am signed in as a customer with a funded wallet
    And the cash-out service is configured with pricing and limits

  Scenario: Verify a customer cashing out to an agent moves money and commission to the right places
    When I cash out to an agent for an amount
    Then I am debited, the agent is credited and paid commission, and fees and tax settle correctly

  Scenario: Verify an unauthenticated customer cannot cash out
    Given I am not signed in
    When I try to cash out
    Then the request is refused

  Scenario: Verify a user without cash-out permission cannot cash out
    Given I am signed in as a user without cash-out permission
    When I try to cash out
    Then the request is refused

  Scenario: Verify a cash-out must carry an idempotency key
    When I try to cash out without a request key
    Then the request is refused

  Scenario: Verify cashing out to an unknown agent is refused
    When I try to cash out to a number that belongs to nobody
    Then the request is reported as not found

  Scenario: Verify a customer can only cash out to an agent, not another customer
    When I try to cash out to another customer instead of an agent
    Then the request is refused

  Scenario: Verify a customer cannot cash out to themselves
    When I try to cash out to my own number
    Then the request is refused

  Scenario: Verify sending the same cash-out twice moves money only once
    When I send the same cash-out request twice
    Then the money moves only once and both responses match

  Scenario: Verify a customer cannot cash out more than their wallet holds
    When I try to cash out more than my wallet holds
    Then the request is refused as insufficient funds

  Scenario: Verify a customer cannot cash out to an agent belonging to another tenant
    Given the agent's number exists only under another tenant
    When I try to cash out to that agent
    Then the request is reported as not found

  Scenario: Verify a large cash-out asks the customer for their PIN
    Given a PIN is required for cash-outs over a threshold
    When I try to cash out an amount over that threshold without my PIN
    Then I am asked to confirm with my PIN

  Scenario: Verify a large cash-out completes when the customer enters the correct PIN
    Given a PIN is required for cash-outs over a threshold
    When I cash out an amount over that threshold with my correct PIN
    Then the cash-out completes

  Scenario: Verify a cash-out is refused and no money moves when the service is unconfigured
    Given the cash-out service is unconfigured
    When I try to cash out
    Then the request is refused and no money moves

  Scenario: Verify a cash-out is refused when limits are missing even if pricing exists
    Given cash-out pricing exists but no limit is configured
    When I try to cash out
    Then the request is refused and no money moves
