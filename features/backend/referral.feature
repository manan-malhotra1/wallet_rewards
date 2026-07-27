Feature: Referral rewards
  As a rewards program administrator
  I want to reward customers who invite their friends, and the friends who join
  So that the program grows through trusted word of mouth without ever paying twice

  Background:
    Given a business with an active rewards program
    And an administrator who can configure referral rules
    And customers who each receive their own referral code

  # --- Referral rule setup validation ---

  Scenario: Verify a referral rule is rejected when its trigger is missing
    When the admin tries to create a referral rule without saying what triggers the reward
    Then the rule is rejected as invalid

  Scenario: Verify a transaction-count referral rule is rejected when the required count is missing
    When the admin tries to create a referral rule that rewards after a number of transactions but gives no number
    Then the rule is rejected as invalid

  Scenario: Verify referral settings are rejected on a non-referral rule
    When the admin tries to put referral settings on a rule that is not a referral rule
    Then the rule is rejected as invalid

  Scenario: Verify a well-formed signup referral rule is accepted
    When the admin creates a signup referral rule with a reward for the new customer
    Then the rule is accepted

  # --- Referral rewards at signup ---

  Scenario: Verify entering a valid referral code at signup rewards the referrer
    Given an existing customer with a referral code
    And a referral rule that rewards the referrer at signup
    When a new customer signs up using that referral code
    Then a referral is recorded and the referrer is rewarded

  Scenario: Verify a customer who signs up without a code still gets their own referral code
    When a customer signs up without entering a referral code
    Then no referral is recorded for them
    And they still receive their own referral code to share

  Scenario: Verify signing up with an unrecognized referral code is rejected
    When a customer tries to sign up with a referral code that belongs to no one
    Then the signup is rejected

  Scenario: Verify a customer cannot refer themselves
    When a customer tries to sign up using their own referral code
    Then the signup is rejected as a self-referral

  Scenario: Verify a signup cashback referral opens wallets and pays both sides
    Given a signup referral rule that pays cashback to both sides
    And a referrer with a referral code and no wallet yet
    When a brand-new customer signs up using that code
    Then both customers get a wallet opened and receive their cashback

  Scenario: Verify a signup still succeeds when the referral reward cannot be paid
    Given an existing customer with a referral code
    And the reward payout is temporarily unavailable
    When a new customer signs up using that code
    Then the new customer's signup still succeeds
    And the referral is kept pending to be rewarded later

  # --- Referral reward payouts ---

  Scenario: Verify a referral rewards both the referrer and the new customer with points
    Given a referral rule that awards points to both sides
    And a pending referral linking a new customer to their referrer
    When the referral is rewarded
    Then both the referrer and the new customer receive their points

  Scenario: Verify a cashback referral pays both the referrer and the new customer into their wallets
    Given a referral rule that awards cashback to both sides
    And a pending referral linking a new customer to their referrer
    When the referral is rewarded
    Then both wallets are credited and the funding float is drawn down by the total

  Scenario: Verify a referral never pays either side twice
    Given a referral rule that awards points to both sides
    When the referral reward is processed more than once
    Then each side is still paid only once

  Scenario: Verify a cashback referral reward lands even when it exceeds the wallet limit
    Given a customer whose wallet has a low balance limit
    When a cashback referral reward larger than that limit is paid
    Then the reward still lands in the wallet

  # --- Referral rewards after enough transactions ---

  Scenario: Verify a referral rewards the referrer only after enough new-customer transactions
    Given a referral rule that rewards once the new customer completes three transactions
    And a pending referral linking a new customer to their referrer
    When the new customer has completed fewer than three transactions
    Then no one is rewarded yet
    When the new customer completes the third transaction
    Then the referrer is rewarded and the referral is marked rewarded
    And re-processing it does not pay anyone again
