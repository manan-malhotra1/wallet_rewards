Feature: Configuration change governance (maker-checker)
  As a platform administrator
  I want every pricing, commission, tax, limit and step-up config change to go through a
  four-eyes approval workflow with full history and tenant isolation
  So that no single admin can change money-affecting configuration unchecked

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And config changes are governed by a maker-checker approval workflow

  Scenario: Verify the review screen shows the names of the admins who proposed and approved a change.
    Given a config change has been proposed by one admin and approved by another
    When I open the review screen for that change
    Then it shows the names of both the proposing and the approving admin

  Scenario: Verify adjacent fee bands that leave no gap are accepted.
    When I propose a fee schedule whose bands are adjacent with no gap between them
    Then the proposal is accepted

  Scenario: Verify fee bands that overlap on a shared amount are rejected.
    When I propose a fee schedule whose bands overlap on a shared amount
    Then the proposal is rejected

  Scenario: Verify a config created during setup still shows a starting baseline version.
    Given a config was created during initial setup with no change history
    When I view its version history
    Then a synthesized starting baseline version is shown

  Scenario: Verify a multi-band fee schedule created during setup shows its full baseline version.
    Given a multi-band fee schedule was created during setup with no change history
    When I view its version history
    Then the baseline version shows all of its bands

  Scenario: Verify a config still shows a baseline version even when its values predate current rules.
    Given a live config whose values predate the current validation rules
    When I view its version history
    Then a baseline version is still shown

  Scenario: Verify a workflow-changed config shows its real history without a duplicate baseline.
    Given a config has been changed through the approval workflow
    When I view its version history
    Then its real history is shown without a synthesized duplicate baseline

  Scenario: Verify one tenant cannot see another tenant's config history.
    Given another tenant has a config with history
    When I request that config's history
    Then I am refused as if the config does not exist

  Scenario: Verify a request for an unknown config's history is rejected cleanly.
    When I request the history of a config that does not exist
    Then I am refused with a not-found response

  Scenario: Verify deleting a fee schedule removes all its bands while other schedules remain.
    Given two fee schedules exist
    When a delete of one schedule is approved
    Then all of its bands are removed and the other schedule remains

  Scenario: Verify deleting a commission schedule removes every band in it.
    Given a commission schedule with several bands exists
    When a delete of that schedule is approved
    Then every band in it is removed

  Scenario: Verify deleting one limit removes only that limit and leaves others in place.
    Given several limits exist
    When a delete of one limit is approved
    Then only that limit is removed and the others remain

  Scenario: Verify deleting a tax config removes exactly that config.
    Given a tax config exists
    When a delete of that tax config is approved
    Then exactly that one config is removed

  Scenario: Verify deleting a fee schedule is recorded in the audit trail with the removed bands.
    When a delete of a fee schedule is approved
    Then a single deleted-audit entry is recorded summarising the removed bands

  Scenario: Verify approving a delete for a config that no longer exists is rejected cleanly.
    Given a delete proposal targets a config that has since been removed
    When the delete is approved
    Then it is rejected with a not-found response

  Scenario: Verify a failed delete leaves the config fully intact and still awaiting approval.
    Given a delete proposal that fails when applied
    When the delete is attempted
    Then the config remains fully intact and still awaiting approval

  Scenario: Verify a config's history shows every version oldest-first, ending at the current one.
    Given a config has several versions
    When I view its history
    Then every version is listed oldest-first, ending at the current version

  Scenario: Verify a config's history shows only its own versions, not another config's.
    Given two configs each have their own versions
    When I view one config's history
    Then only that config's versions are shown

  Scenario: Verify a history request for an unknown config is rejected cleanly.
    When I request the history of a config that does not exist
    Then I am refused with a not-found response

  Scenario: Verify the version-history view loads its own list, not a single request.
    When I open the version-history view
    Then it loads the list of versions and is not shadowed by a single-request route

  Scenario: Verify version history cannot be viewed without signing in.
    Given I am not signed in
    When I request a config's version history
    Then I am refused with an unauthorized response

  Scenario: Verify an admin without the right role cannot view version history.
    Given I am signed in without the required role
    When I request a config's version history
    Then I am refused with a forbidden response

  Scenario: Verify one tenant cannot view another tenant's config history.
    Given another tenant has a config with history
    When I request that config's version history
    Then I see nothing belonging to the other tenant

  Scenario: Verify a proposed config change stays pending and does not take effect until approved.
    When I propose a config change
    Then it stays pending and the live config is not written until it is approved

  Scenario: Verify a config change goes live once a second admin approves it.
    Given I have proposed a config change
    When a second admin approves it
    Then the change goes live

  Scenario: Verify the admin who proposed a change cannot approve their own change.
    Given I have proposed a config change
    When I try to approve my own change
    Then the approval is forbidden

  Scenario: Verify only an admin with approver rights can approve a config change.
    Given a config change is pending
    When an admin without approver rights tries to approve it
    Then the approval is forbidden

  Scenario: Verify a change sent back for edits applies the revised version once re-approved.
    Given a proposed change was sent back for edits and revised
    When the revised change is re-approved
    Then the revised version is applied

  Scenario: Verify only the admin who proposed a change may edit it after changes are requested.
    Given a proposed change has had changes requested
    When an admin other than the proposer tries to edit it
    Then the edit is forbidden

  Scenario: Verify requesting changes requires a comment explaining why.
    When an approver requests changes without a comment
    Then the request is rejected until a comment is provided

  Scenario: Verify a withdrawn change stays withdrawn and can no longer be approved.
    Given a proposed change has been withdrawn
    When someone tries to approve it
    Then it remains withdrawn and cannot be approved

  Scenario: Verify wallet-balance limits can also be changed through the approval workflow.
    When I propose a change to a wallet-balance limit
    And a second admin approves it
    Then the wallet-balance limit is updated

  Scenario: Verify a config change with invalid values is rejected cleanly.
    When I propose a config change with invalid values
    Then the proposal is rejected with a validation error

  Scenario: Verify one tenant cannot see another tenant's config change request.
    Given another tenant has a pending config change request
    When I request that change
    Then I am refused as if it does not exist

  Scenario: Verify a tiered fee schedule with several bands can be proposed.
    When I propose a tiered fee schedule with several bands
    Then the proposal is accepted

  Scenario: Verify a fee schedule with overlapping bands is rejected.
    When I propose a fee schedule with overlapping bands
    Then the proposal is rejected

  Scenario: Verify a fee schedule whose bands cover different scopes is rejected.
    When I propose a fee schedule whose bands cover different scopes
    Then the proposal is rejected

  Scenario: Verify approving a tiered fee schedule creates every band.
    Given a tiered fee schedule has been proposed
    When it is approved
    Then every band in it is created

  Scenario: Verify a single-band fee proposal still applies correctly.
    Given a single-band fee proposal
    When it is approved
    Then the single band is applied correctly

  Scenario: Verify a tiered commission schedule can be proposed and applied.
    When I propose a tiered commission schedule
    And it is approved
    Then every band in the commission schedule is applied

  Scenario: Verify the config-request list can be filtered to a single config type.
    Given change requests exist for several config types
    When I filter the config-request list to one config type
    Then only requests of that config type are shown

  Scenario: Verify a second edit is blocked while one is already awaiting approval for that config.
    Given an edit for a config is already awaiting approval
    When I propose a second edit for the same config
    Then it is blocked as a conflict

  Scenario: Verify a second create proposal is blocked while one is already pending for that scope.
    Given a create proposal for a scope is already pending
    When I propose a second create for the same scope
    Then it is blocked as a conflict

  Scenario: Verify a delete is blocked while an edit is already pending for the same config.
    Given an edit for a config is already pending
    When I propose a delete for the same config
    Then it is blocked as a conflict

  Scenario: Verify a new proposal is blocked while an earlier one is still awaiting the maker's edits.
    Given an earlier proposal is awaiting the maker's edits
    When I make a new proposal for the same config
    Then it is blocked as a conflict

  Scenario: Verify withdrawing a pending change frees the config for a new proposal.
    Given a pending change is withdrawn
    When I propose a new change for the same config
    Then the new proposal succeeds

  Scenario: Verify approving a pending change frees the config for a new proposal.
    Given a pending change is approved
    When I propose a new change for the same config
    Then the new proposal succeeds

  Scenario: Verify a pending change on one config does not block changes to a different config.
    Given a pending change exists on one config
    When I propose a change to a different config
    Then the new proposal is allowed

  Scenario: Verify a revised edit cannot be redirected to a different config than it named.
    Given a proposed edit named a specific config
    When the revised edit tries to point at a different config
    Then the revision is rejected

  Scenario: Verify a same-scope revised edit applies to the config it named.
    Given a proposed edit named a specific config
    When a same-scope revised edit is approved
    Then it applies to the config it named

  Scenario: Verify a revised edit carrying another tenant's data is rejected.
    Given a proposed edit is revised to carry another tenant's band
    When the revised edit is submitted
    Then it is rejected

  Scenario: Verify a revised edit with invalid values is rejected before it is saved.
    When a proposed edit is revised with invalid values
    Then the revision is rejected before it is saved

  Scenario: Verify a revised step-up threshold cannot be redirected to a different scope.
    Given a proposed step-up threshold named a specific scope
    When the revised threshold tries to point at a different scope
    Then the revision is rejected

  Scenario: Verify proposing a change records its original version as the first revision.
    When I propose a config change
    Then its original version is recorded as the first revision

  Scenario: Verify editing a change adds a new revision and both are kept in order.
    Given a change has an original revision
    When I edit the change
    Then a second revision is added and both are kept in order

  Scenario: Verify resubmitting and approving a change add no new revisions.
    Given a revised change exists
    When it is resubmitted and approved
    Then no new revision snapshots are added

  Scenario: Verify a delete proposal records a revision with no config values.
    When I propose a delete
    Then a revision is recorded with a null payload carrying no config values

  Scenario: Verify a new step-up threshold only takes effect once approved.
    When I propose a new step-up threshold
    Then no policy is written until the change is approved

  Scenario: Verify an approved edit updates the step-up threshold.
    Given a step-up threshold edit has been proposed
    When it is approved
    Then the step-up threshold is updated

  Scenario: Verify a step-up edit cannot be redirected to a different scope than it named.
    Given a step-up edit named a specific scope
    When it tries to point at a different scope
    Then the edit is rejected

  Scenario: Verify an approved delete removes the step-up threshold.
    Given a step-up threshold delete has been proposed
    When it is approved
    Then the step-up threshold is removed

  Scenario: Verify the admin who proposed a step-up change cannot approve their own change.
    Given I have proposed a step-up change
    When I try to approve my own change
    Then the approval is forbidden

  Scenario: Verify only a platform admin can propose a step-up change.
    Given I am signed in without the platform administrator role
    When I try to propose a step-up change
    Then the proposal is forbidden

  Scenario: Verify only an approver can approve a step-up change.
    Given a step-up change is pending
    When an admin without approver rights tries to approve it
    Then the approval is forbidden

  Scenario: Verify a second step-up change is blocked while one is already pending for the same scope.
    Given a step-up change for a scope is already pending
    When I propose a second step-up change for the same scope
    Then it is blocked as a conflict

  Scenario: Verify pending step-up changes on different scopes do not block each other.
    Given a pending step-up change exists on one scope
    When I propose a step-up change for a different scope
    Then the new proposal is allowed

  Scenario: Verify a negative step-up threshold is rejected.
    When I propose a step-up change with a negative threshold
    Then the proposal is rejected

  Scenario: Verify a step-up change missing a required field is rejected.
    When I propose a step-up change missing a required field
    Then the proposal is rejected

  Scenario: Verify a non-p2p step-up threshold can be created and later edited.
    When I propose a step-up threshold for a non-peer-transfer type
    Then it can be created and later edited without a scope mismatch

  Scenario: Verify every step-up transaction type the system provisions can be configured.
    Given the system provisions a set of guarded step-up transaction types
    When I check the configurable step-up types
    Then every provisioned guarded type can be configured

  Scenario: Verify every step-up transaction type can be created and edited through approval.
    When I propose and approve a step-up threshold for each guarded transaction type
    Then each type can be created and edited through the approval workflow

  Scenario: Verify an edit that does not say which config to change is rejected cleanly.
    When I propose an edit without naming which config to change
    Then it is rejected with a validation error

  Scenario: Verify an edit pointing at a config that does not exist is rejected cleanly.
    When I propose an edit pointing at a config that does not exist
    Then it is rejected with a not-found response

  Scenario: Verify an edit with no new values is rejected cleanly.
    When I propose an edit with no new values
    Then it is rejected with a validation error

  Scenario: Verify editing a limit updates its value and leaves a single config.
    Given a limit config exists
    When an edit to it is approved
    Then its value is updated and a single config remains

  Scenario: Verify a proposed edit records its original version as the first revision.
    When I propose an edit
    Then its original version is recorded as the first revision

  Scenario: Verify editing a fee schedule replaces it with exactly the new bands.
    Given a fee schedule exists
    When an edit to it is approved
    Then it is replaced with exactly the new set of bands

  Scenario: Verify editing a tax config updates its rate and leaves a single config.
    Given a tax config exists
    When an edit to it is approved
    Then its rate is updated and a single config remains

  Scenario: Verify a failed edit leaves the original config intact and still awaiting approval.
    Given an edit proposal that fails when applied
    When the edit is attempted
    Then the original config remains intact and still awaiting approval

  Scenario: Verify an edit cannot be redirected to a different config than it named.
    Given an edit named a specific config
    When it tries to point at a different config
    Then the edit is rejected while a matching-scope edit succeeds

  Scenario: Verify an edit sent back for changes applies its revised value once re-approved.
    Given an edit was sent back for changes and revised
    When the revised edit is re-approved
    Then its revised value is applied
