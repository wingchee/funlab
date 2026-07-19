# Member Links Final Review Fix Report

## Findings addressed

- `admin_promote_membership` now assigns a newly generated, unique
  `balance_access_token` in the same transaction that assigns the member code.
- `admin_remove_membership` now clears `balance_access_token` with the member
  code and phone number, revoking the former public bearer URL.

## Regression coverage

Added `test_membership_transitions_rotate_private_balance_link`, which verifies
the complete lifecycle for an existing account:

1. Promotion issues a token and its public balance URL succeeds.
2. Membership removal clears the stored token and the former URL returns 404.
3. Re-promotion creates a distinct token and its new public balance URL succeeds.

## Test-driven evidence

Before the router change, the new focused test failed because promotion left
`balance_access_token` as `None`. After the change, that focused test passed.

## Final verification

- `python3 -m pytest tests/test_memberships.py tests/test_unified_accounts.py -v`
  completed with 37 passed.
- `git diff --check` completed with no whitespace errors.
