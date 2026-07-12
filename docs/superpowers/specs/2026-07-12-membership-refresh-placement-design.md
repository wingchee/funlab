# Membership Refresh Placement Design

## Goal

Place the Refresh control immediately to the left of the Staff Dashboard / Member Portal switcher in the staff Membership header.

## Scope

- Change only the visual order of the two existing controls in `MembershipPage`.
- Keep the Refresh action, its loading label, the mode-switch action, and all existing styling intact.
- Preserve the existing wrapping behavior on narrow screens.

## Design

The header action row remains a wrapping flex container. The Refresh button is rendered first, followed by the segmented membership-mode switcher. On desktop this puts Refresh on the left of the switcher. When the row wraps on a narrow viewport, the browser retains the same source order without imposing a new breakpoint or layout rule.

## Data, Errors, and Testing

This presentation-only change makes no request, state, data-model, or error-handling changes. Verification will confirm the source order and exercise the existing frontend container build.
