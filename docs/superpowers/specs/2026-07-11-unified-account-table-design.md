# Unified Account Table Design

## Goal

Use `users` as the only account table for administrators and members. A person signs in with one password, receives one token type, and uses the same identity across the public site, Membership portal, saved patterns, table check-in, package balances, and administrative features.

## Production Assumptions

The production database currently contains `users` but no member records that must be preserved. Existing production email text, user rows, IDs, passwords, favorites, and `is_admin` values must survive byte-for-byte unchanged. Before applying the schema migration, deployment creates a SQLite backup and aborts if the backup fails.

Local member records and their package, visit, timer-assignment, and member-favorite test data do not need to be retained. The migration may remove and rebuild local-only membership tables and foreign keys to match the unified schema.

## Unified Identity Model

`users` remains the account table and gains these membership fields:

- `member_code`: nullable and unique when populated;
- `phone`: nullable and unique when populated;
- `is_active`: non-null, default `true`;
- `notes`: non-null, default empty string;
- `updated_at`: timestamp maintained on updates.

The existing `email`, `password_hash`, `name`, `is_admin`, and `created_at` fields remain. Administrator-only accounts may leave `member_code` and `phone` empty. A member account has `is_admin = false` and receives a generated Member ID and normalized phone number. An administrator may also have membership fields, allowing one account to carry both capabilities.

Application validation requires email, name, phone, and password when registering a member. Database nullability remains permissive for pre-existing administrator rows.

## Related Data

There is no `members` table or `Member` ORM model after migration. Membership-related records refer to `users.id`:

- `member_packages.member_id`;
- `member_visits.member_id`;
- `table_timers.active_member_id`;
- `table_time_logs.member_id`;
- `favorites.user_id`.

The existing column names containing `member_id` remain for API compatibility, but their foreign keys target `users.id`. Relationships resolve to `User`. Favorites return to one owner column, `user_id`; the temporary `favorites.member_id` branch is removed.

Only users with a populated `member_code` are valid membership principals for packages, visits, QR codes, and table attachment. Administrative authorization continues to depend solely on `is_admin`.

## Authentication

All accounts use the existing bcrypt password format and the existing JWT format. The separate PBKDF2 member password functions, HMAC member tokens, `pc_member_token`, and token-type switching are removed.

One login operation accepts an `identifier` plus password. It searches active users by:

1. normalized email;
2. normalized phone;
3. case-insensitive Member ID.

Successful login returns one JWT and a serialized account containing administrator and membership attributes. Admin-only accounts ordinarily sign in by email because phone and Member ID are optional. Inactive accounts cannot authenticate. Invalid credentials always produce one generic response.

Existing sessions are intentionally invalidated once during deployment by rotating `SECRET_KEY` after the database backup is verified. Everyone signs in again through the unified endpoint.

## Registration And Account Management

Public member registration creates a `User` with `is_admin = false`, a generated unique Member ID, normalized unique email and phone values, and a bcrypt password. Duplicate email, phone, or Member ID conflicts return HTTP 409 without creating a partial record.

Administrators continue to search and edit membership information. Editing a user may add membership fields to an administrator or change a member's details. Removing a Member ID from an account is rejected while packages, visits, or active table assignments reference that account.

The Membership portal and main sign-in popup use the same session. Signing out from either surface clears that session everywhere. Administrator navigation appears when `is_admin` is true; membership navigation and data appear when `member_code` is populated.

## Migration

Create a new Alembic revision after the current head. Its upgrade is deterministic for both production-style and current local schemas:

1. Add the optional membership columns to `users` when absent.
2. Detect normalized duplicate user emails and abort without rewriting any email text.
3. Preserve every existing production user ID, password hash, favorite, and `is_admin` value.
4. Drop local-only membership-dependent data in dependency order because the user approved discarding it.
5. Recreate membership tables with foreign keys to `users.id` and required uniqueness/index constraints.
6. Remove `favorites.member_id` and preserve existing `favorites.user_id` rows.
7. Remove the `members` table.
8. Seed missing table-timer rows without replacing existing timer state that does not reference discarded local members.

The migration must inspect tables and columns before changing them so it works against both the production database and developer databases that already contain the experimental member schema. Before schema changes, it must abort with an actionable message on normalized user-email collisions or any `NULL is_admin` value; it never guesses administrator permissions. It must run transactionally where SQLite permits and fail on backup/configuration problems.

Downgrade is intentionally unsupported once unified membership data exists because reconstructing two password identities would be lossy. Restoration uses the pre-migration SQLite backup.

## API Compatibility

Membership URLs may remain under `/api/members` to avoid unnecessary frontend churn, but their dependencies and queries use `User`. Responses may continue to expose `member_id`; its value equals the unified user's ID.

The old `/api/members/login` endpoint is removed. There is no compatibility alias, second credential check, or second token. The frontend calls only the canonical unified login endpoint.

## Error Handling And Safety

- Deployment stops if the database backup cannot be created or verified.
- Migration stops on duplicate normalized user emails.
- Migration stops on `NULL is_admin` values rather than converting them.
- Registration and edits rely on both application validation and database uniqueness.
- Admin-only accounts are not treated as members unless they have a Member ID.
- Membership operations reject inactive accounts and accounts without membership capability.
- Foreign-key enforcement is enabled during migration tests and application operation.
- No plaintext passwords or password hashes are logged.

## Testing And Verification

Migration tests cover a production-style database containing only existing users and favorites, plus a local schema containing disposable member tables. They prove user IDs, bcrypt hashes, admin flags, and user-owned favorites remain unchanged; membership tables point to `users`; and `members` no longer exists.

Authentication tests cover email, phone, and Member-ID login; generic invalid-credential errors; inactive accounts; one JWT type; and preserved administrator authorization. Registration tests cover required membership fields, normalized uniqueness, generated Member IDs, and bcrypt storage.

Membership tests cover packages, visits, QR codes, table attachment and settlement, account editing, and rejection of membership operations for admin-only users. Favorites tests cover the single `user_id` ownership path.

Frontend tests prove the main popup and Membership portal share one token, one account state, and one logout path. Final verification runs the full automated test suite, rebuilds the Docker stack against a disposable database, checks administrator and member journeys through localhost, and then repeats the critical login and Membership flows through the active Cloudflare tunnel.

## Deployment Sequence

1. Stop write traffic to the backend.
2. Create and verify a timestamped SQLite backup outside the database volume.
3. Generate and persist a new production `SECRET_KEY` once to invalidate old user and member sessions, then retain it on routine deployments.
4. Deploy the new backend image and run `alembic upgrade head` once.
5. Start one backend replica and verify health, admin login, member registration, and database foreign keys.
6. Start the remaining services and verify the frontend.
7. Retain the backup until the unified schema has been validated in production.
