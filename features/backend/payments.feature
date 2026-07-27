Feature: Sending money to another customer
  As a customer using the wallet
  I want to send money to another customer safely
  So that transfers are accurate, protected, and never move money twice

  Background:
    Given I am signed in as a customer with a funded wallet
    And the transfer service is configured with pricing and limits

  Scenario: Verify a transfer that earns no reward points shows none earned
    When I send money and no reward rule applies
    Then the response shows that no reward points were earned

  Scenario: Verify a transfer that earns reward points shows the points earned
    Given a transfer earns reward points
    When I view the transfer result
    Then the response shows the points I earned

  Scenario: Verify sending money moves it from the sender to the recipient
    When I send money to another customer
    Then my balance goes down and the recipient's balance goes up by that amount

  Scenario: Verify a customer cannot send more money than their wallet balance
    Given my wallet holds less than I want to send
    When I try to send that amount
    Then the transfer is refused and my balance is unchanged

  Scenario: Verify a customer cannot send money to themselves
    When I try to send money to my own number
    Then the transfer is refused

  Scenario: Verify sending money to an unknown recipient is refused
    When I try to send money to a number that belongs to nobody
    Then the transfer is refused

  Scenario: Verify a customer cannot send money in a currency they hold no wallet for
    When I try to send money in a currency I hold no wallet for
    Then the transfer is refused

  Scenario: Verify a customer cannot send money to a recipient belonging to another tenant
    Given the recipient's number exists only under another tenant
    When I try to send money to that number
    Then the transfer is refused

  Scenario: Verify sending a zero or negative amount is refused
    When I try to send a zero or negative amount
    Then the transfer is refused

  Scenario: Verify a transfer must carry an idempotency key
    When I try to send money without a request key
    Then the transfer is refused

  Scenario: Verify an unauthenticated customer cannot send money
    Given I am not signed in
    When I try to send money
    Then the transfer is refused

  Scenario: Verify sending the same transfer twice moves money only once
    When I send the same transfer request twice
    Then the money moves only once and both responses match

  Scenario: Verify two simultaneous transfers cannot spend the same balance twice
    Given my wallet holds only enough for one of two transfers
    When both transfers are sent at the same time
    Then only one succeeds and the other is refused as insufficient funds

  Scenario: Verify simultaneous incoming transfers cannot push a recipient past their maximum balance
    Given two senders each transfer to the same recipient at once
    And together the transfers would exceed the recipient's maximum balance
    When both transfers are sent at the same time
    Then only one lands and the recipient never exceeds their maximum balance

  Scenario: Verify two customers can send to each other at the same time without the transfers stalling
    Given two customers each send money to the other at the same time
    When both transfers run
    Then both complete and each balance reflects both transfers

  Scenario: Verify a transfer is refused when the service has no pricing or limit set up
    Given the transfer service has no pricing or limit set up
    When I try to send money
    Then the transfer is refused

  Scenario: Verify a transfer completes when pricing and limits are configured
    Given the transfer service has pricing and limits set up
    When I send money
    Then the transfer completes

  Scenario: Verify a transfer is refused when no fee is configured for its amount
    Given no fee is configured for the amount I want to send
    When I try to send that amount
    Then the transfer is refused

  Scenario: Verify a transfer is refused and no money moves when the service is unconfigured
    Given the transfer service is unconfigured
    When I try to send money
    Then the transfer is refused and no money moves

  Scenario: Verify a transfer is refused when limits are missing even if pricing exists
    Given pricing exists but no limit is configured for transfers
    When I try to send money
    Then the transfer is refused and no money moves
