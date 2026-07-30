Feature: Treasury & system wallets
  As an admin operator
  I want to move money into and out of customer and system wallets, manage bank
  mirrors, and review ledger activity
  So that the platform's float and customer balances stay funded, balanced and auditable.

  Background:
    Given I am signed in as an admin operator
    And I am on the System Wallets page

  # --- Fund a user wallet (fund-user-dialog) --------------------------------

  Scenario: Verify an admin can top up a customer's wallet from the operator float
    Given I open the "Fund a user wallet" dialog
    When I identify the customer by phone "+27 82 555 0001"
    And I enter an amount of "500" in "ZAR"
    And I enter the reason "Refund for failed fund"
    And I submit the fund
    Then the fund is proposed for approval with that customer, amount and reason
    And the dialog closes

  Scenario: Verify funding is blocked when the amount is empty
    Given I open the "Fund a user wallet" dialog
    When I identify the customer by phone "+27 82 555 0001"
    And I enter the reason "Refund for failed fund"
    And I leave the amount empty
    And I submit the fund
    Then I see the message "Amount must be a positive number."
    And no fund is proposed

  Scenario: Verify a failed top-up shows the error to the admin
    Given I open the "Fund a user wallet" dialog
    And the operator float is empty
    When I identify the customer by phone "+27 82 555 0001"
    And I enter an amount of "500" in "ZAR"
    And I enter the reason "Refund for failed fund"
    And I submit the fund
    Then I see the backend error "InsufficientFloat: Operator float is empty. Top up from the bank first."
    And the dialog stays open so I can retry

  # --- Withdraw from a user wallet (withdraw-from-user-dialog) ---------------

  Scenario: Verify an admin can pull funds back from a customer into a bank mirror
    Given I open the "Withdraw from a user wallet" dialog
    When I identify the customer by phone "+27 82 555 0001"
    And I enter an amount of "200" in "ZAR"
    And I choose the bank mirror "Standard Bank — main float" as the counter-leg
    And I enter the reason "Cash-out at agent counter"
    And I submit the withdrawal
    Then the withdrawal is proposed with that customer, amount, reason and bank mirror
    And the dialog closes

  Scenario: Verify a withdrawal is blocked until a bank mirror is chosen
    Given I open the "Withdraw from a user wallet" dialog
    When I identify the customer by phone "+27 82 555 0001"
    And I enter an amount of "200" in "ZAR"
    And I enter the reason "Cash-out at agent counter"
    And I submit the withdrawal without choosing a bank mirror
    Then I see the message "Select a bank mirror for the counter-leg."
    And no withdrawal is proposed

  Scenario: Verify a rejected withdrawal shows the error to the admin
    Given I open the "Withdraw from a user wallet" dialog
    When I identify the customer by phone "+27 82 555 0001"
    And I enter an amount of "200" in "ZAR"
    And I choose the bank mirror "Standard Bank — main float" as the counter-leg
    And I enter the reason "Cash-out at agent counter"
    And I submit the withdrawal
    Then I see the backend error "insufficient_funds: The customer wallet does not hold that much."
    And the dialog stays open so I can retry

  # --- Adjust a system wallet (adjust-system-wallet-dialog) ------------------

  Scenario: Verify an admin can add float to a system wallet
    Given I open the "Adjust system wallet" dialog for a system wallet in "ZAR"
    When the direction is set to Fund
    And I enter an amount of "1000000"
    And I choose the bank mirror "Standard Bank — main float" as the counter-leg
    And I enter the reason "Initial float wire 8023"
    And I submit the adjustment
    Then the adjustment is proposed with a positive amount against that bank mirror
    And the dialog closes

  Scenario: Verify an admin can draw float down from a system wallet
    Given I open the "Adjust system wallet" dialog for a system wallet in "ZAR"
    When I switch the direction to Withdraw
    And I enter an amount of "50000"
    And I choose the bank mirror "Standard Bank — main float" as the counter-leg
    And I enter the reason "Ops expense Q3"
    And I submit the adjustment
    Then the adjustment is proposed with a negative amount against that bank mirror

  Scenario: Verify an adjustment is blocked when the amount is empty
    Given I open the "Adjust system wallet" dialog for a system wallet in "ZAR"
    When I choose the bank mirror "Standard Bank — main float" as the counter-leg
    And I enter the reason "Initial float wire 8023"
    And I leave the amount empty
    And I submit the adjustment
    Then I see the message "Amount must be a positive number."
    And no adjustment is proposed

  Scenario: Verify a rejected adjustment shows the error to the admin
    Given I open the "Adjust system wallet" dialog for a system wallet in "ZAR"
    When the direction is set to Fund
    And I enter an amount of "1000000"
    And I choose the bank mirror "Standard Bank — main float" as the counter-leg
    And I enter the reason "Initial float wire 8023"
    And I submit the adjustment
    Then I see the backend error "InsufficientFloat: The bank mirror cannot go negative."
    And the dialog stays open so I can retry

  # --- Create a bank mirror (new-bank-mirror-dialog) -------------------------

  Scenario: Verify an admin can create a named bank mirror
    Given I open the "New bank mirror" dialog
    When I enter the name "Standard Bank — main float"
    And I keep the default currency "ZAR"
    And I submit the new bank mirror
    Then the bank mirror is proposed with that name and currency
    And the dialog closes

  Scenario: Verify an admin can create a bank mirror in a chosen currency
    Given I open the "New bank mirror" dialog
    When I enter the name "Chase — USD settlement"
    And I choose the currency "USD"
    And I submit the new bank mirror
    Then the bank mirror is proposed with that name and the "USD" currency

  Scenario: Verify creating a bank mirror is blocked when the name is empty
    Given I open the "New bank mirror" dialog
    When I submit the new bank mirror without a name
    Then I see the message "Name is required."
    And no bank mirror is proposed

  Scenario: Verify a duplicate bank mirror name shows the error to the admin
    Given I open the "New bank mirror" dialog
    When I enter the name "Standard Bank — main float"
    And I submit the new bank mirror
    Then I see the backend error "duplicate_name: A bank mirror with that name already exists."
    And the dialog stays open so I can retry

  # --- Rename a bank mirror (rename-bank-mirror-dialog) ----------------------

  Scenario: Verify an admin can rename a bank mirror
    Given I open the rename dialog for the bank mirror "Standard Bank — main float"
    When I change the name to "Standard Bank — settlement"
    And I save the rename
    Then the rename is submitted with the new name for that bank mirror
    And the dialog closes

  Scenario: Verify renaming is blocked when the name is cleared
    Given I open the rename dialog for the bank mirror "Standard Bank — main float"
    When I clear the name
    And I save the rename
    Then I see the message "Name is required."
    And no rename is submitted

  Scenario: Verify a rename collision shows the error to the admin
    Given I open the rename dialog for the bank mirror "Standard Bank — main float"
    When I change the name to "Chase — USD settlement"
    And I save the rename
    Then I see the backend error "duplicate_name: Another bank mirror already uses that name."
    And the dialog stays open so I can retry

  # --- Review transactions (transactions-dialog) -----------------------------

  Scenario: Verify an admin can review recent transactions on a system wallet
    Given the system wallet has a completed "Fund" transaction of "500" ZAR
    When I open the recent-transactions drill-down for that wallet
    Then I see the transaction listed as "Fund" with its reference and a CREDIT direction

  Scenario: Verify an admin sees a clear message when a wallet has no transactions yet
    Given the system wallet has no transactions
    When I open the recent-transactions drill-down for that wallet
    Then I see the message "No transactions on this account yet."

  Scenario: Verify an admin sees an error when the transaction history can't load
    Given the transaction history service is unreachable
    When I open the recent-transactions drill-down for that wallet
    Then I see an inline error explaining the history could not load
