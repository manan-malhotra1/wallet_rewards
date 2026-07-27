Feature: Opening accounts and checking balances
  As a platform administrator
  I want to open customer and system accounts and read their balances
  So that customers can hold funds and points and everyone can trust the numbers

  Background:
    Given a business is set up on the platform
    And a customer belongs to that business
    And every balance is worked out purely from the account's completed transactions

  Scenario: Verify a new customer wallet is created and starts active
    Given a customer with no wallet yet
    When I open a wallet for the customer
    Then the wallet is created and is ready to use

  Scenario: Verify a system rewards points account can be opened without an owner
    Given the business needs a rewards points account
    When I open a system points account
    Then it is created without belonging to any customer or merchant

  Scenario: Verify an account cannot be opened for an unknown business
    Given I name a business that does not exist
    When I try to open an account for it
    Then the request is refused

  Scenario: Verify an unrecognised account type is rejected
    Given I ask for an account type the platform does not offer
    When I try to open the account
    Then the request is rejected

  Scenario: Verify the account currency is saved in a standard uppercase form
    Given I open an account giving the currency in lower case
    When the account is created
    Then the currency is stored in the standard uppercase form

  Scenario: Verify opening an account is recorded in the audit trail
    Given I open an account for the customer
    When the account is created
    Then the action is recorded in the audit trail

  Scenario: Verify a new customer starts with a zero balance
    Given a customer's brand-new account
    When I check its balance
    Then the balance is zero

  Scenario: Verify checking the balance of an unknown account is rejected
    Given an account that does not exist
    When I check its balance
    Then the request is refused

  Scenario: Verify one business cannot see another business's account balance
    Given an account belongs to one business
    When another business tries to read its balance
    Then the request is refused

  Scenario: Verify a customer's balance reflects their completed transactions
    Given a customer's wallet receives a completed transaction
    When I check the balance
    Then it reflects the money moved by that transaction
