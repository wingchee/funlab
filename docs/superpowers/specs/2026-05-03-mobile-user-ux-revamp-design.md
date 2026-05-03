# Mobile User UX Revamp Design

Date: 2026-05-03

## Scope

Revamp the root project UI for more comfortable mobile and desktop web use, with the strongest focus on mobile user-side flows. Do not modify `BeanBuddy-AI-main/` or `perler-beads-master/`.

The production UI is currently the single-file React app in `frontend/index.html`. Existing backend APIs, auth behavior, admin conversion flow, and timetable endpoints remain unchanged.

## Approved Direction

Use a library-first mobile experience for visitors and members:

- Mobile users should reach search, filters, pattern cards, saved patterns, timetable, and bead-map viewing with fewer taps.
- The brand/home page should remain, but on mobile it should be shorter and should lead quickly into library tasks.
- Admin remains optimized for tablet and desktop because that is the normal usage context.
- Admin screens still need responsive cleanup so they do not break on narrow screens.

## UX Goals

- Make phone usage comfortable beside a bead board.
- Reduce vertical friction on mobile by using compact headers, sticky actions, and bottom navigation.
- Improve tap target size and spacing for pattern browsing, favorite toggling, filters, zoom controls, and bead-map actions.
- Keep desktop layouts familiar, but tighten spacing and max widths so pages feel calmer.
- Preserve the existing FunLab AU visual identity: Space Grotesk, Space Mono for numeric/code labels, `#F47A8A`, `#6BB5E8`, `#FEF4F5`, `#FFFFFF`, `#E8E6E1`, and the pixel-grid background.

## App Shell

### Desktop

- Keep the sticky top navigation.
- Keep primary navigation labels: Home, Library, Saved, Time Table, and Admin for admin users.
- Improve spacing so the nav remains stable when labels wrap or the viewport narrows.

### Mobile

- Convert the app shell into a compact top header plus fixed bottom navigation.
- Top header contains brand/logo and account/sign-in affordance.
- Bottom navigation contains Home, Library, Saved, and Time.
- Admin access does not need a bottom-nav item; admin users can still reach Admin from the wider/tablet navigation or a compact account/menu affordance if present.
- Add bottom padding to pages so fixed bottom navigation does not cover content.

## Home Page

### Mobile

- Shorten the hero copy and reduce hero visual height.
- Move the main action toward Library-first behavior.
- Keep a clear path to Join/Member Sign In.
- Avoid oversized desktop hero typography on phones.
- Keep the FunLab brand visual, but reduce decorative stats and orbit elements when space is tight.

### Desktop

- Preserve the current official website structure: hero, offer cards, steps, and visit panel.
- Improve responsive breakpoints and content max widths where needed.

## Library And Saved Patterns

### Mobile

- Use a compact page title and subtitle.
- Make search full width.
- Make size filters horizontally scrollable chips with stable tap areas.
- Prefer one-column pattern cards or wider mobile cards with larger preview and easier favorite tapping.
- Keep pattern metadata readable: title, tags, palette dots, favorite count.
- Improve empty states so they fit cleanly in one viewport.

### Desktop

- Keep the grid layout, but use consistent page gutters and a max content width for better readability on wide displays.
- Preserve card hover behavior.

## Bead Map Viewer

### Mobile

- Change the modal into a full-height or near-full-height sheet.
- Header stays sticky with pattern title, dimensions, close action, and progress summary.
- Grid area becomes the primary focus with horizontal and vertical scrolling.
- Keep zoom controls accessible without crowding the title.
- Move legend into a collapsible section, drawer, or stacked section below the grid.
- Keep primary actions sticky at the bottom: Fullscreen and Download PDF.
- Ensure fixed actions never cover the grid without enough safe padding.

### Desktop

- Preserve the side-by-side modal layout with grid and legend.
- Improve spacing and control wrapping if the viewport is narrower than the current modal expects.

## Timetable

### Mobile Users

- Keep the timetable cards easy to scan.
- Preserve individual table links.
- Ensure action buttons and timer text do not overflow.
- Bottom nav should make Time easy to reach.

### Admin

- Admin controls remain available on tablet/desktop.
- On narrow screens, controls can stack rather than attempting a dense grid.

## Admin Dashboard

- Keep the existing three-step upload/configure/preview workflow.
- Keep a two-column layout on tablet/desktop.
- Collapse to one column below tablet width.
- Improve button wrapping in the preview action row so actions remain readable.
- Do not redesign conversion logic or API flow.

## Implementation Notes

- Continue working in `frontend/index.html`; avoid a framework migration in this revamp.
- Prefer CSS classes and responsive media queries over expanding inline style complexity where practical.
- Add shared responsive utility classes for page shell, mobile-only bottom nav, content gutters, filter bars, card grids, modal layout, and sticky mobile actions.
- Preserve current React state, local storage keys, and API calls.
- Do not change backend files for this UX pass unless a frontend integration issue requires it.

## Testing And Verification

- Run a lightweight static/serving check for `frontend/index.html`.
- Use the in-app browser to verify:
  - Mobile viewport around 390px width.
  - Desktop viewport around 1280px width.
  - Home, Library, Saved, Time Table, Bead Map Viewer, and Login Modal.
  - Admin layout at tablet/desktop width if an admin session is available; otherwise inspect the responsive CSS and available UI state.
- Check for mobile overflow, covered bottom content, unreadable buttons, cramped filters, modal content clipping, and broken desktop layout.

## Out Of Scope

- No changes to `BeanBuddy-AI-main/`.
- No changes to `perler-beads-master/`.
- No backend API redesign.
- No database schema changes.
- No authentication behavior changes.
- No visual concept replacement of the FunLab AU brand.
