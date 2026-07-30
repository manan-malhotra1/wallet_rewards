Feature: Services catalog admin
  As an administrator managing the service catalog, I can add a new service with
  an immutable code, and I am protected from a malformed code or a silent
  failure. Each scenario maps one-to-one to a Vitest interaction test
  co-located with create-service-dialog.tsx.

  Background:
    Given I am an administrator on the Services screen

  Scenario: Verify an admin can add a new service to the catalog
    Given I open the new service dialog
    When I enter a valid code and a display name and create the service
    Then the service is created with exactly that code and name
    And the dialog closes

  Scenario: Verify a service with a malformed code is blocked
    Given I open the new service dialog
    When I enter a code with spaces and capitals and create the service
    Then I am told the code must be lowercase letters, numbers, and underscores
    And nothing is sent to the backend

  Scenario: Verify a rejected service creation shows the error to the admin
    Given I open the new service dialog
    And the backend will reject a duplicate code
    When I enter a valid code and a display name and create the service
    Then the returned error code and reason are shown
    And the dialog stays open so I can adjust and retry
