# Admin-Managed Member Links Design

## Goal

Replace public member registration with admin-created members that share a private balance URL and branded QR image.

## Scope

- Remove the registration UI and disable the public registration endpoint.
- Add a dedicated Add Member view in the staff Membership dashboard.
- Require only name and phone when an admin creates a member.
- Give every membership-bearing user an unguessable public-balance access token and a read-only balance URL.
- Let admins generate a downloadable QR PNG for the balance URL, with the Funlab logo centered in the image.
- Preserve the existing Member ID QR flow used for staff table check-in.

## Data Model and Migration

Add nullable, unique `balance_access_token` to `users`, with a unique index. The migration backfills a cryptographically random token for every existing user with a `member_code`; non-member accounts remain null.

An admin-created member is still a row in `users` because packages, table visits, and timers already reference that table. The creation endpoint generates an internal unique placeholder email and a random password hash, neither of which is returned to the member or used for public access. It also generates the Member ID and balance token atomically. Name and normalized unique phone are the only admin-supplied required fields.

## API

- `POST /api/members` is admin-only and accepts `{name, phone}`. It returns the usual member summary plus `balance_access_token` for the admin response.
- `GET /api/members/public/{balance_access_token}` is unauthenticated. It returns only name, Member ID, remaining seconds, and package summaries; it never returns phone, email, notes, visits, account IDs, or admin flags. Missing, revoked, inactive, or non-member tokens return 404.
- `POST /api/members/{id}/balance-link/regenerate` is admin-only. It replaces the token, immediately invalidating the old URL and QR code.
- `GET /api/members/{id}/balance-qr?origin=<current-origin>` is admin-only. It validates an HTTP(S) origin and returns a QR PNG containing `<origin>/member/<token>`.
- The existing `GET /api/members/{id}/qr` and `/api/members/me/qr` endpoints continue to encode Member IDs for check-in and are not repurposed.

## Frontend

The login modal is sign-in only; it has no registration toggle or registration request. Existing accounts can still sign in.

The staff Membership dashboard has an Add Member action that opens a dedicated in-page Add Member view with Name and Phone fields. After creation it selects the new member and shows the balance URL, Copy Link, Download QR, and Regenerate Link controls.

The public client route `/member/<token>` renders without a session. It fetches the public balance endpoint and displays the member name, Member ID, remaining hours, and package names/hours. It shows a neutral unavailable state for an invalid, inactive, or regenerated link.

## QR Branding

Copy the existing Funlab logo asset into the backend image assets. Generate balance-link QR codes with high error correction, reserve a centered white logo plate, and overlay the Funlab logo at no more than 20% of the QR width. The final PNG must remain decodable and must encode the exact public balance URL.

## Error Handling and Security

Phone uniqueness conflicts return 409. Member creation rolls back on any conflict. Tokens are generated with `secrets.token_urlsafe`, stored only server-side, and never derived from names, phones, IDs, or timestamps. The public route deliberately acts as a bearer link: anyone with it can view the limited balance data, while regeneration revokes it.

## Verification

Tests cover public-registration removal, admin creation with name/phone only, migration backfill and uniqueness, public payload minimization, token revocation, inactive-member denial, QR URL decoding/logo output, and frontend route/form behavior. Run the full suite and rebuild the Docker stack.
