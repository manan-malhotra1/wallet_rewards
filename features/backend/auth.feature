Feature: Administrator and partner authentication
  As a platform operator
  I want administrator sign-ins and partner API requests to be verified rigorously
  So that only legitimate, authorised callers can act on the platform

  Background:
    Given the platform trusts a known set of administrator sign-in keys
    And partners hold API keys with shared signing secrets
    And every request is checked before any action is taken

  Scenario: Verify an administrator action is rejected without a sign-in
    Given an administrator has not signed in
    When they try to run a privileged action
    Then the request is refused and they are asked to sign in

  Scenario: Verify an administrator without the right role is refused
    Given an administrator is signed in without the required role
    When they try to run a privileged action
    Then the request is refused as not permitted

  Scenario: Verify a platform administrator can perform a privileged action
    Given a platform administrator is signed in
    When they run a privileged action
    Then the action is carried out and a result is returned

  Scenario: Verify a finance reviewer can view pending items
    Given a finance reviewer is signed in
    When they open the list of pending items
    Then they can see the list

  Scenario: Verify an administrator with no role cannot view pending items
    Given an administrator is signed in with no roles at all
    When they open the list of pending items
    Then the request is refused as not permitted

  Scenario: Verify an expired administrator sign-in is rejected
    Given an administrator's sign-in has expired
    When they try to run a privileged action
    Then the request is refused and they are asked to sign in again

  Scenario: Verify a malformed administrator sign-in is rejected safely
    Given an administrator presents a meaningless sign-in credential
    When they try to run a privileged action
    Then the request is refused cleanly without an internal error

  Scenario: Verify a correctly signed partner request is accepted for its business
    Given a partner signs a request with their valid API key
    When the request arrives
    Then it is accepted and attributed to the partner's business

  Scenario: Verify a request using an unknown API key is rejected
    Given a request quotes an API key that does not exist
    When the request arrives
    Then it is rejected without revealing whether the key exists

  Scenario: Verify a request using a revoked API key is rejected
    Given a partner's API key has been revoked
    When they send a correctly signed request
    Then it is rejected

  Scenario: Verify a partner request with a tampered body is rejected
    Given a partner's request body was altered after it was signed
    When the request arrives
    Then it is rejected

  Scenario: Verify an expired partner request is rejected as a replay
    Given a partner request was signed longer ago than the allowed window
    When the request arrives
    Then it is rejected as a possible replay

  Scenario: Verify a partner request with a malformed signature is rejected
    Given a partner request carries a signature that is not well formed
    When the request arrives
    Then it is rejected as malformed

  Scenario: Verify a new API key starts active and unused
    Given an administrator creates a new API key
    When the key is stored
    Then it is active and has never been used

  Scenario: Verify two API keys cannot share the same public identifier
    Given one API key already uses a public identifier
    When another key tries to reuse the same identifier
    Then the second key is rejected

  Scenario: Verify API keys are kept separate per business
    Given two businesses each hold their own API keys
    When one business's keys are listed
    Then only that business's keys are returned

  Scenario: Verify an API key is rate-limited after too many calls
    Given an API key has reached its allowed number of calls
    When it makes another call
    Then the call is blocked with a hint on when to retry

  Scenario: Verify one API key hitting its limit does not affect another
    Given one API key has used up its allowance
    When a different API key makes a call
    Then that call is still allowed

  Scenario: Verify a correctly signed request passes verification
    Given a request is signed with the correct secret and current time
    When the signature is checked
    Then it passes verification

  Scenario: Verify a recently signed request is still accepted
    Given a request was signed a short time ago within the allowed window
    When the signature is checked
    Then it is still accepted

  Scenario: Verify a request signed too long ago is rejected
    Given a request was signed longer ago than the allowed window
    When the signature is checked
    Then it is rejected

  Scenario: Verify a request signed too far in the future is rejected
    Given a request is timestamped too far in the future
    When the signature is checked
    Then it is rejected

  Scenario: Verify a request whose body was altered is rejected
    Given a request body was changed after it was signed
    When the signature is checked
    Then it is rejected

  Scenario: Verify a request signed with the wrong secret is rejected
    Given a request was signed with the wrong shared secret
    When the signature is checked
    Then it is rejected

  Scenario: Verify a request missing its signature is rejected as malformed
    Given a request has no signature value
    When the signature is checked
    Then it is rejected as malformed

  Scenario: Verify a request missing its signing time is rejected as malformed
    Given a request has no signing time
    When the signature is checked
    Then it is rejected as malformed

  Scenario: Verify a request with an invalid signing time is rejected as malformed
    Given a request's signing time is not a valid value
    When the signature is checked
    Then it is rejected as malformed

  Scenario: Verify a request stays valid during a secret rotation
    Given a request carries signatures for both the old and new secret
    When the signature is checked during rotation
    Then it is accepted because one signature matches

  Scenario: Verify a signature is accepted regardless of letter case
    Given a request's signature uses upper-case letters
    When the signature is checked
    Then it is accepted

  Scenario: Verify unknown extra signature fields do not break verification
    Given a request's signature includes unfamiliar extra fields
    When the signature is checked
    Then the extra fields are ignored and it is accepted

  Scenario: Verify a standard sign-in header is read correctly
    Given a standard administrator sign-in header
    When it is read
    Then the sign-in token is extracted correctly

  Scenario: Verify a missing sign-in header is rejected
    Given no administrator sign-in header is present
    When it is read
    Then the request is rejected

  Scenario: Verify a sign-in header using the wrong scheme is rejected
    Given an administrator sign-in header uses an unsupported scheme
    When it is read
    Then the request is rejected

  Scenario: Verify a sign-in header with no token is rejected
    Given an administrator sign-in header carries no token
    When it is read
    Then the request is rejected

  Scenario: Verify a sign-in header scheme is accepted regardless of letter case
    Given an administrator sign-in header uses a differently cased scheme name
    When it is read
    Then the sign-in token is still extracted

  Scenario: Verify a valid administrator sign-in is accepted
    Given a genuine administrator sign-in token
    When it is validated
    Then the administrator's details are trusted

  Scenario: Verify an unsigned administrator token is rejected
    Given an administrator token that claims to need no signature
    When it is validated
    Then it is rejected

  Scenario: Verify an administrator token altered after signing is rejected
    Given an administrator token was changed after it was signed
    When it is validated
    Then it is rejected

  Scenario: Verify an administrator token signed by an untrusted key is rejected
    Given an administrator token signed by a key the platform does not trust
    When it is validated
    Then it is rejected

  Scenario: Verify an administrator token signed with an unknown key is rejected
    Given an administrator token references a signing key the platform does not know
    When it is validated
    Then it is rejected

  Scenario: Verify an expired administrator token is rejected
    Given an administrator token whose validity has lapsed
    When it is validated
    Then it is rejected

  Scenario: Verify an administrator token from an untrusted issuer is rejected
    Given an administrator token issued by an untrusted authority
    When it is validated
    Then it is rejected

  Scenario: Verify a stored API key secret can be recovered but is never kept in the clear
    Given a partner API key secret is stored encrypted
    When the platform needs the secret to verify a request
    Then it can recover the original secret even though it was never kept in the clear

  Scenario: Verify two identical secrets are stored as different ciphertexts
    Given two API keys happen to share the same secret value
    When each secret is stored
    Then their stored forms differ so equal secrets cannot be matched

  Scenario: Verify a new sign-in session is tracked for the user
    Given a user signs in and a session is created
    When the session is recorded
    Then it appears in the user's list of active sessions

  Scenario: Verify signing out clears the user's session
    Given a user has an active session
    When they sign out
    Then the session ends and is removed from their active sessions

  Scenario: Verify an administrator can end all of a user's sessions at once
    Given a user has several active sessions
    When an administrator ends all of the user's sessions
    Then every session is ended and the number ended is reported

  Scenario: Verify ending sessions for a user with none is harmless
    Given a user has no active sessions
    When an administrator ends all of the user's sessions
    Then nothing happens and no error occurs

  Scenario: Verify an active session stays revocable as it is used
    Given a user keeps using an active session
    When the session is refreshed by use
    Then it remains revocable by an administrator later

  Scenario: Verify ending one user's sessions leaves other users signed in
    Given two different users each have an active session
    When one user's sessions are ended
    Then the other user's session remains active
