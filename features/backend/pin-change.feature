Feature: Changing a customer PIN
  As a signed-in customer
  I want to change my own PIN safely
  So that I stay in control of my wallet and am charged fairly and predictably

  Background:
    Given I am a customer signed in on my device
    And my current PIN is set
    And changing a PIN is only allowed when its pricing and limits are configured

  Scenario: Verify a customer can change their PIN and is charged the fee
    Given a fee applies to changing my PIN and my wallet can cover it
    When I change my PIN with the correct current PIN
    Then my new PIN works, my old PIN stops working, and the fee is taken from my wallet

  Scenario: Verify a PIN change is audited without recording the PIN
    Given a fee applies to changing my PIN
    When I change my PIN
    Then the change is recorded in the audit trail without ever storing my PIN

  Scenario: Verify a free PIN change moves no money
    Given changing my PIN is free
    When I change my PIN
    Then my PIN is updated and no money moves

  Scenario: Verify repeating a free PIN change request changes the PIN only once
    Given changing my PIN is free
    When I send the same free PIN change request twice
    Then my PIN changes only once and both responses match

  Scenario: Verify repeating a charged PIN change request charges only once
    Given a fee applies to changing my PIN
    When I send the same charged PIN change request twice
    Then my PIN changes only once and I am charged only once

  Scenario: Verify a PIN change is refused when its pricing is not configured
    Given the pricing for changing a PIN is not configured
    When I try to change my PIN
    Then the request is refused and my PIN is unchanged

  Scenario: Verify a PIN change is refused when its limits are not configured
    Given the limits for changing a PIN are not configured
    When I try to change my PIN
    Then the request is refused and my PIN is unchanged

  Scenario: Verify a customer cannot change their PIN with the wrong current PIN
    Given I enter the wrong current PIN
    When I try to change my PIN
    Then the request is refused and my PIN is unchanged

  Scenario: Verify repeated wrong current PIN attempts lock the account
    Given I keep entering the wrong current PIN
    When I reach the allowed number of failed attempts
    Then my account is locked and even the correct PIN is refused for now

  Scenario: Verify changing a PIN requires the customer to be signed in
    Given I am not signed in
    When I try to change a PIN
    Then the request is refused

  Scenario: Verify a new PIN that is not a valid format is rejected
    Given I choose a new PIN that is not in a valid format
    When I try to change my PIN
    Then the request is rejected

  Scenario: Verify a customer cannot reuse their current PIN as the new one
    Given I choose a new PIN that is the same as my current one
    When I try to change my PIN
    Then the request is rejected

  Scenario: Verify a PIN change is refused when the wallet cannot cover the fee
    Given a fee applies but my wallet is empty
    When I try to change my PIN
    Then the request is refused and my PIN is unchanged

  Scenario: Verify a reused key changes PINs independently across businesses
    Given two customers in different businesses reuse the same request key
    When each of them changes their PIN
    Then each PIN change is handled independently for its own business
