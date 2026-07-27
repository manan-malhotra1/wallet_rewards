Feature: Agent cash-in
  As an agent serving customers
  I want to take cash and top up a customer's wallet from my float
  So that customers get funded, I earn my commission, and money never moves twice

  Background:
    Given I am signed in as an agent with a funded float
    And the cash-in service is configured with pricing and limits

  Scenario: Verify an agent cashing in a customer moves money and commission to the right places
    When I cash in a customer for an amount
    Then the customer is credited, my commission is paid, and fees and tax settle correctly

  Scenario: Verify an unauthenticated agent cannot cash in a customer
    Given I am not signed in
    When I try to cash in a customer
    Then the request is refused

  Scenario: Verify a user without cash-in permission cannot cash in a customer
    Given I am signed in as a user without cash-in permission
    When I try to cash in a customer
    Then the request is refused

  Scenario: Verify a cash-in must carry an idempotency key
    When I try to cash in a customer without a request key
    Then the request is refused

  Scenario: Verify cashing in an unknown customer is refused
    When I try to cash in a customer whose number belongs to nobody
    Then the request is reported as not found

  Scenario: Verify sending the same cash-in twice moves money only once
    When I send the same cash-in request twice
    Then the money moves only once and both responses match

  Scenario: Verify an agent cannot cash in more than their float holds
    When I try to cash in more than my float holds
    Then the request is refused as insufficient funds

  Scenario: Verify an agent cannot cash in a customer belonging to another tenant
    Given the customer's number exists only under another tenant
    When I try to cash in that customer
    Then the request is reported as not found

  Scenario: Verify a cash-in is refused and no money moves when the service is unconfigured
    Given the cash-in service is unconfigured
    When I try to cash in a customer
    Then the request is refused and no money moves

  Scenario: Verify a cash-in is refused when limits are missing even if pricing exists
    Given cash-in pricing exists but no limit is configured
    When I try to cash in a customer
    Then the request is refused and no money moves

  Scenario: Verify a cash-in completes when pricing and limits are configured
    Given the cash-in service has pricing and limits set up
    When I cash in a customer
    Then the cash-in completes
