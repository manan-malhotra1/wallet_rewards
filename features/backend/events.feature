Feature: Event ingestion and sources
  As a rewards platform operator
  I want external activity events to be ingested safely and only once
  So that customers earn rewards from trusted sources without duplicates

  Background:
    Given a tenant is configured on the platform
    And a customer exists in that tenant

  Scenario: Verify an event from an unregistered source is rejected and logged
    Given an event arrives quoting a source that was never registered
    When the platform processes the event
    Then the event is rejected
    And no reward is issued

  Scenario: Verify an event whose source belongs to another tenant is rejected
    Given a source is registered for one tenant
    And an event arrives claiming that source but naming a different tenant
    When the platform processes the event
    Then the event is rejected

  Scenario: Verify the same event processed twice only takes effect once
    Given a registered source and a qualifying reward rule
    When the same event is delivered twice
    Then the reward is granted only on the first delivery
    And the repeat delivery is treated as a duplicate

  Scenario: Verify a first-time reward is granted only on the first qualifying event
    Given a first-time reward rule for an activity
    When the customer performs that activity twice
    Then a reward is granted the first time
    And no reward is granted the second time

  Scenario: Verify a milestone reward is granted at the threshold and the count then restarts
    Given a milestone reward rule that fires every third qualifying activity
    When the customer performs the activity six times
    Then a reward is granted on the third and the sixth activity
    And no reward is granted on the other activities

  Scenario: Verify a reward tied to one activity does not trigger on a different activity
    Given a reward rule bound to one activity type
    When the customer performs a different activity
    Then no reward is granted

  Scenario: Verify every received event is recorded in the ingestion log
    Given a registered source
    When an event is received
    Then the platform keeps a record of that event and its outcome

  Scenario: Verify the developer ingest route is hidden when the simulator is switched off
    Given the developer simulator is switched off
    When a request is sent to the developer ingest route
    Then the route is not available

  Scenario: Verify a correctly signed simulated event is accepted and processed
    Given the developer simulator is switched on
    And a registered source with a signing secret
    When a simulated event carrying a valid signature is submitted
    Then the event is accepted and processed

  Scenario: Verify a simulated event with an invalid signature is rejected
    Given the developer simulator is switched on
    And a registered source with a signing secret
    When a simulated event carrying a bad signature is submitted
    Then the event is rejected

  Scenario: Verify an event source signing secret is stored encrypted, never in plain text
    When an event source is registered with a signing secret
    Then the stored secret is encrypted and cannot be read as plain text

  Scenario: Verify the developer Kafka produce route is hidden when the simulator is switched off
    Given the developer simulator is switched off
    When a request is sent to the developer Kafka produce route
    Then the route is not available

  Scenario: Verify a simulated Kafka event without a user is rejected
    Given the developer simulator is switched on
    When a simulated Kafka event is submitted without naming a customer
    Then the request is rejected

  Scenario: Verify a new event source can be registered and is immediately active
    When an operator registers a new event source
    Then the source is created and immediately active

  Scenario: Verify an event source key cannot be registered twice
    Given an event source key is already registered
    When an operator registers another source with the same key
    Then the registration is rejected as a conflict

  Scenario: Verify an event source cannot be registered for an unknown tenant
    When an operator registers a source for a tenant that does not exist
    Then the registration is rejected
