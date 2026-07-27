Feature: Admin user changes with maker-checker
  As a platform administrator
  I want creating and editing users to be proposed and independently approved
  So that no single admin can create or change a user on their own

  Background:
    Given I am a platform administrator for my tenant
    And user changes are proposed first and only take effect once approved
    And an approval must come from a different admin who holds user approval rights

  # --- A second admin's approval applies the change (four_eyes) ---

  Scenario: Verify a second admin's approval actually creates the new user
    Given I have proposed creating a new user
    When a second admin with user approval rights approves the change
    Then the change is applied and the new user is created

  Scenario: Verify a second admin's approval applies the edits to the user
    Given I have proposed editing an existing user's status, type and name
    When a second admin approves the change
    Then the edits are applied to the user

  Scenario: Verify the admin who proposed a user change cannot approve their own change
    Given I have proposed a user change and I also hold user approval rights
    When I try to approve my own change
    Then the approval is refused as a self-approval and no user is changed

  Scenario: Verify only an admin with user approval rights can approve a user change
    Given I have proposed a user change
    When another admin without user approval rights tries to approve it
    Then the approval is refused

  Scenario: Verify an already-applied user change cannot be approved again to create a duplicate
    Given a create-user change has already been approved and applied
    When another admin tries to approve the completed change again
    Then the second approval is refused and no duplicate user is created

  Scenario: Verify approving a user change that does not exist is reported as not found
    When an approver tries to approve a user change that does not exist
    Then the request is reported as not found

  # --- How many approvals are required (n_eyes) ---

  Scenario: Verify a user change needing two approvals only applies after two different admins approve
    Given a user change that requires two approvals has been proposed
    When the first admin approves, the change stays pending
    And a second different admin approves, the change is applied

  Scenario: Verify one admin cannot supply both required approvals for a user change
    Given a user change that requires two approvals has been proposed
    When the same admin tries to approve it twice
    Then the second attempt is refused as a duplicate approval

  # --- Proposing holds the change until approved (propose) ---

  Scenario: Verify proposing to create a user creates no user until approved
    When I propose creating a new user
    Then the change is recorded as pending and no user has been created

  Scenario: Verify proposing to edit a user leaves the user unchanged until approved
    Given an existing user
    When I propose editing that user
    Then the change is recorded as pending and the user is unchanged

  Scenario: Verify proposing an edit to a user who does not exist is reported as not found
    When I propose editing a user who does not exist in this tenant
    Then the request is reported as not found

  Scenario: Verify a new user must have at least an email or phone number
    When I propose creating a user with no email or phone number
    Then the request is rejected as invalid

  Scenario: Verify an unrecognised user change type is rejected
    When I propose a user change of a type the system does not recognise
    Then the request is rejected as invalid

  Scenario: Verify only a platform admin can propose a user change
    Given I do not hold platform-admin rights
    When I try to propose a user change
    Then the request is refused

  # --- Request changes, revise, resubmit, withdraw (changes_loop) ---

  Scenario: Verify a checker can send a user change back to the proposer with a comment
    Given I have proposed a user change
    When a checker asks for changes with a comment
    Then the change is sent back for changes and the comment is recorded

  Scenario: Verify asking for changes on a user change requires a comment explaining why
    Given I have proposed a user change
    When a checker asks for changes without giving a comment
    Then the request is rejected as invalid

  Scenario: Verify resubmitting a revised user change clears earlier approvals and starts fresh
    Given a user change was sent back for changes
    When I revise the change and resubmit it
    Then the approvals reset and a different admin may approve the fresh round to apply it

  Scenario: Verify a withdrawn user change can no longer be approved or applied
    Given I have withdrawn a user change I proposed
    When an approver tries to approve the withdrawn change
    Then the approval is refused and no user is changed

  Scenario: Verify only the admin who proposed a user change can withdraw it
    Given I have proposed a user change
    When a different admin tries to withdraw it
    Then the request is refused

  # --- Changes stay within one tenant (tenant_isolation) ---

  Scenario: Verify one tenant cannot see another tenant's user change
    Given a user change has been proposed in one tenant
    When I try to view it while working in a different tenant
    Then the change is reported as not found

  Scenario: Verify one tenant cannot approve another tenant's user change
    Given a user change has been proposed in one tenant
    When an approver tries to approve it while working in a different tenant
    Then the change is reported as not found

  # --- Every change is recorded in the audit trail (audit) ---

  Scenario: Verify proposing and approving a user change is fully recorded in the audit trail
    Given I have proposed creating a user
    When a second admin approves the change
    Then the audit trail records the proposal, the approval and the application
