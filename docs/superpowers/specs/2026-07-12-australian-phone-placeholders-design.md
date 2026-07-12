# Australian Phone Placeholder Design

## Goal

Use an Australian phone-number example in every dedicated phone-entry placeholder.

## Scope

- Replace the three dedicated Membership phone-entry placeholders with `+61 412 345 678`.
- Cover registration, staff membership promotion, and staff member editing.
- Leave the mixed email/phone/Member ID login hint unchanged.

## Design

The existing inputs, `type="tel"` attributes, state bindings, requests, validation, and stored phone values remain unchanged. Only their placeholder text changes to the same international Australian mobile example, making the expected format consistent across the product.

## Verification

A focused frontend safety assertion will confirm the exact placeholder appears three times. Existing frontend safety tests and the frontend Docker image build will verify the change does not affect runtime behavior.
