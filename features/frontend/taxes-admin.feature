Feature: Tax config admin
  As an administrator setting tax rates, I can propose a per-currency tax config
  through the maker-checker pipeline, and I am protected from an invalid rate or
  a silent failure. Each scenario maps one-to-one to a Vitest interaction test
  co-located with create-tax-dialog.tsx.

  Background:
    Given I am an administrator on the Taxes screen
    And a currency is available

  Scenario: Verify an admin can propose tax rates for a currency
    Given I open the new tax config dialog
    When I enter the fee and commission tax rates, mark the fee tax inclusive, and propose the change
    Then the tax config is proposed for approval with those rates and the inclusive flag
    And the dialog closes

  Scenario: Verify a tax proposal with an invalid rate is rejected with a reason
    Given I open the new tax config dialog
    And the backend will reject an out-of-range rate
    When I enter an invalid tax rate and propose the change
    Then I am told the rate is out of range
    And the dialog stays open so I can correct it

  Scenario: Verify a rejected tax proposal shows the error to the admin
    Given I open the new tax config dialog
    And the backend is unavailable
    When I enter a tax rate and propose the change
    Then the returned error code and reason are shown
    And the dialog stays open so I can retry
