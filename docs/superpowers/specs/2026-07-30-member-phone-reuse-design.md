# Member Phone Reuse Design

## Goal

Allow staff to add a member using a phone number held by a deactivated member account, while preserving the old account's records.

## Staff flow

When the Add Member form submits a phone that belongs to a deactivated, non-archived member, the API returns the matched account summary instead of a generic duplicate-phone error. The form presents three choices:

1. Restore old account — reactivate the existing member and retain its member ID, package balance, visit history, and account identity.
2. Create new account — permanently archive the existing account, release its phone number, then create a new member using the submitted name and phone.
3. Cancel — leave the form unchanged.

Active accounts continue to reject duplicate phones without offering these choices.

## Data and API behavior

Add a non-null permanent-archive flag on `users`, defaulting to false. A permanently archived account remains inactive, has its balance link revoked, and has its phone cleared so the number can be reused. It remains stored with its historical packages, visits, and table logs.

The restore action is available only to inactive, non-archived members. It sets `is_active` to true and ensures the account has a private balance token. The create-new action permanently archives the matched account and then creates a fresh member through the existing creation rules.

Admin search and check-in continue to return active members only. Permanently archived accounts cannot be restored through this flow.

## Safety and testing

All actions require admin authorization. Phone normalization and uniqueness remain enforced. Tests cover restoring a deactivated account, creating a new account after permanently archiving the old account, active duplicate rejection, and the frontend prompt choices.
