Feature: Rewards rules engine
  As a rewards program administrator
  I want to configure reward rules and see how customers earn from them
  So that the right customers are rewarded for the right behaviour, and never twice

  Background:
    Given a business with an active rewards program
    And an administrator signed in to manage that business's rules
    And customers whose activity can earn rewards

  # --- Creating reward rules ---

  Scenario: Verify an admin can create a first-time reward rule that goes live
    When the admin creates a first-time reward rule for funding
    Then the rule is saved and immediately active

  Scenario: Verify an admin can create a milestone reward rule
    When the admin creates a milestone rule that rewards after a number of transactions
    Then the rule is saved with its target count

  Scenario: Verify a milestone rule is rejected when its target count is missing
    When the admin tries to create a milestone rule without a target count
    Then the rule is rejected as invalid

  Scenario: Verify a first-time rule is rejected when it sets a target count
    When the admin tries to create a first-time rule with a target count
    Then the rule is rejected as invalid

  Scenario: Verify a rule cannot be created for an unknown business
    When the admin tries to create a rule for a business that does not exist
    Then the request is not found

  Scenario: Verify a business only sees its own reward rules
    Given each of two businesses has created a rule
    When the admin lists one business's rules
    Then only that business's rule is returned

  # --- Composite (combined-condition) rule setup ---

  Scenario: Verify an admin can create a combined-condition reward rule
    When the admin creates a rule that combines a funding and a sending condition
    Then the rule is saved with both conditions

  Scenario: Verify a combined-condition rule is rejected when its and-or-or choice is missing
    When the admin tries to create a combined-condition rule without saying whether all or any condition must be met
    Then the rule is rejected as invalid

  Scenario: Verify a combined-condition rule is rejected when it has fewer than two conditions
    When the admin tries to create a combined-condition rule with only one condition
    Then the rule is rejected as invalid

  Scenario: Verify a simple rule is rejected when it carries combined-condition settings
    When the admin tries to create a simple milestone rule that also lists combined conditions
    Then the rule is rejected as invalid

  Scenario: Verify a simple rule is rejected when it carries an and-or-or choice
    When the admin tries to create a simple first-time rule that also sets an all-or-any choice
    Then the rule is rejected as invalid

  # --- Managing reward rules ---

  Scenario: Verify an admin can view the full details of a reward rule
    Given the admin has created a reward rule
    When the admin opens that rule
    Then all of the rule's details are shown

  Scenario: Verify a business cannot view another business's reward rule
    Given one business has created a reward rule
    When an administrator of a different business tries to open that rule
    Then the rule is not found

  Scenario: Verify an admin can change a reward rule's payout amount
    Given the admin has created a reward rule
    When the admin changes the rule's payout amount
    Then the new payout amount is saved

  Scenario: Verify a reward rule cannot be updated to a zero or negative payout
    Given the admin has created a reward rule
    When the admin tries to set the payout to zero
    Then the change is rejected as invalid

  Scenario: Verify a business cannot change another business's reward rule
    Given one business has created a reward rule
    When an administrator of a different business tries to change that rule
    Then the rule is not found

  Scenario: Verify an admin can deactivate a reward rule
    Given the admin has created a reward rule
    When the admin deactivates the rule
    Then the rule is kept on record but marked inactive

  Scenario: Verify deactivating an already-inactive rule succeeds
    Given the admin has already deactivated a reward rule
    When the admin deactivates the same rule again
    Then the request succeeds with no further change

  Scenario: Verify a business cannot deactivate another business's reward rule
    Given one business has created a reward rule
    When an administrator of a different business tries to deactivate that rule
    Then the rule is not found

  # --- Budget coverage on rules ---

  Scenario: Verify a rule with no reward budget reports no budget
    Given a rule with no reward budget configured
    When the admin views the rule's budget coverage
    Then it shows that no budget applies

  Scenario: Verify a rule covered only by a business-wide budget reports it
    Given a business-wide reward budget is in place
    When the admin views a rule's budget coverage
    Then it shows the rule is covered by the business-wide budget only

  Scenario: Verify a rule with its own budget reports it
    Given a rule has its own dedicated reward budget
    When the admin views the rule's budget coverage
    Then it shows the rule is covered by its own budget only

  Scenario: Verify a rule reports both its own and the business-wide budget
    Given both a business-wide budget and a rule-specific budget are in place
    When the admin views the rule's budget coverage
    Then it shows the rule is covered by both budgets

  Scenario: Verify the rules overview shows each rule's budget coverage
    Given several rules with different budget coverage
    When the admin views the rules overview
    Then each rule's budget coverage is shown alongside it

  # --- Rule performance reporting ---

  Scenario: Verify a rule that has never rewarded anyone shows zero activity
    Given a rule that has never rewarded a customer
    When the admin views the rule's performance
    Then it shows no rewards and no customers reached

  Scenario: Verify a rule's performance shows how many rewards and distinct customers it reached
    Given a rule that has rewarded several customers, some more than once
    When the admin views the rule's performance
    Then it shows the total rewards, the number of distinct customers, and the total payout

  Scenario: Verify performance for an unknown rule is not found
    When the admin requests performance for a rule that does not exist
    Then the request is not found

  Scenario: Verify a business cannot view another business's rule performance
    Given one business has created a rule
    When an administrator of a different business requests that rule's performance
    Then the request is not found

  Scenario: Verify a badly formed rule reference is rejected
    When the admin requests performance using a badly formed rule reference
    Then the request is rejected as invalid

  Scenario: Verify the performance overview reports every rule including those that never fired
    Given a business has active rules and rules that never rewarded anyone
    When the admin views the performance overview
    Then every rule appears, with the quiet ones showing zero activity

  Scenario: Verify a business's performance overview excludes other businesses' rules
    Given two businesses each have their own rules
    When the admin views one business's performance overview
    Then only that business's rules appear

  Scenario: Verify a business with no rules gets an empty performance overview
    Given a business that has created no rules
    When the admin views the performance overview
    Then the overview is empty

  # --- Value-based rewards ---

  Scenario: Verify a customer earns a reward when a transaction meets the minimum amount
    Given a value-based rule that rewards transactions at or above a minimum amount
    When a customer makes a transaction at or above that amount
    Then the customer earns the reward

  Scenario: Verify a customer earns no reward when a transaction is below the minimum amount
    Given a value-based rule that rewards transactions at or above a minimum amount
    When a customer makes a transaction below that amount
    Then the customer earns nothing

  Scenario: Verify a value-based rule stops rewarding a customer after its trigger limit
    Given a value-based rule that stops after two rewards per customer
    When a customer makes three qualifying transactions
    Then the customer is rewarded for the first two only

  Scenario: Verify a value-based rule is rejected when its minimum amount is missing
    When the admin tries to create a value-based rule without a minimum amount
    Then the rule is rejected as invalid

  # --- Streak rewards ---

  Scenario: Verify a customer earns a streak reward after several consecutive days of activity
    Given a rule that rewards a three-day activity streak
    When a customer is active on three consecutive days
    Then the customer earns the reward on the third day

  Scenario: Verify a customer's streak resets when they miss a day
    Given a rule that rewards a three-day activity streak
    When a customer is active, then misses a day, then resumes
    Then the streak restarts and the reward is never earned

  Scenario: Verify multiple actions on the same day advance a streak only once
    Given a rule that rewards a two-day activity streak
    When a customer acts twice on the first day and once on the next day
    Then the streak advances one step per day and the reward is earned on the second day

  Scenario: Verify a customer can earn a streak reward again after it resets
    Given a rule that rewards a three-day activity streak and then resets
    When a customer keeps a daily streak over six days
    Then the customer earns the reward on the third day and again on the sixth

  Scenario: Verify a streak rule is rejected when its length is missing
    When the admin tries to create a streak rule without a streak length
    Then the rule is rejected as invalid

  Scenario: Verify a customer's streak count grows with each qualifying day
    Given a rule that tracks an activity streak
    When a customer is active on three consecutive days
    Then the customer's streak count reads three

  # --- Combined-condition rewards ---

  Scenario: Verify a customer earns a reward when every condition of a combined rule is met
    Given a rule that requires both a funding and a sending transaction
    When a customer completes both a funding and a sending transaction
    Then the customer earns the reward

  Scenario: Verify a customer earns no reward when only some conditions of a combined rule are met
    Given a rule that requires both a funding and a sending transaction
    When a customer completes only the funding transaction
    Then the customer earns nothing

  Scenario: Verify small transactions do not count toward a combined rule's spending condition
    Given a combined rule that requires two funding transactions above a minimum amount
    When a customer makes one qualifying funding transaction and one below the minimum
    Then the spending condition is not yet met and no reward is earned
    When the customer makes a second qualifying funding transaction
    Then the condition is met and the customer earns the reward

  Scenario: Verify a customer earns a reward when any one condition of a combined rule is met
    Given a rule that rewards either a funding or a sending transaction
    When a customer completes just the funding transaction
    Then the customer earns the reward

  Scenario: Verify a customer earns no reward when no condition of a combined rule is met
    Given a rule that rewards either two funding or two sending transactions
    When a customer makes only one of each
    Then the customer earns nothing

  Scenario: Verify a repeated event never rewards a combined rule twice
    Given a combined rule the customer has satisfied
    When the same triggering event is processed twice
    Then the customer is rewarded only once

  Scenario: Verify a customer can earn a resetting combined-rule reward again in a new cycle
    Given a combined rule that resets after it rewards
    When a customer satisfies it, then satisfies it again with fresh activity
    Then the customer is rewarded both times

  Scenario: Verify a one-time combined-rule reward is earned only once
    Given a combined rule that does not reset after it rewards
    When a customer keeps satisfying it
    Then the customer is rewarded only the first time

  Scenario: Verify a combined rule stops rewarding a customer after its trigger limit
    Given a combined rule that stops after one reward per customer
    When a customer satisfies it a second time with fresh activity
    Then the customer is not rewarded again

  Scenario: Verify a combined-rule reward skips a customer outside the targeted segment
    Given a combined rule targeted at a specific customer segment
    When a customer outside that segment satisfies the conditions
    Then the customer earns nothing

  Scenario: Verify an active bonus multiplier increases a combined rule's reward
    Given a combined rule and an active bonus multiplier
    When a customer satisfies the rule while the multiplier is active
    Then the customer's reward is scaled up by the multiplier

  # --- Campaign rewards ---

  Scenario: Verify a customer earns a campaign reward during the campaign period
    Given a campaign rule running for a set period
    When a customer qualifies during the campaign period
    Then the customer earns the campaign reward

  Scenario: Verify a customer earns no campaign reward before the campaign starts
    Given a campaign rule with a future or ongoing period
    When a customer's activity falls before the campaign started
    Then the customer earns nothing

  Scenario: Verify a customer earns a campaign reward only once
    Given a campaign rule running for a set period
    When a customer qualifies twice during the period
    Then the customer earns the reward only once

  Scenario: Verify a campaign rule is rejected when its end date is missing
    When the admin tries to create a campaign rule with a start date but no end date
    Then the rule is rejected as invalid

  Scenario: Verify a campaign rule is rejected when it ends before it starts
    When the admin tries to create a campaign rule whose end date is before its start date
    Then the rule is rejected as invalid
