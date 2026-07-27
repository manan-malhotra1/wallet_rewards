Feature: Treasury money operations with maker-checker
  As a platform administrator
  I want every treasury money move to be proposed and independently approved
  So that no single admin can move money on their own

  Background:
    Given I am a platform administrator for my tenant
    And treasury moves are proposed first and only take effect once approved
    And an approval must come from a different admin who holds treasury approval rights

  # --- A second admin's approval makes a move happen (four_eyes) ---

  Scenario: Verify a second admin's approval credits the user's wallet with the funded amount
    Given I have proposed funding a user's wallet and the cash float is topped up
    When a second admin with treasury approval rights approves the move
    Then the move is applied and the user's wallet is credited with the funded amount

  Scenario: Verify an approved withdrawal moves money out of the user's wallet
    Given I have proposed withdrawing money from a funded user's wallet
    When a second admin approves the move
    Then the money leaves the user's wallet and lands in the chosen bank mirror

  Scenario: Verify an approved top-up adds money to the operator's system wallet
    Given I have proposed a top-up of the operator's system wallet
    When a second admin approves the move
    Then the system wallet is credited with the top-up amount

  Scenario: Verify an approved request creates the new bank mirror account
    Given I have proposed creating a new bank mirror account
    When a second admin approves the request
    Then the new bank mirror account is created

  Scenario: Verify the admin who proposed a move cannot approve their own move
    Given I have proposed a move and I also hold treasury approval rights
    When I try to approve my own move
    Then the approval is refused as a self-approval and nothing happens

  Scenario: Verify only an admin with treasury approval rights can approve a move
    Given I have proposed a move
    When another admin without treasury approval rights tries to approve it
    Then the approval is refused

  Scenario: Verify an already-completed move cannot be approved again to move money twice
    Given a funding move has already been approved and applied
    When another admin tries to approve the completed move again
    Then the second approval is refused and no money moves a second time

  Scenario: Verify approving a move that does not exist is reported as not found
    When an approver tries to approve a move that does not exist
    Then the request is reported as not found

  # --- How many approvals the policy requires (n_eyes_policy) ---

  Scenario: Verify a move requiring two approvals only happens after two different admins approve
    Given the tenant's policy requires two approvals for a move
    And I have proposed the move
    When the first admin approves, the move stays pending
    And a second different admin approves, the move is applied

  Scenario: Verify one admin cannot supply both required approvals for a move
    Given the tenant's policy requires two approvals and I have proposed a move
    When the same admin tries to approve it twice
    Then the second attempt is refused as a duplicate approval

  Scenario: Verify the proposing admin cannot count as one of the two required approvers
    Given the tenant's policy requires two approvals and I have proposed a move
    When I try to approve my own move
    Then the approval is refused as a self-approval

  Scenario: Verify an approval rule set for a specific move overrides the tenant-wide default
    Given the tenant has a default approval rule and a stricter rule for a specific move type
    When I propose a move of that specific type
    Then the number of approvals required follows the specific rule

  Scenario: Verify the tenant-wide approval rule applies to moves without their own rule
    Given the tenant has only a tenant-wide default approval rule
    When I propose a move that has no rule of its own
    Then the number of approvals required follows the tenant-wide default

  Scenario: Verify a move needs one approval when no approval rule is configured
    Given the tenant has no approval rules configured
    When I propose a move
    Then the move requires a single approval

  Scenario: Verify a single approval does not move money when two are required
    Given the tenant's policy requires two approvals and I have proposed a move
    When only one admin approves it
    Then no money moves and no account is created yet

  # --- Proposing holds the move until approved (propose) ---

  Scenario: Verify proposing to fund a user moves no money until approved
    When I propose funding a user's wallet
    Then the move is recorded as pending and no money has moved

  Scenario: Verify proposing a withdrawal leaves the user's balance untouched until approved
    Given a user has a funded wallet
    When I propose a withdrawal from that wallet
    Then the move is recorded as pending and the user's balance is untouched

  Scenario: Verify proposing a system-wallet top-up moves no money until approved
    When I propose a top-up of the operator's system wallet
    Then the move is recorded as pending and no money has moved

  Scenario: Verify proposing a bank mirror creates no account until approved
    When I propose creating a bank mirror
    Then the move is recorded as pending and no account has been created

  Scenario: Verify a move with an invalid amount is rejected before it is recorded
    When I propose a move with a negative amount
    Then the request is rejected as invalid

  Scenario: Verify an unrecognised move type is rejected
    When I propose a move of a type the system does not recognise
    Then the request is rejected as invalid

  Scenario: Verify only a platform admin can propose a treasury move
    Given I hold treasury approval rights but not platform-admin rights
    When I try to propose a treasury move
    Then the request is refused

  Scenario: Verify proposing a move for an unknown tenant is reported as not found
    When I propose a move against a tenant that does not exist
    Then the request is reported as not found

  # --- Moves stay within one tenant (tenant_isolation) ---

  Scenario: Verify one tenant cannot see another tenant's treasury move
    Given a move has been proposed in one tenant
    When I try to view it while working in a different tenant
    Then the move is reported as not found

  Scenario: Verify one tenant cannot approve another tenant's treasury move
    Given a move has been proposed in one tenant
    When an approver tries to approve it while working in a different tenant
    Then the move is reported as not found

  Scenario: Verify the moves list shows only the current tenant's moves
    Given a move has been proposed in one tenant
    When I list the moves for a different tenant
    Then that tenant's list does not include the other tenant's move

  Scenario: Verify the books still balance after a treasury move is applied
    Given I have proposed a withdrawal from a funded wallet
    When a second admin approves and the move is applied
    Then the tenant's books still balance to zero

  # --- Treasury buttons propose instead of moving money directly (treasury_gated) ---

  Scenario: Verify using the fund-user button proposes a move instead of paying out immediately
    When I use the fund-user button on the treasury screen
    Then a pending move is created and no money has moved yet

  Scenario: Verify a fund-user move made from the treasury screen pays out once approved
    Given I have used the fund-user button and the cash float is topped up
    When a second admin approves the move
    Then the user's wallet is credited with the funded amount

  Scenario: Verify using the bank-mirror button proposes a move instead of creating the account
    When I use the bank-mirror button on the treasury screen
    Then a pending move is created and no account has been created yet

  Scenario: Verify a signed-out user cannot propose a treasury move
    Given I am not signed in
    When I try to propose a treasury move
    Then the request is refused as unauthenticated

  # --- Request changes, revise, resubmit, withdraw (changes_loop) ---

  Scenario: Verify asking for changes on a move requires a comment explaining why
    Given I have proposed a move
    When a checker asks for changes without giving a comment
    Then the request is rejected as invalid

  Scenario: Verify a checker can send a move back to the proposer with a comment
    Given I have proposed a move
    When a checker asks for changes with a comment
    Then the move is sent back for changes and the comment is recorded

  Scenario: Verify resubmitting a revised move clears earlier approvals and starts fresh
    Given a move needing two approvals has one approval and was then sent back for changes
    When I revise the move and resubmit it
    Then the approvals reset to zero and the earlier approver may approve the fresh round

  Scenario: Verify only the admin who proposed a move can revise it
    Given a move I proposed has been sent back for changes
    When a different admin tries to revise it
    Then the request is refused

  Scenario: Verify a withdrawn move can no longer be approved or executed
    Given I have withdrawn a move I proposed
    When an approver tries to approve the withdrawn move
    Then the approval is refused and nothing is executed

  Scenario: Verify only the admin who proposed a move can withdraw it
    Given I have proposed a move
    When a different admin tries to withdraw it
    Then the request is refused

  Scenario: Verify the move keeps a full history of every step from proposal to completion
    Given I have taken a move through changes, revision, resubmission and approval
    When I open the move's history
    Then every step from proposal to completion is recorded in order
