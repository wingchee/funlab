# Unified Member Authentication Design

## Goal

Use one member account across the public FunLab site and the Membership page. Members register and sign in from the main-menu popup or Membership page and receive the same profile, Member ID, QR code, packages, visits, and saved patterns in either entry point.

## Scope

- Remove member creation from the staff Membership dashboard.
- Add member registration to the main-menu authentication popup.
- Require email, name, phone, password, and password confirmation for registration.
- Use the existing `Member` record as the customer identity everywhere.
- Keep existing administrator accounts and administrator authentication working.
- Preserve staff member search, QR scanning, package management, record editing, and table check-in.
- Preserve saved-pattern behavior for signed-in customers.

## Identity Model

`Member` becomes the source of truth for customer identity. It gains a normalized, unique email address. A member's existing phone, Member ID, package history, visit history, and QR code remain on the same record.

Administrator accounts remain in `User`. They are operational accounts and are not converted into members. The shared popup first authenticates a customer against the member system and retains an administrator path for existing admin credentials.

Member login accepts email, normalized phone number, or Member ID. Member registration rejects duplicate email addresses and duplicate normalized phone numbers. Password and password confirmation must match, and password storage continues to use the membership password hashing implementation.

## Saved Patterns

Favorites support either an administrator user or a member as their owner. Existing user favorites remain valid. New member favorites are stored against the member record, allowing a member authenticated through the main popup to save patterns without creating a parallel `User` account.

The favorites API resolves the bearer token as either an administrator/user token or a member token, then reads and writes favorites for that principal. A database constraint prevents duplicate favorites for the same member and pattern.

## Frontend Behavior

### Main-Menu Popup

The popup has `Sign In` and `Register` modes.

Sign In contains:

- Email, phone, or Member ID
- Password

Register contains:

- Email
- Name
- Phone
- Password
- Confirm password

Successful member authentication stores the member token as the active site session and the Membership tab immediately displays that same member profile. Existing administrator credentials remain accepted and produce the existing admin navigation and permissions.

### Membership Page

The member portal uses the same active member session as the main popup. Its registration form contains the same five required registration fields and the same validation. Signing in or registering there updates the global site session, so the navigation and saved-pattern features recognize the member without a second login.

The staff dashboard no longer displays or executes `Create Member`. Its empty selection message changes to instruct staff to select a member. Members create their own accounts through either registration form.

## API Contracts

`POST /members/register` accepts:

```json
{
  "email": "member@example.com",
  "name": "Member Name",
  "phone": "+60 12-345 6789",
  "password": "secret-password",
  "password_confirmation": "secret-password"
}
```

It returns a member token and serialized member profile. The profile includes email.

`POST /members/login` continues to accept `identifier` and `password`, with `identifier` expanded to email, phone, or Member ID.

The main popup calls the member endpoints for customer authentication. Administrator sign-in continues through `POST /auth/login` as a fallback when member authentication does not match.

## Data Migration

The migration adds nullable `members.email` first so existing members remain valid. A unique index is applied to populated normalized email values. Existing counter-created members without email cannot use portal login by email until an administrator supplies an email through record editing; they can continue using phone or Member ID if they already have a password.

Favorites gain a nullable `member_id` foreign key. Existing `user_id` ownership is retained and made compatible with member ownership. Each row must belong to exactly one supported principal in application behavior.

## Validation And Errors

- Registration requires every displayed field.
- Email is trimmed and compared case-insensitively.
- Phone is normalized to digits before uniqueness checks.
- Password confirmation mismatch is rejected before record creation.
- Duplicate email and phone errors are specific enough for the UI to display.
- Invalid credentials use a generic response that does not reveal whether an account exists.
- Inactive members cannot authenticate.
- Failed requests leave the current session unchanged.

## Testing

Backend tests cover registration requirements, password confirmation, email and phone uniqueness, normalized email login, phone/Member-ID login, member serialization, member-owned favorites, and preservation of user-owned favorites.

Frontend contract tests cover removal of staff member creation, both popup modes, all five registration fields, matching-password validation, member endpoint usage, administrator fallback, and shared member-session storage between the popup and Membership page.

The full test suite must pass. The running app is then checked through the active HTTPS tunnel at desktop and mobile viewport sizes, including registration, sign-in, Membership profile visibility, and staff-dashboard absence of Create Member.
