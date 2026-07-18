# Profile account settings design

## Goal

Give each signed-in account a self-service Profile page for changing its sign-in
email address or password without exposing these controls in the member or
administrator management areas.

## User experience

- Add **Profile** to the authenticated account popover in the site header and
  mobile navigation.
- The page follows the existing FunLab visual language: pale pink grid
  background, white bordered cards, Space Grotesk typography, and the
  pink-to-blue primary gradient.
- The email card displays the current account email in a read-only field,
  followed by fields for the new email and current password. Its button updates
  only the email address.
- The password card contains current password, new password, and confirmation
  fields. Its button updates only the password.
- Both cards require the current password. Each shows its own submitting state,
  inline/form-level error, and success notification. A successful email change
  replaces the email held in the client session immediately.
- The page is responsive: a single readable column on small screens and the
  same forms and navigation entry points on desktop and mobile.

## Backend contract

Provide one authenticated endpoint in `backend/routers/auth.py`:

`PUT /api/auth/profile`

The request accepts optional `email` and `new_password` fields plus required
`current_password`. Exactly one change is permitted per request; the frontend
uses the endpoint separately from each card. The endpoint:

1. verifies the authenticated user’s current password;
2. normalizes and validates an email update, rejecting an email already used by
   another account with a clear 409 response;
3. validates a password update, including a minimum eight-character password
   and a matching confirmation in the client;
4. persists the permitted change and returns `serialize_account(user)`.

The endpoint never returns password material. Existing administrator member
editing remains unchanged and does not become the self-service profile path.

## Frontend structure

- Add a `ProfilePage` component to `frontend/index.html` alongside the existing
  page components.
- Add a `profile` page state and route it through the root page switch, guarded
  so only signed-in users can access it.
- Extend `Navbar` and `MobileNavDrawer` with the Profile action.
- On save, call the profile endpoint with `apiFetch`, replace the in-memory user
  with `storeAccountSession(response, token)`, clear the applicable form, and
  use the existing notification system for feedback.

## Validation and errors

- Client validation blocks empty values, invalid email syntax, a new email equal
  to the current email, passwords shorter than eight characters, and mismatched
  new-password confirmation.
- Server validation is authoritative and protects against stale clients and
  duplicate emails.
- Incorrect current password receives a generic, non-revealing error; client
  fields remain intact other than password values, which are cleared after a
  successful save.

## Tests

- Backend tests cover valid email changes, valid password changes, rejection of
  incorrect current password, duplicate email, malformed email, and short
  password.
- Frontend safety tests assert the Profile menu entry, page controls, and use
  of the authenticated profile endpoint without placing password fields in
  local storage.
- Run the targeted Python test suite and the project’s frontend safety tests.
