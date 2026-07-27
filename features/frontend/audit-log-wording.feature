Feature: Audit log wording
  As an administrator reviewing the audit log
  I want actions, statuses and changes phrased in plain language
  So that I can understand what happened without decoding raw codes

  Background:
    Given I am an administrator using the admin portal

  Scenario: Verify a known admin action reads as plain language in the audit log
    Given an audit entry for the action "pin.changed"
    When I read the entry in the audit log
    Then the action reads "PIN changed"

  Scenario: Verify an unrecognised action still shows as readable words, never a raw code
    Given an audit entry for an unknown action "widget.frobnicated"
    When I read the entry in the audit log
    Then the action reads "Widget frobnicated"
    And it contains no dots or underscores

  Scenario: Verify suspending a user is recorded as 'Login locked' in the audit log
    Given an access change moving a user from "active" to "suspended"
    When I read the entry in the audit log
    Then the action reads "Login locked"

  Scenario: Verify restoring a suspended user is recorded as 'Login access restored'
    Given an access change moving a user from "suspended" to "active"
    When I read the entry in the audit log
    Then the action reads "Login access restored"

  Scenario: Verify blocking a user's transactions is recorded as 'Transactions locked'
    Given an access change moving a user from "active" to "txn_locked"
    When I read the entry in the audit log
    Then the action reads "Transactions locked"

  Scenario: Verify a general access change reads as 'User access changed' when the before and after are unknown
    Given an access change with no before or after state
    When I read the entry in the audit log
    Then the action reads "User access changed"

  Scenario: Verify a transaction-locked account is shown as 'Transactions locked'
    Given an account with status "txn_locked"
    When I view the account status
    Then it reads "Transactions locked"

  Scenario: Verify an active account is shown as 'Active'
    Given an account with status "active"
    When I view the account status
    Then it reads "Active"

  Scenario: Verify an unrecognised account status is still shown as readable words
    Given an account with an unknown status "pending_review"
    When I view the account status
    Then it reads "Pending review"

  Scenario: Verify admin, user and system actors are named in plain language
    Given audit entries made by an admin, a user and the system
    When I view who performed each action
    Then they read "Admin", "User" and "System"

  Scenario: Verify the audit log shows where an action came from (admin portal or mobile app)
    Given audit entries originating from admin, user and system actors
    When I view where each action came from
    Then they read "Admin portal", "Mobile app" and "System"

  Scenario: Verify a change shows only the fields that actually changed
    Given a change where only the last name went from "Jones" to "Smith"
    When I view the change detail
    Then only the last name field is listed as changed from "Jones" to "Smith"

  Scenario: Verify a status change is shown in plain words on both the old and new values
    Given a status change from "active" to "txn_locked"
    When I view the change detail
    Then the old value reads "Active" and the new value reads "Transactions locked"

  Scenario: Verify true/false values are shown as Yes and No
    Given a change where a verified flag went from false to true
    When I view the change detail
    Then the old value reads "No" and the new value reads "Yes"

  Scenario: Verify a previously empty value is shown as a dash next to its readable field name
    Given a change where a first name was previously empty and is now "Bob"
    When I view the change detail
    Then the old value reads "—" and the new value reads "Bob"
    And the field is labelled "First name"
