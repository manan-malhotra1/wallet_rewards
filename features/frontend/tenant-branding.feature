Feature: Tenant branding — admin theme customization
  As a platform administrator
  I want to set a tenant's two brand colours and icon with a live preview
  So that the whole admin app re-themes to the tenant's brand before I commit

  Scenario: Verify the form opens seeded with the tenant's current brand colours
    Given I am a platform admin on the tenants page
    And a tenant already has a custom accent and light colour
    When I open its "Customize theme" dialog
    Then the accent and light hex fields show the tenant's current colours

  Scenario: Verify changing the accent updates the live preview swatches
    Given I have opened a tenant's "Customize theme" dialog
    When I change the accent colour
    Then the brand-scale preview swatches repaint to the new palette

  Scenario: Verify an invalid hex blocks saving
    Given I have opened a tenant's "Customize theme" dialog
    When I enter an accent value that is not a valid 6-digit hex
    Then the save button is disabled and no save is attempted

  Scenario: Verify a valid save calls the branding action with the entered values
    Given I have opened a tenant's "Customize theme" dialog
    When I enter a valid accent colour and an http(s) icon URL and save
    Then the branding action is called with the tenant id and the entered accent, light, and icon URL

  Scenario: Verify a server error surfaces in the dialog
    Given I have opened a tenant's "Customize theme" dialog
    When I save and the backend rejects the change
    Then the dialog shows the returned error code and message
