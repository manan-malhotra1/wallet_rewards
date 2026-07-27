Feature: Treasury operation wording
  As an administrator reviewing money approvals
  I want treasury operations labelled and summarised in plain language
  So that I can approve or reject them without decoding raw codes

  Background:
    Given I am an administrator using the admin portal

  Scenario: Verify withdrawing from a user is labelled 'Withdraw from user'
    Given a treasury operation of type "withdraw_user"
    When I view it in the money-approvals table
    Then it is labelled "Withdraw from user"

  Scenario: Verify an unrecognised treasury operation is shown as-is rather than hidden
    Given a treasury operation of an unknown type "teleport_funds"
    When I view it in the money-approvals table
    Then it is shown as "teleport_funds" rather than hidden

  Scenario: Verify funding a user reads as the amount, currency and recipient on one line
    Given a fund-user operation of "150" "ZAR" to recipient "Bob Jones"
    When I read its one-line summary
    Then it reads "ZAR 150.00 → Bob Jones"

  Scenario: Verify adjusting a treasury wallet shows whether the amount is added or removed, and on which account
    Given an adjust-system-wallet operation of "-50" on account "Cash float"
    When I read its one-line summary
    Then it reads "−50.00 on Cash float"
