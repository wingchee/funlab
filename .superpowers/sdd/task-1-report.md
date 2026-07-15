# Task 1 Report — Hide Email from Membership Staff Workflows

## Scope completed

- Removed email from `MembershipPage` search copy, member-list fallback, selected-member detail display, profile form state, form input, effect dependencies, and update request body.
- Preserved account email storage and authentication paths outside the Membership staff UI.
- Added `test_membership_page_hides_email_from_staff_workflows` and updated the existing search-placeholder assertion.

## TDD evidence

- Red: `python3 -m pytest tests/test_frontend_ux_safety.py::test_membership_page_hides_email_from_staff_workflows -v` failed as expected because the staff Membership page still had the email-inclusive search placeholder.
- Green: `python3 -m pytest tests/test_frontend_ux_safety.py -v` passed: 19 passed.

## Docker verification

Attempted twice (once sandboxed and once with approved escalation):

```sh
docker compose up --build -d frontend && docker compose ps frontend && curl -fsS -o /dev/null -w 'frontend_http=%{http_code}\n' http://localhost/
```

Both attempts were blocked before build/run because Docker Desktop's daemon socket was unavailable at `unix:///Users/wingchee/.docker/run/docker.sock`. No frontend HTTP response could be obtained in this environment.

## Self-review

- `git diff --check` completed without whitespace errors.
- Reviewed the scoped diff: only the prescribed Membership email removals and frontend safety tests are included.

---

# Follow-up Fix — Restrict Membership Search to Name, Phone, and Member ID

## Scope

- Removed the `models.User.email.ilike(like)` predicate from `search_members` in `backend/routers/memberships.py`.
- Kept stored email addresses and all authentication/sign-in behavior unchanged.
- Updated existing search assertions to protect name, phone, and Member ID lookups only.
- Added `test_member_search_does_not_match_email_only_query` to prove an email-only lookup cannot return the matching member.

## TDD evidence

### Red

```sh
python3 -m pytest tests/test_memberships.py::MembershipTests::test_member_search_does_not_match_email_only_query -v
```

Result: `1 failed`. The assertion failed because `search_members(db, member.email)` returned the matching member (`AssertionError: 1 unexpectedly found in [1]`).

### Green

```sh
python3 -m pytest tests/test_memberships.py::MembershipTests::test_member_is_searchable_by_name_phone_or_code tests/test_memberships.py::MembershipTests::test_member_search_does_not_match_email_only_query tests/test_memberships.py::MembershipTests::test_staff_search_finds_admin_only_account_by_name -v
```

Result: `3 passed in 2.02s`.

```sh
python3 -m pytest tests/test_frontend_ux_safety.py -v
```

Result: `19 passed in 0.07s`.

## Additional verification

```sh
python3 -m pytest tests/test_memberships.py -v
```

Initial result: `25 passed, 2 failed`. One failure was the now-obsolete admin email-search assertion, which was updated as part of this scope. The other was `test_balance_qr_encodes_public_link_and_has_center_logo_plate`, which failed to decode its generated QR image.

```sh
python3 -m pytest tests/test_memberships.py::MembershipTests::test_balance_qr_encodes_public_link_and_has_center_logo_plate -v
```

Rerun result: `1 passed in 1.63s`; the QR failure was nondeterministic and unrelated to this search change.
