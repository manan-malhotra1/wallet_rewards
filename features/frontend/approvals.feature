Feature: Approvals
  As an administrator working the maker-checker surfaces, I can review a
  colleague's proposed change, approve it or send it back for changes, and — as
  the maker — withdraw or revise my own pending proposal. Each scenario maps
  one-to-one to a Vitest interaction test co-located with its component.

  # --- Treasury moves (money-operations detail drawer) --------------------

  Scenario: Verify a second admin can approve a pending treasury move
    Given a treasury move is pending and I did not propose it
    And I am a treasury approver
    When I click Approve and then confirm
    Then the move is submitted for approval with its tenant and id
    And the drawer refreshes with the updated move

  Scenario: Verify requesting changes on a treasury move needs a comment
    Given a pending treasury move I am reviewing
    When I try to request changes without a comment
    Then nothing is sent and I am told a comment is required
    And when I add a comment and submit, the change request carries that comment

  Scenario: Verify a rejected approval attempt shows the reason
    Given a pending treasury move I am reviewing
    And the backend will reject my approval
    When I click Approve and then confirm
    Then the drawer shows the returned error code and reason

  Scenario: Verify the maker can withdraw their own pending treasury move
    Given a treasury move I proposed and that is still pending
    When I click Withdraw and then confirm
    Then the move is withdrawn with its tenant and id
    And the drawer refreshes with the updated move

  Scenario: Verify the maker can revise and resubmit a returned treasury move
    Given a treasury move I proposed that was sent back for changes
    When I open the revise editor and resubmit
    Then the revised payload is re-submitted for a fresh approval round

  # --- User changes (user-operations detail drawer) -----------------------

  Scenario: Verify a second admin can approve a pending user change
    Given a user change is pending and I did not propose it
    And I am a user approver
    When I click Approve and then confirm
    Then the user change is submitted for approval with its tenant and id
    And the drawer refreshes with the updated operation

  Scenario: Verify requesting changes on a user change needs a comment
    Given a pending user change I am reviewing
    When I try to request changes without a comment
    Then nothing is sent and I am told a comment is required
    And when I add a comment and submit, the change request carries that comment

  Scenario: Verify a rejected approval attempt on a user change shows the reason
    Given a pending user change I am reviewing
    And the backend will reject my approval
    When I click Approve and then confirm
    Then the drawer shows the returned error code and reason

  Scenario: Verify the maker can withdraw their own pending user change
    Given a user change I proposed and that is still pending
    When I click Withdraw and then confirm
    Then the user change is withdrawn with its tenant and id
    And the drawer refreshes with the updated operation

  Scenario: Verify the maker can revise and resubmit a returned user change
    Given a user change I proposed that was sent back for changes
    When I open the revise editor and resubmit
    Then the revised payload is re-submitted for a fresh approval round

  # --- Config changes (config-requests detail drawer) ---------------------

  Scenario: Verify a second admin can approve a pending config change
    Given a config change is pending and I did not propose it
    And I am a config approver
    When I click Approve
    Then the config change is approved with its tenant and id
    And the drawer refreshes with the updated request

  Scenario: Verify requesting changes on a config change needs a comment
    Given a pending config change I am reviewing
    When I try to request changes without a comment
    Then nothing is sent and I am told a comment is required
    And when I add a comment and submit, the change request carries that comment

  Scenario: Verify a rejected approval attempt on a config change shows the reason
    Given a pending config change I am reviewing
    And the backend will reject my approval
    When I click Approve
    Then the drawer shows the returned error code and reason

  Scenario: Verify the maker can withdraw their own pending config change
    Given a config change I proposed and that is still pending
    When I click Withdraw
    Then the config change is withdrawn with its tenant and id
    And the drawer refreshes with the updated request

  # --- Open requests on the native config pages ---------------------------

  Scenario: Verify the maker can withdraw a pending commission change
    Given a commission change I proposed that is under approval
    When I click Withdraw and confirm the prompt
    Then the commission change is withdrawn with its tenant and id

  Scenario: Verify a colleague can see a commission change but cannot withdraw it
    Given a commission change proposed by someone else
    When I look at the open request
    Then I can open its read-only details
    But I see neither a Withdraw nor an Edit & resubmit control

  Scenario: Verify the maker can reopen a returned commission change to edit it
    Given a commission change I proposed that was sent back for changes
    When I look at the open request
    Then an Edit & resubmit control is available to me

  Scenario: Verify the maker can withdraw a pending fee change
    Given a fee change I proposed that is under approval
    When I click Withdraw and confirm the prompt
    Then the fee change is withdrawn with its tenant and id

  Scenario: Verify the maker can reopen a returned fee change to edit it
    Given a fee change I proposed that was sent back for changes
    When I look at the open request
    Then an Edit & resubmit control is available to me

  Scenario: Verify the maker can withdraw a pending tax change
    Given a tax change I proposed that is under approval
    When I click Withdraw and confirm the prompt
    Then the tax change is withdrawn with its tenant and id

  Scenario: Verify the maker can reopen a returned tax change to edit it
    Given a tax change I proposed that was sent back for changes
    When I look at the open request
    Then an Edit & resubmit control is available to me

  Scenario: Verify the maker can withdraw a pending PIN step-up change
    Given a PIN step-up change I proposed that is under approval
    When I click Withdraw and confirm the prompt
    Then the step-up change is withdrawn with its tenant and id

  Scenario: Verify the maker can reopen a returned PIN step-up change to edit it
    Given a PIN step-up change I proposed that was sent back for changes
    When I look at the open request
    Then an Edit & resubmit control is available to me

  Scenario: Verify the maker can withdraw a pending limit change
    Given a limit change I proposed that is under approval
    When I click Withdraw and confirm the prompt
    Then the limit change is withdrawn with its tenant and id

  Scenario: Verify the maker can reopen a returned spending limit to edit it
    Given a spending limit change I proposed that was sent back for changes
    When I look at the open request
    Then an Edit & resubmit control is available to me

  Scenario: Verify the maker can reopen a returned wallet balance limit to edit it
    Given a wallet balance limit change I proposed that was sent back for changes
    When I look at the open request
    Then an Edit & resubmit control is available to me
