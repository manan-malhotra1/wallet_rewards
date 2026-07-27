Feature: Users & identity
  As a platform administrator running the wallet
  I want to create customers, manage how they sign in, and control access to their accounts
  So that the right people can transact safely and no one can reach another business's customers

  Background:
    Given I am signed in to the admin portal as a platform administrator
    And my business has customers registered on the platform

  # --- Creating a customer ---

  Scenario: Verify an admin can create a customer with a phone number
    When I create a customer with a phone number
    Then the customer is created and active
    And their phone number is saved in a standard format

  Scenario: Verify creating a customer under an unknown tenant is rejected
    When I try to create a customer for a business that does not exist
    Then the request is refused as not found

  Scenario: Verify creating a customer with no identifier is rejected
    When I try to create a customer without any phone, email, or account number
    Then the request is refused as invalid

  Scenario: Verify creating a customer with an unknown identifier kind is rejected
    When I try to create a customer with an identifier of an unrecognised kind
    Then the request is refused as invalid

  Scenario: Verify a phone number already registered in the tenant cannot be reused
    Given a customer already exists with a given phone number
    When I try to create another customer with the same phone number
    Then the request is refused because the number is already in use

  Scenario: Verify the same phone number can be registered in a different tenant
    Given a customer exists with a phone number in one business
    When I create a customer with the same phone number in another business
    Then both customers are created as separate people

  Scenario: Verify a customer can be created with profile details
    When I create a customer and include their name and date of birth
    Then the customer is created with the profile details saved

  Scenario: Verify creating a customer requires signing in
    Given I am not signed in
    When I try to create a customer
    Then I am refused because I am not signed in

  # --- Customer types and hierarchy ---

  Scenario: Verify a new customer is a consumer by default
    When I create a customer without saying what type they are
    Then the customer is a consumer with no parent above them

  Scenario: Verify a super agent can be created
    When I create a super agent
    Then the super agent is created with no parent above them

  Scenario: Verify an agent can be created without a parent
    When I create an agent without naming a parent
    Then the agent is created with no parent above them

  Scenario: Verify an agent can be created under a super agent
    Given a super agent already exists
    When I create an agent under that super agent
    Then the agent is created beneath the super agent

  Scenario: Verify a merchant can be created under a head merchant
    Given a head merchant already exists
    When I create a merchant under that head merchant
    Then the merchant is created beneath the head merchant

  Scenario: Verify an agent cannot be placed under a consumer
    Given a consumer already exists
    When I try to create an agent under that consumer
    Then the request is refused because the parent is not allowed

  Scenario: Verify a consumer cannot be given a parent
    Given a super agent already exists
    When I try to create a consumer under that super agent
    Then the request is refused because a consumer cannot have a parent

  Scenario: Verify a customer cannot be placed under a parent in another tenant
    Given a super agent exists in another business
    When I try to create an agent under that foreign super agent
    Then the request is refused because the parent is in another business

  Scenario: Verify a customer cannot be placed under a parent that does not exist
    When I try to create an agent under a parent that does not exist
    Then the request is refused because the parent cannot be found

  Scenario: Verify creating a customer with an unknown type is rejected
    When I try to create a customer of an unrecognised type
    Then the request is refused as invalid

  Scenario: Verify a customer's type and parent show on their profile
    Given an agent exists beneath a super agent
    When I open the agent's profile
    Then I see their type and the parent above them

  Scenario: Verify a customer's parent is shown by their full name
    Given an agent sits beneath a super agent who has a full name on file
    When I open the agent's profile
    Then the parent is shown by their full name

  Scenario: Verify a customer's parent is shown by their phone number when they have no profile
    Given an agent sits beneath a super agent who has no name on file
    When I open the agent's profile
    Then the parent is shown by their phone number

  Scenario: Verify a top-level customer shows no parent name
    Given a super agent with no parent above them
    When I open their profile
    Then no parent is shown

  # --- Changing a customer's type ---

  Scenario: Verify a customer can be promoted to a super agent
    Given an ordinary customer exists
    When I change the customer into a super agent
    Then the customer becomes a super agent

  Scenario: Verify a customer can become an agent under a super agent
    Given a customer and a super agent exist
    When I change the customer into an agent under the super agent
    Then the customer becomes an agent beneath the super agent

  Scenario: Verify an agent cannot be placed under an incompatible parent
    Given a customer and a consumer exist
    When I try to change the customer into an agent under the consumer
    Then the request is refused because the parent is not allowed

  Scenario: Verify a top-level customer cannot be given a parent
    Given a customer and a super agent exist
    When I try to change the customer into a consumer while naming a parent
    Then the request is refused because a top-level type cannot have a parent

  Scenario: Verify a customer cannot be made their own parent
    Given a super agent exists
    When I try to change the customer into an agent under themselves
    Then the request is refused as invalid

  Scenario: Verify changing a customer's type requires a reason
    Given a customer exists
    When I try to change their type without giving a reason
    Then the request is refused as invalid

  Scenario: Verify changing to an unknown customer type is rejected
    Given a customer exists
    When I try to change them to an unrecognised type
    Then the request is refused as invalid

  Scenario: Verify changing a customer's type requires signing in
    Given I am not signed in
    When I try to change a customer's type
    Then I am refused because I am not signed in

  Scenario: Verify only a platform administrator can change a customer's type
    Given I am signed in without administrator rights
    When I try to change a customer's type
    Then I am refused because I lack permission

  Scenario: Verify an admin cannot change the type of a customer in another tenant
    Given a customer exists in another business
    When I try to change that customer's type from my business
    Then the request is refused as not found

  Scenario: Verify changing the type of a customer who does not exist is rejected
    When I try to change the type of a customer that does not exist
    Then the request is refused as not found

  Scenario: Verify repeating the same type change makes no further recorded change
    Given a customer has already been changed to a super agent
    When I change them to a super agent again
    Then nothing further is recorded in the audit trail

  # --- Adding an identifier ---

  Scenario: Verify an admin can add an account number to an existing customer
    Given a customer exists
    When I add an account number to the customer
    Then the account number is added but not yet verified

  Scenario: Verify an added phone number and email are tidied into a standard format
    Given a customer exists
    When I add a phone number and an email to the customer
    Then the phone number and email are saved in a standard format

  Scenario: Verify an identifier already used by someone else in the tenant is rejected
    Given an account number already belongs to one customer
    When I try to add the same account number to a different customer
    Then the request is refused because the identifier is already in use
    And no duplicate identifier is created

  Scenario: Verify adding an identifier to a customer who does not exist is rejected
    When I try to add an identifier to a customer that does not exist
    Then the request is refused as not found

  Scenario: Verify an admin cannot add an identifier to a customer in another tenant
    Given a customer exists in another business
    When I try to add an identifier to that customer from my business
    Then the request is refused as not found

  Scenario: Verify only a platform administrator can add an identifier
    Given I am signed in without administrator rights
    When I try to add an identifier to a customer
    Then I am refused because I lack permission

  Scenario: Verify adding an identifier requires signing in
    Given I am not signed in
    When I try to add an identifier to a customer
    Then I am refused because I am not signed in

  Scenario: Verify a raw card number cannot be added as an identifier
    Given a customer exists
    When I try to add a raw card number as an identifier
    Then the request is refused as invalid

  Scenario: Verify an empty identifier is rejected
    Given a customer exists
    When I try to add an identifier with no value
    Then the request is refused as invalid

  Scenario: Verify adding an identifier is audited without recording the sensitive value
    Given a customer exists
    When I add an account number to the customer
    Then the action is recorded in the audit trail
    And the sensitive identifier value never appears in the audit record

  # --- Verifying an identifier ---

  Scenario: Verify an admin can mark a customer's account number as verified
    Given a customer has an unverified account number
    When I verify the account number
    Then the account number is marked as verified
    And the verification is recorded in the audit trail without the sensitive value

  Scenario: Verify a phone number cannot be manually marked as verified through this action
    Given a customer has a phone number
    When I try to manually verify the phone number
    Then the request is refused as not allowed for this identifier
    And the phone number stays unverified

  Scenario: Verify re-verifying an already-verified identifier makes no further change
    Given a customer's account number is already verified
    When I verify it again
    Then it stays verified
    And nothing further is recorded in the audit trail

  Scenario: Verify verifying an identifier that does not exist is rejected
    Given a customer exists
    When I try to verify an identifier that does not exist
    Then the request is refused as not found

  Scenario: Verify an identifier cannot be verified against the wrong customer
    Given an account number belongs to one customer
    When I try to verify it while naming a different customer
    Then the request is refused as not found

  Scenario: Verify an admin cannot verify an identifier in another tenant
    Given an identifier belongs to a customer in another business
    When I try to verify it from my business
    Then the request is refused as not found

  Scenario: Verify only a platform administrator can verify an identifier
    Given a customer has an account number
    And I am signed in without administrator rights
    When I try to verify the account number
    Then I am refused because I lack permission

  Scenario: Verify verifying an identifier requires signing in
    Given a customer has an account number
    And I am not signed in
    When I try to verify the account number
    Then I am refused because I am not signed in

  # --- Finding a customer by identifier ---

  Scenario: Verify a customer can be found by their phone number
    Given a customer is registered with a phone number
    When I look up that phone number
    Then I am shown which customer it belongs to

  Scenario: Verify looking up an unregistered identifier finds no customer
    When I look up an identifier that no one has registered
    Then no customer is found

  Scenario: Verify a customer cannot be found from another tenant
    Given a customer is registered in one business
    When I look up their identifier from another business
    Then no customer is found

  Scenario: Verify looking up a customer requires signing in
    Given I am not signed in
    When I try to look up a customer by identifier
    Then I am refused because I am not signed in

  # --- Customer display names ---

  Scenario: Verify a customer with a profile is shown by their full name
    Given a customer has a first and last name on file
    When I resolve their display name
    Then they are shown by their full name

  Scenario: Verify a customer with only a first name is shown by that name
    Given a customer has only a first name on file
    When I resolve their display name
    Then they are shown by that first name with no trailing space

  Scenario: Verify a customer with no profile is shown by their identifier
    Given a customer has no name on file but has a phone number
    When I resolve their display name
    Then they are shown by their phone number

  Scenario: Verify a customer's phone number is preferred over their email as a display name
    Given a customer has both a phone number and an email but no name
    When I resolve their display name
    Then they are shown by their phone number rather than their email

  Scenario: Verify a customer with no name and no identifier has no display name
    Given a customer has neither a name nor any identifier
    When I resolve their display name
    Then no display name is available for them

  Scenario: Verify a customer who does not exist has no display name
    When I resolve the display name of a customer that does not exist
    Then no display name is available for them

  Scenario: Verify a customer in another tenant has no display name here
    Given a customer exists in another business
    When I resolve their display name from my business
    Then no display name is available for them

  Scenario: Verify display names resolve correctly for many customers at once
    Given a mix of customers with full names, only identifiers, and no details
    When I resolve all their display names in one request
    Then each named customer is shown by their best available name
    And customers with no details are left out

  # --- Signing up: one-time code and PIN ---

  Scenario: Verify a customer can request a one-time code
    Given a customer wants to sign up with their phone number
    When they request a one-time code
    Then a code is sent to them

  Scenario: Verify requesting a code for a new phone starts a new customer account
    Given a phone number not yet on the platform
    When a one-time code is requested for it
    Then a new customer account is started for that number

  Scenario: Verify a customer cannot request another one-time code too soon
    Given a customer just requested a one-time code
    When they immediately request another code
    Then the second request is refused for asking too soon

  Scenario: Verify requesting a code under an unknown tenant is rejected
    When a one-time code is requested for a business that does not exist
    Then the request is refused as not found

  Scenario: Verify entering the correct one-time code lets the customer continue registration
    Given a customer has been sent a one-time code
    When they enter the correct code
    Then they may continue setting up their account

  Scenario: Verify a wrong one-time code is rejected
    Given a customer has been sent a one-time code
    When they enter the wrong code
    Then the code is refused

  Scenario: Verify a one-time code for a phone that never requested one is rejected
    When a code is entered for a phone number that never requested one
    Then the code is refused without revealing whether the number exists

  Scenario: Verify a one-time code cannot be used twice
    Given a customer has already used their one-time code
    When they try to use the same code again
    Then the code is refused

  Scenario: Verify a customer can set their PIN after verifying their code
    Given a customer has verified their one-time code
    When they choose a PIN
    Then their PIN is set

  Scenario: Verify a PIN cannot be set with an invalid registration token
    When a customer tries to set a PIN with an invalid registration token
    Then the request is refused

  Scenario: Verify a registration token can only set a PIN once
    Given a customer has already set their PIN with their registration token
    When they try to set a PIN again with the same token
    Then the request is refused

  Scenario: Verify a non-numeric PIN is rejected
    Given a customer has verified their one-time code
    When they try to set a PIN that is not all digits
    Then the request is refused as invalid

  Scenario: Verify a customer cannot set a PIN when one is already set
    Given a customer already has a PIN
    When they try to set a PIN again
    Then the request is refused because a PIN is already set

  # --- Signing in with a PIN ---

  Scenario: Verify a customer can sign in with their correct PIN
    Given a customer has set their PIN
    When they sign in with the correct PIN
    Then they are given an active session

  Scenario: Verify signing in with a wrong PIN is rejected
    Given a customer has set their PIN
    When they sign in with the wrong PIN
    Then they are refused

  Scenario: Verify a customer is locked out after too many wrong PIN attempts
    Given a customer has set their PIN
    When they enter the wrong PIN too many times in a row
    Then they are locked out
    And even the correct PIN is refused while locked

  Scenario: Verify signing in with an unknown phone number is rejected without revealing it exists
    When someone tries to sign in with a phone number that is not registered
    Then they are refused without revealing whether the number exists

  Scenario: Verify a customer who has not set a PIN cannot sign in with one
    Given a customer account exists but no PIN has been set
    When they try to sign in with a PIN
    Then they are refused because no PIN is set

  # --- Signing out ---

  Scenario: Verify signing out ends the customer's session
    Given a customer is signed in
    When they sign out
    Then their session no longer works

  Scenario: Verify signing out without an active session still succeeds
    Given no active session
    When a sign-out is requested
    Then it still succeeds

  # --- My wallet (customer view) ---

  Scenario: Verify a signed-in customer sees their own accounts
    Given a signed-in customer with a money wallet and a points wallet
    When they open their wallet
    Then they see their own accounts

  Scenario: Verify each recent transaction shows its fee, commission, and tax
    Given a signed-in customer with a recent transaction
    When they open their wallet
    Then each recent transaction shows its fee, commission, and tax

  Scenario: Verify each recent transaction shows its customer-facing reference
    Given a signed-in customer with a recent transaction
    When they open their wallet
    Then each recent transaction shows a customer-facing reference

  Scenario: Verify viewing the wallet requires signing in
    Given I am not signed in
    When I try to open a wallet
    Then I am refused because I am not signed in

  Scenario: Verify an invalid session cannot view the wallet
    Given I present an invalid session
    When I try to open a wallet
    Then I am refused because I am not signed in

  Scenario: Verify a customer never sees another customer's accounts
    Given another customer has accounts in the same business
    When a signed-in customer opens their own wallet
    Then they see only their own accounts and never the other customer's

  # --- Customer transaction history (admin view) ---

  Scenario: Verify viewing a customer's transactions requires signing in
    Given I am not signed in
    When I try to view a customer's transactions
    Then I am refused because I am not signed in

  Scenario: Verify an admin can see a customer's recent transactions
    Given a customer has been funded once
    When I view the customer's transactions
    Then I see the incoming funding transaction with its amount and currency

  Scenario: Verify viewing transactions for a customer who does not exist is rejected
    When I try to view the transactions of a customer that does not exist
    Then the request is refused as not found

  Scenario: Verify an admin cannot see the transactions of a customer in another tenant
    Given a customer with transactions exists in another business
    When I try to view their transactions from my business
    Then the request is refused as not found

  # --- Locking and unlocking access (admin) ---

  Scenario: Verify an admin can set a customer to active, login-locked, or transactions-locked
    Given a customer exists
    When I set the customer's access level
    Then the customer's account reflects the chosen access level

  Scenario: Verify locking a customer's login immediately ends their active session
    Given a customer is signed in
    When I lock the customer's login
    Then their active session stops working straight away

  Scenario: Verify blocking a customer's transactions still lets them stay signed in
    Given a customer is signed in
    When I block the customer's transactions
    Then they can still stay signed in and read their account

  Scenario: Verify only a platform administrator can change a customer's access
    Given I am signed in without administrator rights
    When I try to change a customer's access
    Then I am refused because I lack permission

  Scenario: Verify an unrecognised access level is rejected
    Given a customer exists
    When I try to set an unrecognised access level
    Then the request is refused as invalid

  Scenario: Verify locking a customer who does not exist is rejected
    When I try to lock a customer that does not exist
    Then the request is refused as not found

  Scenario: Verify an admin cannot lock a customer belonging to another tenant
    Given a customer exists in another business
    When I try to lock that customer from my business
    Then the request is refused as not found

  Scenario: Verify every access change is recorded in the audit trail
    Given a customer is signed in
    When I lock the customer's login
    Then the access change is recorded in the audit trail with the before and after state

  Scenario: Verify a customer's current access level shows on their profile
    Given a customer exists
    When I block the customer's transactions and open their profile
    Then their profile shows the transactions-locked access level

  # --- What a locked customer can and cannot do ---

  Scenario: Verify an active customer is allowed to transact
    Given an active customer
    When the account lock guard is checked
    Then the customer is allowed to transact

  Scenario: Verify a locked or suspended customer cannot transact
    Given a locked or suspended customer
    When the account lock guard is checked
    Then the customer is not allowed to transact

  Scenario: Verify a customer who does not exist cannot transact
    When the account lock guard is checked for a customer that does not exist
    Then the request is refused as not found

  Scenario: Verify a customer from another tenant cannot transact
    Given a customer exists in another business
    When the account lock guard is checked from my business
    Then the customer is treated as not found

  Scenario: Verify a suspended or closed customer cannot sign in
    Given a customer's account is suspended or closed
    When they try to sign in
    Then they are refused because the account is suspended

  Scenario: Verify a transactions-locked customer can still sign in to view their account
    Given a customer's transactions are locked
    When they sign in
    Then they are allowed in so they can view their account

  Scenario: Verify an active customer can sign in normally
    Given an active customer with a PIN
    When they sign in
    Then they are given an active session

  Scenario: Verify a locked customer cannot send money to another person
    Given a locked or suspended customer
    When they try to send money to another person
    Then the transfer is refused because they are blocked

  Scenario: Verify a locked customer cannot change their PIN
    Given a locked or suspended customer
    When they try to change their PIN
    Then the change is refused because they are blocked

  Scenario: Verify a locked customer cannot cash out
    Given a customer whose transactions are locked
    When they try to cash out
    Then the cash out is refused because they are blocked

  Scenario: Verify a retried request returns the original result even after the customer is locked
    Given a customer completed a PIN change and was then locked
    When the same PIN-change request is retried
    Then the original result is returned rather than being blocked

  # --- Admin PIN reset ---

  Scenario: Verify an admin can reset a customer's PIN and receive the new one
    Given a customer exists
    When I reset the customer's PIN
    Then a fresh PIN is issued and works for that customer

  Scenario: Verify resetting the PIN of a customer who does not exist is rejected
    When I try to reset the PIN of a customer that does not exist
    Then the request is refused as not found

  Scenario: Verify an admin cannot reset the PIN of a customer in another tenant
    Given a customer exists in another business
    When I try to reset their PIN from my business
    Then the request is refused as not found

  Scenario: Verify each PIN reset produces a freshly generated PIN
    Given a customer exists
    When I reset the customer's PIN twice
    Then each reset produces a freshly generated PIN

  # --- Admin unlock (PIN lockout) ---

  Scenario: Verify an admin can release a customer locked out by wrong PIN attempts
    Given a customer is locked out from too many wrong PIN attempts
    When I unlock the customer
    Then the customer is released and can try again immediately

  Scenario: Verify unlocking a customer who is not locked simply succeeds
    Given a customer who is not locked
    When I unlock the customer
    Then the request simply succeeds

  Scenario: Verify only a platform administrator can unlock a customer
    Given I am signed in without administrator rights
    When I try to unlock a customer
    Then I am refused because I lack permission

  Scenario: Verify unlocking a customer who does not exist is rejected
    When I try to unlock a customer that does not exist
    Then the request is refused as not found

  Scenario: Verify an admin cannot unlock a customer in another tenant
    Given a customer exists in another business
    When I try to unlock that customer from my business
    Then the request is refused as not found

  Scenario: Verify unlocking a customer is recorded in the audit trail
    Given a customer is locked out
    When I unlock the customer
    Then the unlock is recorded in the audit trail

  Scenario: Verify resetting a customer's PIN also releases an active lockout
    Given a customer is locked out from too many wrong PIN attempts
    When I reset the customer's PIN
    Then the lockout is also released

  Scenario: Verify a customer's lockout status and remaining time show on their profile
    Given a customer exists
    When I open their profile before and after they become locked
    Then their profile shows the lockout status and the time remaining

  # --- Sign-in start ---

  Scenario: Verify a returning customer is asked for their PIN
    Given a customer is already registered with a phone number
    When they start signing in with that phone number
    Then they are asked for their PIN

  Scenario: Verify a new phone number is routed to one-time-code registration without creating an account
    Given a phone number not yet on the platform
    When someone starts signing in with that number
    Then they are routed to one-time-code registration
    And no account or identifier is created

  Scenario: Verify a phone number is recognised regardless of spacing
    Given a customer is registered with a phone number
    When they start signing in with the same number formatted with spaces
    Then they are recognised and asked for their PIN

  Scenario: Verify a phone known in another tenant is treated as new here
    Given a phone number is registered only in another business
    When someone starts signing in with that number here
    Then they are routed to one-time-code registration as if new

  Scenario: Verify signing in against an unknown tenant is rejected
    When someone starts signing in against a business that does not exist
    Then the request is refused as not found

  Scenario: Verify a malformed phone number is rejected
    When someone starts signing in with a malformed phone number
    Then the request is refused as invalid

  Scenario: Verify signing in without a phone number is rejected
    When someone starts signing in without providing a phone number
    Then the request is refused as invalid

  # --- Allowed account statuses ---

  Scenario: Verify every allowed customer status can be saved
    When a customer is saved with each of the allowed statuses
    Then every allowed status is accepted

  Scenario: Verify an invalid customer status cannot be saved
    When a customer is saved with a status outside the allowed set
    Then the save is refused
