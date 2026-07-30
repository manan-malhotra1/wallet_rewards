Feature: Managing customers
  As an administrator managing customer accounts
  I want to look up, register, edit, and secure customers from the admin portal
  So that customer records stay correct and access controls are applied safely

  Background:
    Given I am signed in as an administrator using the admin portal

  # ── Customer lookup ───────────────────────────────────────────────
  Scenario: Verify an admin can look up a customer by phone number
    Given I am on the Users page
    When I enter the phone number "+27 82 555 0142" and press Lookup
    Then the portal searches by the canonical number "+27825550142"

  Scenario: Verify an admin can look up a customer by email address
    Given I am on the Users page with the identifier set to Email
    When I enter the email "jane@example.com" and press Lookup
    Then the portal searches by that email address

  Scenario: Verify a blank lookup does nothing until an identifier is entered
    Given I am on the Users page
    When I press Lookup without entering an identifier
    Then no search is performed and I stay on the page

  # ── Registering a customer (maker-checker) ────────────────────────
  Scenario: Verify creating a customer is proposed for approval
    Given I have opened the Register user form
    When I enter a phone identifier and submit for approval
    Then a create-user request is proposed for the customer
    And I am told it is awaiting approval and taken to the approvals queue

  Scenario: Verify registering a customer with no identifier is blocked
    Given I have opened the Register user form
    When I submit for approval without entering an identifier
    Then I am asked to enter a phone number or email address
    And no create-user request is proposed

  Scenario: Verify a rejected registration shows the reason and does not leave the form
    Given I have opened the Register user form
    When I submit a phone identifier that is already registered
    Then I see that the phone number is already registered
    And I remain on the form to correct it

  # ── Editing a customer (maker-checker) ────────────────────────────
  Scenario: Verify editing a customer is proposed for approval with only the changed field
    Given I have opened the Edit user drawer for a customer
    When I change only the first name and submit for approval
    Then an update request is proposed containing just the changed first name
    And I am told it is awaiting approval and taken to the approvals queue

  Scenario: Verify submitting an edit with no changes is blocked
    Given I have opened the Edit user drawer for a customer
    When I submit for approval without changing any field
    Then I am asked to change at least one field first
    And no update request is proposed

  Scenario: Verify a rejected edit shows the reason
    Given I have opened the Edit user drawer for a customer
    When I change a field and the proposal is rejected
    Then I see the rejection reason and stay on the drawer

  Scenario: Verify a customer with a pending edit cannot have another proposed
    Given a customer already has an edit awaiting approval
    When I open the Edit user drawer for that customer
    Then I am told an edit is already awaiting approval instead of an editable form
    And I am offered a way to go to User approvals

  # ── Adding an identifier ──────────────────────────────────────────
  Scenario: Verify an admin can add a phone identifier to a customer
    Given I have opened the Add identifier dialog for a customer
    When I enter a phone value and add it
    Then the phone identifier is added to the customer
    And the customer detail is refreshed so the new identifier appears

  Scenario: Verify adding an identifier with no value is blocked
    Given I have opened the Add identifier dialog for a customer
    When I add without entering a value
    Then I am asked to enter an identifier value
    And no identifier is added

  Scenario: Verify adding an identifier already in use shows a friendly error
    Given I have opened the Add identifier dialog for a customer
    When I add an identifier that is already registered
    Then I see a friendly message that the identifier is already registered
    And the customer detail is not refreshed

  # ── Access lock (login / transactions) ────────────────────────────
  Scenario: Verify locking a customer's login asks for confirmation first
    Given I am viewing an active customer
    When I choose to lock the customer's login
    Then I am asked to confirm before anything is applied

  Scenario: Verify confirming a login lock applies it immediately
    Given I am viewing an active customer
    When I choose to lock the customer's login and confirm
    Then the customer's login is locked immediately and I see a confirmation

  Scenario: Verify a failed access change shows the reason and keeps the dialog open
    Given I am viewing an active customer
    When I confirm a login lock and the change fails
    Then I see the failure reason and the confirm dialog stays open

  # ── PIN reset ─────────────────────────────────────────────────────
  Scenario: Verify a PIN reset asks for confirmation before anything changes
    Given I am viewing a customer
    When I choose to reset the customer's PIN
    Then I am asked to confirm before the PIN is changed

  Scenario: Verify a PIN reset can be triggered for a customer and reveals the new PIN
    Given I am viewing a customer
    When I confirm resetting the customer's PIN
    Then a fresh PIN is generated and shown so I can read it back

  Scenario: Verify a failed PIN reset shows the reason
    Given I am viewing a customer
    When I confirm a PIN reset and it fails
    Then I see the failure reason and no new PIN is revealed

  # ── Clearing a PIN lockout ────────────────────────────────────────
  Scenario: Verify unlocking a customer asks for confirmation first
    Given I am viewing a locked-out customer
    When I choose to unlock the customer
    Then I am asked to confirm before the lockout is cleared

  Scenario: Verify confirming an unlock clears the customer's PIN lockout
    Given I am viewing a locked-out customer
    When I confirm unlocking the customer
    Then the PIN lockout is cleared and I see a confirmation

  Scenario: Verify a failed unlock shows the reason
    Given I am viewing a locked-out customer
    When I confirm an unlock and it fails
    Then I see the failure reason

  # ── Verifying an account number ───────────────────────────────────
  Scenario: Verify an admin can mark an account number verified
    Given I am viewing a customer with an unverified account number
    When I verify the account number identifier
    Then the identifier is marked verified and the customer detail is refreshed

  Scenario: Verify a rejected verification shows the reason
    Given I am viewing a customer with an identifier that cannot be verified this way
    When I try to verify it
    Then I see the reason and the customer detail is not refreshed
