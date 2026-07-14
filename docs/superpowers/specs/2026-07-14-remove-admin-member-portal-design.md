# Remove Admin Member Portal Design

## Goal

Remove the Member Portal switcher and embedded portal view from the admin Membership page.

## Scope

- Admins see the staff Membership dashboard only.
- Remove the admin-only `membershipMode` state and the Staff Dashboard / Member Portal switcher.
- Preserve the Add Member view, member search, packages, check-in tools, balance links, and QR controls.
- Preserve `MemberPortalPage` for non-admin membership users.

## Design

`MembershipPage` continues to return `MemberPortalPage` for non-admin users. For administrators it proceeds directly to the staff dashboard or its existing Add Member view, without an embedded member-portal branch. No API, database, authentication, public-balance URL, or QR behavior changes.

## Verification

A focused frontend assertion confirms the admin Membership header no longer contains the portal switcher or `membershipMode`, while the non-admin `MemberPortalPage` return remains. Run the frontend safety suite and rebuild the frontend container.
