Feature: Managing partner API keys
  As a platform administrator
  I want to create, list, and revoke API keys for partner businesses
  So that partners can access the API securely and their access stays under my control

  Background:
    Given I am signed in as a platform administrator
    And a business is set up on the platform
    And API key secrets are only ever stored encrypted

  Scenario: Verify a new API key's secret is shown only once and never stored in the clear
    Given I create an API key for the business
    When the key is returned to me
    Then the secret is shown once and is never stored or listed in the clear

  Scenario: Verify an API key can be created without linking it to a merchant
    Given I create an API key without naming a merchant
    When the key is created
    Then it exists with no merchant attached

  Scenario: Verify an API key can be linked to a merchant and the change is audited
    Given the business has a merchant
    When I create an API key linked to that merchant
    Then the key is tied to the merchant and the change is recorded in the audit trail

  Scenario: Verify an API key cannot be linked to a non-merchant user
    Given the business has an ordinary customer who is not a merchant
    When I try to create an API key linked to that customer
    Then the request is rejected and no key is created

  Scenario: Verify an API key cannot be linked to an unknown user
    Given I name a user that does not exist
    When I try to create an API key linked to that user
    Then the request is rejected and no key is created

  Scenario: Verify an API key cannot be linked to a merchant from another business
    Given a merchant belongs to a different business
    When I try to create an API key linked to that merchant
    Then the request is rejected and no key is created

  Scenario: Verify creating an API key requires an administrator to sign in
    Given I am not signed in
    When I try to create an API key
    Then the request is refused and I am asked to sign in

  Scenario: Verify only a platform administrator can create an API key
    Given I am signed in without platform administrator rights
    When I try to create an API key
    Then the request is refused as not permitted

  Scenario: Verify an API key cannot be created for an unknown business
    Given I name a business that does not exist
    When I try to create an API key for it
    Then the request is refused

  Scenario: Verify one business only sees its own API keys
    Given two businesses each have their own API keys
    When I list one business's keys
    Then only that business's keys are shown

  Scenario: Verify an administrator can revoke an API key only within their own business
    Given a business has an active API key
    When I revoke it under the correct business
    Then the key becomes revoked
    But revoking it under a different business is refused
