Feature: Treasury operations
  As a platform administrator
  I want to manage the operator float, bank records, and customer wallets safely
  So that money moves only with proper approval and always to the right place

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And money moves are proposed first and only take effect once a second admin approves them

  # --- Adjusting the operator float ---

  Scenario: Verify topping up the operator float raises it and lowers the chosen bank record
    Given I have proposed topping up the operator float against a chosen bank record
    When a second admin approves the move
    Then the float goes up and the chosen bank record goes down by that amount

  Scenario: Verify a float adjustment affects only the bank record the operator chose
    Given several bank records exist and I have proposed a float adjustment against one of them
    When a second admin approves the move
    Then only the chosen bank record changes and the others are untouched

  Scenario: Verify drawing down the operator float lowers it and raises the chosen bank record
    Given the operator float has been topped up
    And I have proposed drawing money out of the float against a chosen bank record
    When a second admin approves the move
    Then the float goes down and the chosen bank record goes up by that amount

  Scenario: Verify an operator cannot make a float adjustment of zero
    When I try to propose a float adjustment of zero
    Then the request is refused

  Scenario: Verify an operator cannot adjust another tenant's float
    Given I have proposed adjusting a float that belongs to another tenant
    When a second admin approves the move
    Then the move is reported as not found

  Scenario: Verify a bank record cannot itself be the target of a float adjustment
    Given I have proposed a float adjustment that targets a bank record itself
    When a second admin approves the move
    Then the move is refused

  Scenario: Verify adjusting an account that does not exist is refused
    Given I have proposed a float adjustment against an account that does not exist
    When a second admin approves the move
    Then the move is reported as not found

  Scenario: Verify adjusting the float against a bank record that does not exist is refused
    Given I have proposed a float adjustment against a bank record that does not exist
    When a second admin approves the move
    Then the move is reported as not found

  Scenario: Verify a float adjustment must use a bank record in the same currency
    Given I have proposed a float adjustment against a bank record in a different currency
    When a second admin approves the move
    Then the move is refused

  Scenario: Verify an unauthenticated user cannot adjust the operator float
    Given I am not signed in
    When I try to propose a float adjustment
    Then the request is refused

  Scenario: Verify a float adjustment must name which bank record to use
    When I try to propose a float adjustment without naming a bank record
    Then the request is refused

  # --- Managing bank records ---

  Scenario: Verify an operator can add a named bank record once a second operator approves it
    Given I have proposed adding a named bank record
    When a second admin approves it
    Then the named bank record is created

  Scenario: Verify a bank record cannot reuse a name already taken in the same currency
    Given a bank record with a name already exists for a currency
    And I have proposed adding another with the same name and currency
    When a second admin approves it
    Then the request is refused

  Scenario: Verify two differently named bank records can exist for the same currency
    Given I have proposed adding two differently named bank records for the same currency
    When a second admin approves each of them
    Then both bank records exist

  Scenario: Verify an unauthenticated user cannot add a bank record
    Given I am not signed in
    When I try to add a bank record
    Then the request is refused

  Scenario: Verify a user without administrator rights cannot add a bank record
    Given I am signed in without administrator rights
    When I try to add a bank record
    Then the request is refused

  Scenario: Verify a bank record must be given a name
    When I try to add a bank record with a blank name
    Then the request is refused

  Scenario: Verify an operator can rename a bank record
    Given a bank record exists
    When I rename it
    Then the bank record shows the new name

  Scenario: Verify a bank record cannot be renamed to a name already in use
    Given two bank records exist for the same currency
    When I try to rename one to the other's name
    Then the rename is refused

  Scenario: Verify renaming a bank record that does not exist is refused
    When I try to rename a bank record that does not exist
    Then the request is reported as not found

  Scenario: Verify only bank records can be renamed through this screen
    Given a system account that is not a bank record exists
    When I try to rename it through the bank records screen
    Then the request is reported as not found

  Scenario: Verify an operator cannot rename another tenant's bank record
    Given a bank record belongs to another tenant
    When I try to rename it
    Then the request is reported as not found

  Scenario: Verify an unauthenticated user cannot rename a bank record
    Given I am not signed in
    When I try to rename a bank record
    Then the request is refused

  # --- Topping up a customer wallet ---

  Scenario: Verify an admin can top up a customer's wallet from the operator float
    Given I have proposed topping up a customer's wallet from the operator float
    When a second admin approves it
    Then the customer's wallet is credited with the amount

  Scenario: Verify an admin cannot top up a wallet by a negative amount
    When I try to propose a top-up of a negative amount
    Then the request is refused

  Scenario: Verify an admin must give a reason when topping up a wallet
    When I try to propose a top-up without giving a reason
    Then the request is refused

  Scenario: Verify topping up a wallet for an unknown tenant is refused
    When I try to propose a top-up for a tenant that does not exist
    Then the request is reported as not found

  Scenario: Verify a top-up that would push a wallet past its maximum balance is refused
    Given the customer's wallet has a maximum balance set
    And I have proposed a top-up that would exceed that maximum
    When a second admin approves it
    Then the top-up is refused and the wallet balance is unchanged

  # --- Viewing the operator wallets ---

  Scenario: Verify an admin can see every operator wallet with its balance
    When I list the operator wallets
    Then I see every operator wallet with its balance

  Scenario: Verify customer wallets do not appear in the operator wallet list
    Given a customer has a wallet
    When I list the operator wallets
    Then no customer wallet appears in the list

  Scenario: Verify an admin can drill into an operator wallet's transactions
    Given a customer wallet has been topped up from the float
    When I drill into the operator float wallet's transactions
    Then I see the matching entry with its customer receipt number

  Scenario: Verify an admin cannot view another tenant's operator wallet transactions
    When I try to view the transactions of an operator wallet under another tenant
    Then the request is reported as not found

  Scenario: Verify viewing transactions for an account that does not exist is refused
    When I try to view the transactions of an account that does not exist
    Then the request is reported as not found

  # --- Pulling funds back from a customer ---

  Scenario: Verify an admin can pull funds from a customer's wallet once a second admin approves it
    Given I have proposed pulling funds from a customer's funded wallet
    When a second admin approves it
    Then the funds leave the customer's wallet

  Scenario: Verify a pulled-back amount lands on the bank record the operator chose
    Given several bank records exist and I have proposed a pull-back against a chosen one
    When a second admin approves it
    Then the amount lands only on the chosen bank record

  Scenario: Verify pulling funds against a bank record that does not exist is refused
    Given I have proposed a pull-back against a bank record that does not exist
    When a second admin approves it
    Then the move is reported as not found

  Scenario: Verify pulling funds against another tenant's bank record is refused
    Given I have proposed a pull-back against another tenant's bank record
    When a second admin approves it
    Then the move is reported as not found

  Scenario: Verify pulling funds must use a bank record in the same currency
    Given I have proposed a pull-back against a bank record in a different currency
    When a second admin approves it
    Then the move is refused

  Scenario: Verify an admin cannot pull back more than a customer's wallet holds
    Given I have proposed pulling back more than the customer's wallet holds
    When a second admin approves it
    Then the move is refused as insufficient funds

  Scenario: Verify pulling funds from a customer with no wallet in that currency is refused
    Given I have proposed a pull-back from a customer with no wallet in that currency
    When a second admin approves it
    Then the move is reported as not found

  Scenario: Verify an unauthenticated user cannot pull funds from a customer
    Given I am not signed in
    When I try to propose a pull-back
    Then the request is refused

  Scenario: Verify pulling funds must name which bank record to use
    When I try to propose a pull-back without naming a bank record
    Then the request is refused

  Scenario: Verify a stray PIN field does not affect an admin fund pull-back
    Given I have proposed a pull-back that includes a stray PIN field
    When a second admin approves it
    Then the stray field is ignored and the pull-back completes

  Scenario: Verify an admin cannot pull funds from a customer in another tenant
    Given I have proposed a pull-back scoped to another tenant for the customer
    When a second admin approves it
    Then the move is reported as not found

  Scenario: Verify pulling back everything empties a customer's wallet
    Given I have proposed pulling back everything from a funded wallet
    When a second admin approves it
    Then the customer's wallet is emptied

  Scenario: Verify an admin cannot ask to pull back everything and a fixed amount at once
    When I try to propose a pull-back of both everything and a fixed amount
    Then the request is refused

  Scenario: Verify an admin must say how much to pull back
    When I try to propose a pull-back without saying how much
    Then the request is refused

  Scenario: Verify pulling back everything from an empty wallet is refused
    Given I have proposed pulling back everything from an empty wallet
    When a second admin approves it
    Then the move is refused because there is nothing to withdraw
