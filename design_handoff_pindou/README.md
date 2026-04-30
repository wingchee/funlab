# Handoff: FunLab 拼豆 Member Portal

## Overview

A full member portal for **FunLab 拼豆** — a pixel bead art community platform. Users browse bead patterns, open an interactive bead map viewer to track their crafting progress, save favorites, and (admins) upload + convert images into bead maps.

---

## About the Design Files

`PixelCraft.html` is a **high-fidelity interactive prototype** built in React/Babel. It is a **design reference only** — not production code. Your task is to **recreate these designs in your target codebase** (React, Next.js, Vue, etc.) using its established component libraries, routing, and state management patterns.

---

## Fidelity

**High-fidelity.** All colors, typography, spacing, border radii, shadows, hover states, and interactions are final and should be implemented pixel-accurately.

---

## Design Tokens

### Colors
| Token | Hex | Usage |
|---|---|---|
| `primary` | `#F47A8A` | CTA buttons, active nav, accents |
| `secondary` | `#6BB5E8` | Gradients, secondary actions |
| `purple` | `#9B8FCF` | Brand text accent (拼豆 label) |
| `amber` | `#F5C042` | Size badge: Medium |
| `green` | `#10B981` | Size badge: Small |
| `bg` | `#FEF4F5` | Page background |
| `surface` | `#FFFFFF` | Cards, modals, panels |
| `surface-alt` | `#F2F1EE` | Pill tags, inactive buttons, input bg |
| `border` | `#E8E6E1` | Card borders, input borders, dividers |
| `text-primary` | `#1A1A18` | Body text, headings |
| `text-secondary` | `#888888` | Subtitles, labels |
| `text-muted` | `#AAAAAA` | Placeholder text, empty states |
| `pixel-grid-line` | `rgba(26,26,24,0.04)` | Background grid lines |

### Typography
| Role | Family | Size | Weight | Notes |
|---|---|---|---|---|
| Body | Space Grotesk | 14–15px | 400–500 | All general UI text |
| Headings | Space Grotesk | 24–36px | 800 | `letter-spacing: -0.03em` |
| Mono / labels | Space Mono | 10–13px | 400/700 | Counts, codes, size badges |
| Nav links | Space Grotesk | 14px | 500/700 | |
| Buttons | Space Grotesk | 13–15px | 700 | |

### Spacing
Base unit: `8px`. Common values: `4, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40`.

### Border Radius
| Element | Radius |
|---|---|
| Cards | `8px` (user-adjusted via Tweaks) |
| Buttons (primary) | `8–10px` |
| Modals | `20px` |
| Pills / tags | `20px` |
| Avatar | `50%` |
| Color swatches | `4px` |
| Logo icon | `6–8px` |

### Shadows
| Level | Value |
|---|---|
| Card default | `0 2px 8px rgba(0,0,0,0.06)` |
| Card hover | `0 8px 24px rgba(0,0,0,0.10)` |
| Modal | `0 24px 80px rgba(0,0,0,0.25)` |
| Fab / floats | `0 8px 32px rgba(0,0,0,0.25)` |

### Gradients
- **Primary CTA**: `linear-gradient(135deg, #F47A8A, #6BB5E8)`
- **User avatar**: `linear-gradient(135deg, #F47A8A, #6BB5E8)`
- **Progress bar fill**: `linear-gradient(90deg, #F47A8A, #6BB5E8)`

---

## Screens / Views

### 1. Gallery (Browse Patterns)

**Purpose:** Main discovery screen. Users search, filter, and browse bead pattern cards.

**Layout:**
- Full-width page with sticky navbar (60px tall)
- Page padding: `40px` on all sides
- Hero text block: `h1` (36px/800) + subtitle, `margin-bottom: 32px`
- Search + filter bar: flex row, `margin-bottom: 32px`
  - Search input: white bg, `2px solid #E8E6E1` border, `12px` radius, `10px 16px` padding, max-width 400px, flex:1
  - Size filter buttons: `All / Small / Medium / Large`, pill style, `8px 16px` padding
  - Pattern count: right-aligned, mono font
- Pattern grid: CSS Grid, `auto-fill, minmax(240px, 1fr)`, gap `20px`
- Background: `#FEF4F5` with pixel dot grid overlay (24px spacing, 4% opacity lines)

**Pattern Card:**
- White background, `8px` border-radius, `2px solid transparent` border (becomes `2px solid #F47A8A` on hover)
- Hover: `translateY(-3px)` + elevated shadow
- Preview area (160px tall): canvas-rendered pixel grid preview on colored background tint
  - Size badge: top-left, colored pill (`Small=#10B981`, `Medium=#F5C042`, `Large=#F47A8A`), `Space Mono` 10px/700
  - Favorite heart button: top-right, 32×32 circle, white bg → `#F47A8A` when active, SVG heart icon
- Card body padding: `14px 16px 16px`
  - Title: 15px/700
  - Tags: `#F2F1EE` pills, 11px/500, `2px 8px` padding, 20px radius, `#666` text
  - Color swatch dots (12px circles) + favorite count in mono

### 2. Bead Map Viewer (Modal / Overlay)

**Purpose:** Full-screen overlay showing interactive pixel grid. Logged-in users click cells to cross off placed beads.

**Layout:**
- Fixed overlay: `rgba(26,26,24,0.7)` + `backdrop-filter: blur(6px)`
- Modal: white, `20px` radius, `min(920px, 95vw)` wide, `max-height: 90vh`, flex column
- Header (border-bottom `#F0EDE8`): pattern title, grid dimensions, color count, progress bar (logged-in only), zoom controls, close button
- Body: flex row
  - Left: scrollable grid area, `padding: 24px`
  - Right: color legend sidebar, `200px` wide, border-left `#F0EDE8`, `padding: 20px 16px`

**Pixel Grid:**
- Rendered as a grid of `div` elements
- Cell size: `Math.min(Math.floor(460 / gridWidth), 24)` px square
- Each cell: background = bead color, `0.5px solid rgba(0,0,0,0.06)` border
- Hovered color: highlight matching cells at full opacity; others at 0.88
- Crossed-off cell: background `#F0EDE8`, opacity 0.25, SVG checkmark overlay
- Zoom: 0.75×, 1×, 1.5×, 2× buttons → CSS `transform: scale()`

**Progress bar:**
- Track: `#F0EDE8`, `6px` tall, `3px` radius
- Fill: gradient `#F47A8A → #6BB5E8`, width = `(done/total)*100%`, transition 0.3s

**Color Legend (sidebar):**
- Each row: 18×18 swatch + name (11px/600) + bead count (10px mono)
- Hover row: highlights matching grid cells
- "Download PDF" CTA button (full-width gradient)
- "Reset Progress" ghost button (logged-in only, after any progress)

**Not-logged-in state:** amber info banner at top of grid — `#F5C042` tint background, lock icon, sign-in prompt.

### 3. My Favorites

**Purpose:** Saved patterns for logged-in users. Same card grid as Gallery.

**Logged-out state:**
- Centered empty state, gradient heart icon (80×80, `20px` radius)
- "Sign In to Continue" CTA button

**Logged-in, empty state:**
- Centered `♡` emoji + "No favorites yet" text

### 4. Admin Dashboard

**Purpose:** Admin-only screen. 3-step flow to upload an image and publish a bead pattern.

**Step indicator:**
- Flex row, 3 segments separated by `1px #E8E6E1` dividers
- Active step: `#F47A8A` bg, white text
- Completed step: `#F47A8A20` bg, `#F47A8A` text
- Inactive: `#F2F1EE` bg, `#AAA` text
- Labels: `01 Upload`, `02 Configure`, `03 Preview`; `12px/700`, `letter-spacing: .05em`

**Step 1 – Upload:**
- Dashed border drop zone: `2px dashed #D0CEC9` → `#F47A8A` on drag-over
- Upload icon (SVG, `#F47A8A`), headline, subtitle, "Choose File" CTA

**Step 2 – Configure:**
- Uploaded file preview row: icon + filename + remove button
- Grid Size selector: `12×12 / 16×16 / 24×24 / 32×32 / 48×48`
- Bead Palette selector: `Hama / Perler / Artkal S / Artkal C`
- Color Accuracy range slider: 50–100, accent `#F47A8A`
- "Convert to Bead Map ✦" gradient CTA (full-width)
- Loading state: spinner animation + "Processing…" text

**Step 3 – Preview:**
- Success header with check icon
- Mini pixel grid preview
- Grid + color count stats (2-col layout)
- "Upload Another" ghost + "Publish to Library ✦" gradient buttons

**Right sidebar (persistent):**
- Library Stats card: Total Patterns, Total Favorites, Avg. Rating
- Conversion Tips card: 3 numbered tips

### 5. Sign In / Sign Up Modal

**Purpose:** Authentication overlay.

**Layout:**
- Fixed overlay: `rgba(26,26,24,0.6)` + `backdrop-filter: blur(6px)`
- Modal: white, `20px` radius, `380px` wide, `36px` padding
- Logo + brand name centered at top
- Tab switcher: "Sign In" / "Create Account" pill tabs in `#F2F1EE` bg
- Email + Password inputs: `2px solid #E8E6E1` border → `#F47A8A` on focus
- Submit button: gradient CTA, full-width, loading state with spinner

**Admin access:** If email contains "admin", user gets admin role (dev note: replace with real auth).

---

## Interactions & Behavior

| Interaction | Detail |
|---|---|
| Card hover | `translateY(-3px)` + elevated shadow + `#F47A8A` border — `transition: all 0.18s ease` |
| Heart/fave toggle | Instant state flip; prompts login if not signed in |
| Modal open | `scaleIn` animation: `scale(0.96→1)` + `opacity(0→1)`, 0.25s ease |
| Card list | `fadeIn` animation: `translateY(8px→0)` + `opacity(0→1)`, 0.35s ease |
| Progress bar | `transition: width 0.3s` on bead cell click |
| Cell hover in grid | `onMouseEnter` highlights bead ID in legend + all matching cells |
| Login submit | 900ms fake delay (replace with real API), spinner during loading |
| Admin step 2 → 3 | 2000ms fake processing (replace with real conversion API) |
| Tweaks panel | Slides up from bottom-right, driven by `postMessage` protocol |

### Persistence (localStorage)
- `pc_page` — active page
- `pc_favs` — JSON array of favorited pattern IDs
- `pc_loggedin` — `"1"` / `"0"`
- `pc_admin` — `"1"` / `"0"`

---

## Navigation / Routing

| Route | Page | Auth required |
|---|---|---|
| `/` or `/gallery` | Gallery | No |
| `/favorites` | My Favorites | Yes (prompt login if not) |
| `/admin` | Admin Dashboard | Yes + admin role |

---

## State Management

```
user: { isLoggedIn, isAdmin }
favIds: Set<patternId>
activePage: 'gallery' | 'favorites' | 'admin'
openPattern: Pattern | null   // drives bead map modal
showLoginModal: boolean
```

### Pattern data shape
```ts
type Pattern = {
  id: number
  title: string
  tags: string[]
  size: 'Small' | 'Medium' | 'Large'
  gridW: number
  gridH: number
  faves: number
  palette: BeadColor[]
  preview: string  // hex color for thumbnail tint
}

type BeadColor = {
  id: string       // e.g. "B001"
  name: string
  hex: string
}
```

---

## Assets

| File | Description |
|---|---|
| `funlab-logo.jpeg` | FunLab 拼豆 company logo — use in navbar and login modal |

**Fonts:** Load from Google Fonts — `Space Grotesk` (400/500/600/700) and `Space Mono` (400/700).

---

## Files

| File | Description |
|---|---|
| `PixelCraft.html` | Full hi-fi interactive prototype — all 5 screens in one React SPA |
| `funlab-logo.jpeg` | Brand logo asset |
| `README.md` | This document |

---

## Implementation Notes

1. **Pixel grid background** — CSS `background-image` with two `linear-gradient` lines at 4% opacity, `24px` background-size. See `.pixel-bg` class in the prototype.
2. **Bead map grid** — The prototype generates a deterministic pixel grid from a sine-wave formula (placeholder data). Replace with real pattern data from your backend.
3. **Image-to-bead conversion** — The Admin upload flow is a UI mock only. Wire Step 2 → Step 3 to a real image processing API.
4. **Authentication** — Replace the 900ms fake login with your auth provider (NextAuth, Supabase, Clerk, etc.).
5. **Canvas thumbnails** — Pattern card previews are drawn on `<canvas>` elements with `imageRendering: pixelated`. Consider pre-generating these server-side as images for performance.
