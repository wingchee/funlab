# Hide Email on the Membership Page

## Goal

Keep account email addresses out of the admin Membership page while preserving
existing account data and login behaviour.

## Scope

- Remove email from the member-search copy and search request.
- Never render email in member-list rows or selected-member details.
- Remove the email input from the Membership page's member-profile editor and
  omit email from its update request.
- Continue to use name, phone, and Member ID as the Membership page's visible
  and searchable identifiers.

## Out of Scope

- Database migrations or deletion of stored email addresses.
- Changes to login, account administration outside Membership, or backend
  authentication.

## Behaviour

Administrators can find members by name, phone, or Member ID. The list and
selected-member panel show member code and phone when available; account-only
users do not fall back to showing an email address. Editing a member updates
only the Membership page's remaining profile fields.

## Validation

Add a frontend safety test which asserts that the Membership-page source has no
email search copy, displayed-email fallback, email input, or email field in the
member-update payload. Run the targeted test, then rebuild the Docker frontend
and confirm the local site responds successfully.
