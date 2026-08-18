<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Frontend - Local Development Guide

This is the React + Vite frontend for the Agentic ERP Automation Quickstart. This README focuses on local development setup and workflows.

For full stack deployment instructions, see the [top-level README](../README.md) and [deployment documentation](../docs/getting-started/DEPLOYMENT.md).

![Chat example](readme-imgs/fast-chat-screenshot.png)

## Local Development Setup

### Prerequisites

- Node.js (20+ recommended)
- npm

### Quick Start

1. Navigate to the frontend directory:

```bash
cd frontend
```

2. Install dependencies:

```bash
npm install
```

3. Start the development server:

```bash
npm run dev
```

4. Open [http://localhost:3000](http://localhost:3000) in your browser

## Development Options

### Option 1: With Authentication (Default)

By default, the app uses Cognito authentication. To test this locally:

1. First deploy the full stack (see [deployment docs](../docs/getting-started/DEPLOYMENT.md))
2. Generate the local auth config from your deployed stacks:

```bash
./scripts/dev/local-dev.sh config
```

3. Start the dev server:

```bash
cd frontend
npm run dev
```

This generates `frontend/public/aws-exports.json` with `localhost:3000` as the redirect URI and the correct Cognito/backend values from your deployed stacks. Re-run the script any time you redeploy infrastructure.

### Option 2: Disable Authentication (ONLY for Local Development!!!)

For faster local development without needing to deploy Cognito, you can disable authentication:

**⚠️ IMPORTANT: Remove the AuthProvider wrapper from `src/App.tsx`**

Change this:

```tsx
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

To this (drop the `AuthProvider` wrapper only):

```tsx
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

This bypasses all authentication flows and lets you develop the UI directly.

### External IdP frontends (direct-entra / direct-okta)

A `direct-entra` / `direct-okta` auth profile points the SPA's login at an external
IdP instead of Cognito. Set `frontend_overrides` in `cdk/config.yaml`
(`discovery_url`, `client_id`, and optional `scope`) — `deploy-frontend.py` writes
these into `aws-exports.json`. `cognito` and `cognito+federated` frontends need no
extra step; they log in against the Cognito user-pool authority as before.

## Design conventions

Fourteen rules the codebase currently enforces. They exist because each one was violated
at some point and cost us a defect.

### The visual identity lives in tokens

`src/styles/globals.css` is the one place the look is decided. `:root` holds the light
theme, `.dark` the dark one, and `@theme inline` maps each `--foo` onto a Tailwind
utility. The decisions encoded there:

- **Ground is cool slate**, not pure grey — the neutrals carry a faint 210°/215° hue
  so the app reads as a console. Surfaces climb in lightness (`--background` →
  `--card`) so panels lift off the ground.
- **`--agent` is reserved.** One violet hue means "the agent is working" — the live
  spinner, the refresh shimmer, in-flight counts — and nothing else. No status tone
  owns violet, so agent motion can never be mistaken for a state.
- **`--radius` is 0.375rem.** Console-sharp, not consumer-soft. Every `radius-*` step
  derives from it; never hardcode a corner.

Components reference tokens (`bg-card`, `text-muted-foreground`, `border-input`), never
raw palette classes or hex. The two sanctioned exceptions, both documented at their
definition: the semantic **status tones** in `statusTone.ts`, and the **chart
data-series palettes** (`TOOL_COLORS`, `MODEL_COLORS`) that feed SVG `fill`/`stroke`.

### Three faces, three jobs

| Utility        | Face          | Job                                              |
| -------------- | ------------- | ------------------------------------------------ |
| `font-sans`    | Geist         | body and UI — the default, never written out     |
| `font-display` | Space Grotesk | headings and headline numerics                   |
| `font-mono`    | Geist Mono    | anything read character-by-character against SAP |

`font-mono` is a correctness tool, not a style: case ids, PO numbers, and tool names
get compared against another screen, so `0`/`O` and `1`/`l` have to be distinct.

`font-display` is declared once in `globals.css` as `--font-display-face` and applied
through `PageHeader` and `StatMetric` — reach for those before writing an `h1` or a
metric tile, and the pairing follows automatically. It falls back to Geist rather than
generic `sans-serif`, so a failed font load changes one thing instead of two.

Sizes come from the scale, including below `text-xs`: `text-2xs` (11px) and `text-3xs`
(10px) are declared in `globals.css` for the trace and timeline rows. Use them instead
of `text-[10px]` — an arbitrary size carries no line-height and is invisible to the
density toggle.

**Money and metric columns are `tabular-nums`.** Proportional digits have different
widths, so a polled number twitches sideways on every refresh and a column of amounts
fails to line up on the decimal. Both sans faces ship the `tnum` OpenType feature —
verified, not assumed; the class is silently inert on a face without it.

### Page chrome lives in the layout route

`src/routes/AppShell.tsx` holds two layout routes. `AppShell` gives every route the
rail plus the `<main>` gutter; `PageFrame` gives the dashboards the fixed-header /
scrolling-body column. A route renders its header and body as fragments and inherits
the rest — it does not re-declare `flex flex-col h-full`, which is how padding and
max-width previously drifted per screen.

Workspace is the one exemption, declared in the route config: its Allotment panes
need the whole viewport, so it sits outside `PageFrame`. `routing.test.tsx` asserts
the exemption, because nesting it would silently constrain the split panes.

### The chat transcript is a module store, not layout-route state

`AppShell` owns the conversation and hands it to routes through `<Outlet context>`, so
state held there re-renders the routed page too. With the transcript in `useState`, every
streamed token re-rendered Workspace and its case list. It lives in `lib/transcript.ts`
instead — a `useSyncExternalStore` store that `AssistantDock` subscribes to directly, so
a token repaints the assistant and nothing else. `lib/agentActivity.ts` is the same
pattern for the rail's heartbeat; reach for it before adding a state library.

Both stores outlive unmount, which is the tax: a test that renders the shell has to
reset them in `beforeEach` or it inherits the previous test's turn.

Messages are never persisted. They carry SAP tool results — PO numbers, amounts, vendor
names — and `localStorage` would leak them past sign-out on a shared workstation.

### Sign-out drops the work, keeps the window

`lib/signOut.ts` is the one wipe, called from the rail's Logout button _and_ from
`AutoSignin` on the authenticated→unauthenticated edge, so an expired session clears the
same residue as a deliberate sign-out. It empties the transcript store, the React Query
cache, the case-scoped `localStorage` keys, and the query string that names the focused
case.

The `localStorage` half is an allowlist of layout keys (theme, density, collapse state,
pane sizes) rather than a list of keys to delete — a key added later is dropped by
default, which is the safe direction for a wipe. `oidc.*` is left alone; oidc-client-ts
removes its own stored user mid-signout and clearing it underneath breaks the
end-session request.

### Headers, stats, and empty states come from the kit

`src/components/ui/page-chrome.tsx` owns the parts every route was improvising:
`PageHeader`, `StatMetric`, `EmptyState`, `PageLoader`, `DomainTabs`, `DomainPill`, and
`Banner`. Reach for one before writing a header row or a "nothing here" paragraph.

The kit declares no colour of its own — `Banner` takes a tone and reads it from
`statusTone.ts`. That is the point: the red left-accent notice had been copy-pasted a
dozen times, the domain tab strip was `border-blue-500` on Tickets and
`border-foreground` on Workspace, and three empty states used three different greys.

`Banner` is `role="alert"` only for `danger` and `role="status"` otherwise, so a warning
does not interrupt a screen reader. `PageLoader` announces via `aria-busy` and pulses
rather than spinning — the motion budget reserves spin for causality.

### Colour means state, nothing else

Every status colour is decided in one file, `src/lib/statusTone.ts`, which defines a
small semantic vocabulary (`neutral`, `info`, `progress`, `attention`, `success`,
`danger`). Case status and ticket status both map onto it via their `*_STATUS_META`
tables, and both render through the single `StatusBadge` primitive.

Do not put a status colour class in a component. Case and ticket state previously
carried independent colour choices, so the same meaning rendered differently depending
on the screen; three separate hand-rolled status pills had drifted apart before they
were consolidated. Add a tone to `statusTone.ts` or reuse one — two states in the same
category may share a tone and be told apart by their label. The file exposes the tone
four ways: `TONE_BADGE` (pill), `TONE_BANNER` (left-accent notice), `TONE_DOT` (dot),
and `TONE_TEXT` (a bare icon or count). All four ship `dark:` variants, and
`status-badge.test.tsx` asserts it for every tone in every rendering.

**Categorical is not state.** A trigger source (poller / manual / webhook) or a chart
series is data, not a status — a webhook is not "success". Those keep distinct hues
rather than borrowing a tone, but they still carry `dark:` variants so they survive
both grounds. When the colour answers "what does this mean to the operator", it is a
tone; when it answers "which of several things is this", it is categorical.

### Both themes ship, and both are measured

`useTheme` is the only place the `.dark` class is set, and it sets it on
`document.documentElement` — not on a provider div, because Radix portals (popovers,
dialogs, selects) render outside the app root and would otherwise stay light. The
default is `system`; a manual choice persists to `localStorage["ui.theme"]`.

The class is also set by a **blocking inline script in `index.html`**. React mounts
after first paint, so a component-set class flashes the light theme first. That
duplication is deliberate and the drift is the risk, so `config.test.ts` pins the
storage key, the class, and the script's position ahead of the app bundle.

Contrast is arithmetic, not judgement. Every colour that carries meaning clears
**4.5:1 as text** and **3:1 as a graphical object** against all four grounds — light
card, light background, dark card, dark background — computed against the installed
Tailwind oklch values, with alpha compositing for the `dark:bg-*-400/15` pill tints.
Two consequences worth knowing before you pick a weight:

- **No weight works on both grounds.** A fill that clears 3:1 on white is too dark on
  the dark card. Every entry in every tone map is a light/dark pair, dots included.
- **The light side needs `-700`, not `-600`, for text.** `blue-600` measures 3.88:1 on
  white and `red-600` 4.41:1 — both fail. `-600` is fine for a dot, which only owes 3:1.

White-on-colour buttons are the easy miss: `bg-orange-600` with white text is 3.42:1.

### Density is a token change, not a second set of utilities

Target users live in SAP GUI and read whitespace as wasted screen, so the rail carries
a comfortable/compact toggle next to the theme one. `useDensity` puts `.compact` on
`document.documentElement` — same two reasons as `.dark`: Radix portals render outside
the app root, and custom properties only inherit. It persists to
`localStorage["ui.density"]`.

Compact **re-declares Tailwind's own scales** rather than adding `compact:` variants.
Every `p-*`, `gap-*`, `h-*`, and `size-*` resolves through `--spacing`, so one class
restyles the app and no component has to know density exists:

```css
.compact {
  --spacing: 0.1875rem; /* from 0.25rem */
  --text-xs: 0.703125rem; /* 11.25px */
  --text-xs--line-height: 1.298; /* → 14.6px box */
  /* …both halves of every step */
}
```

Three things that are easy to get wrong here:

- **Move both halves of each type step.** A list of `text-xs` rows loses more height to
  line-height than to padding, so re-declaring `--text-xs` alone barely moves anything.
- **`.compact` must stay unlayered.** Tailwind's defaults live in `@layer theme` under
  `:root`, and an unlayered rule beats a layered one regardless of specificity.
- **Arbitrary values are unreachable.** `text-[10px]` compiles to a literal with no
  line-height at all, so 45 such sites — the trace, timeline, and badge rows where
  density matters most — were the ones it could not touch. They now use the named
  `text-2xs` / `text-3xs` steps, declared in a plain `@theme` block because
  `@theme inline` bakes the value into the utility and puts it out of reach.

10px is the floor; below that the trace rows stop being readable. `--radius` does not
move — corner radius is identity, not density. Shrinking `--spacing` also shrinks
hit targets, so `globals.css` pins a 14px minimum on checkboxes and radios.
`config.test.ts` asserts the spacing scale moves, that every type step moves both
halves, and that the sub-`xs` steps stay outside `@theme inline`.

**`--spacing` is the wrong knob for tuning how far apart the two modes sit.** The chrome
uses `min-h-7` and `w-11`, so every spacing step has to land on an integer pixel, and
4px and 3px are the only options in that range — anything between puts `px-3` at 10.5px.
So the whole type scale is re-declared in the plain `@theme` block, comfortable coming
down to meet compact coming up, which is where the rows actually are. Re-derived against
the compiled stylesheet, comfortable/compact: trace row 33.5 / 28.3px, rail row
34.5 / 28.5px, page header 47.0 / 39.0px.

The knob has a ceiling, and the case row hit it. Leading dominates a **stacked** row, so
the type scale converged the old two-line case row from 21.1% to 16.9% apart. The
one-line row that replaced it (see the density note in the roadmap's D.9) leaves one text
box, and 4 of its 6px residual gap is `py-2` — so the row is back to 20.7% apart and the
remaining distance is padding, which is the one knob that cannot move. Type-scale
convergence works on rows built from stacked text and runs out on rows built from one line.

No browser was available, so these are arithmetic over the compiled values —
`text-*` utilities emit `font-size: var(--text-N)` with `line-height:
var(--text-N--line-height)`, and each `--line-height` here is the target box divided by
the size, so the pair _is_ the row height.

### Chrome sizing lives in tokens

Icon size, panel width and band height were each decided per component until they
disagreed. One source for each now: `ICON_CHROME` / `ICON_INLINE` in `src/lib/utils.ts`
(icons take a literal `size={n}` SVG attribute, so they cannot be tokens, and an icon
that shrank with density would stop matching the text baseline it sits on), and
`--rail-w` / `--dock-w` / `--gutter-w` / `--band-h` in `:root`. All three widths are
re-declared in `.compact` and `--band-h` derives from `--spacing`, because chrome that
ignored the density toggle would be the same bug in a new place.
`config.test.ts` pins the mechanism — that the tokens exist and that the components read
them — not the values, so a future tuning pass does not have to delete a test.

The rail has **one** width, 48/40px, because it has one state. Its rows are icons labelled
by a CSS-only tooltip on hover or focus, so there is nothing to expand into — a collapse
toggle would have been a control with a single outcome, and the width that used to be the
expanded one was mostly label. Two consequences worth knowing before editing it: the nav
list must not be a scroll container, since `overflow-y: auto` forces `overflow-x` to
compute as `auto` too and would clip every tooltip at `left-full`; and each row's tooltip
text is its `aria-label`, so the two cannot drift.

### Motion has a budget

One easing curve and three durations, declared as tokens in `globals.css`:

| Token             | Value                            | Use                                  |
| ----------------- | -------------------------------- | ------------------------------------ |
| `--ease-standard` | `cubic-bezier(0.22, 1, 0.36, 1)` | every transition                     |
| `--duration-fast` | 120 ms                           | hover, focus, colour                 |
| `--duration-base` | 200 ms                           | entrances, layout shifts             |
| `--duration-slow` | 250 ms                           | ceiling — nothing should exceed this |

Motion shows causality — where something went, what changed — and is never
decoration. An earlier `fade-in-up` ran for **2 seconds**, which reads as a hung app
rather than as polish. Always pair a transition with `motion-reduce:transition-none`;
keyframe animations need an entry in the `prefers-reduced-motion` block.

### Links are styled where they are rendered

There is deliberately **no global `a` rule**. The previous one applied a brand colour
and an underline to every anchor in the app, which meant every react-router `<Link>`
wrapping a `<Button>` rendered an underlined button label, and every rail nav item was
underlined too. It also failed WCAG AA contrast at roughly 2:1.

Prose links live in `MarkdownRenderer` and use the `--link` token, which is tuned per
theme to clear the 4.5:1 floor. Anything else styles itself.

Agent-generated markdown is untrusted input, so external hrefs get
`target="_blank" rel="noopener noreferrer"`.

### Tokens over literals

Colours come from the token set in `globals.css`. Note that `:root` declares
`--brand-*` as bare HSL _components_ (`197 37% 24%`), not colours — the `@theme` block
wraps them in `hsl()`. Referencing `var(--brand-teal)` as a colour silently produces an
invalid value.

### No chunk over 500 kB

`build.test.ts` asserts it, because a Rollup size warning is easy to scroll past — the
app chunk reached 1,241 kB before anyone acted on one. Two habits keep it there:

- **Lazy-load routes.** Everything in `src/routes/` except Workspace is behind
  `React.lazy`. Workspace is the landing route, so splitting it would only add a round
  trip to first paint.
- **Deep-import from big libraries.** Barrel files pull in everything. The syntax
  highlighter's eager `Prism` entry statically imports `refractor/all` — ~960 kB of
  Prism grammars for every language in existence — so `MarkdownRenderer` uses
  `PrismAsyncLight` and imports the single theme directly rather than via the styles
  barrel.

When adding to `manualChunks`, name the specifier the app actually imports. Listing
`react-dom` while the entry imports `react-dom/client` left the whole renderer in the
app chunk.

## UI Components

This project uses [shadcn/ui](https://ui.shadcn.com/docs/components) for UI components.

### Adding New Components

Install additional shadcn components as needed:

```bash
npx shadcn@latest add calendar
npx shadcn@latest add dialog
npx shadcn@latest add form
```

### Available Components

Browse the full component library at: https://ui.shadcn.com/docs/components

Popular components include:

- Button, Input, Textarea
- Dialog, Sheet, Popover
- Table, Card, Badge
- Form, Calendar, Select
- And many more...

## Icons

This project includes [Lucide React](https://lucide.dev/) icons, providing a comprehensive set of beautiful, customizable icons.

### Using Icons

Import and use any icon from the Lucide library:

```tsx
import { Camera } from "lucide-react"

// Usage
const App = () => {
  return <Camera color="red" size={48} />
}

export default App
```

### Available Icons

Browse all available icons at: https://lucide.dev/

Popular icons include Camera, Search, Menu, User, Settings, Download, Upload, and hundreds more.

## Project Structure

```
frontend/
├── src/
│   ├── main.tsx            # Application entry point
│   ├── App.tsx             # Root component with routing
│   ├── routes/             # Route components
│   ├── components/
│   │   ├── ui/             # shadcn components
│   │   ├── chat/           # Chat UI
│   │   └── auth/           # Authentication components
│   ├── hooks/              # Custom hooks (useToolRenderer)
│   ├── lib/                # Utilities and configurations
│   │   ├── aguiReducer.ts  # Folds AG-UI events into chat state
│   │   ├── transcript.ts   # Chat messages, held outside React state
│   │   ├── signOut.ts      # Drops the operator's working context
│   │   └── ...
│   ├── services/           # API service layers (incl. agentRuntimeService: AG-UI transport)
│   └── styles/             # Global styles
├── public/                 # Static assets
├── index.html              # HTML entry point
└── package.json
```

## Environment Variables

The application uses Vite environment variables with the `VITE_` prefix:

- `VITE_COGNITO_USER_POOL_ID` - Cognito User Pool ID
- `VITE_COGNITO_CLIENT_ID` - Cognito Client ID
- `VITE_COGNITO_REGION` - AWS Region
- `VITE_COGNITO_REDIRECT_URI` - Redirect URI after authentication
- `VITE_COGNITO_POST_LOGOUT_REDIRECT_URI` - Redirect URI after logout

These can be set in a `.env` file or as environment variables. The application will fall back to `aws-exports.json` if environment variables are not set.

## Available Scripts

- `npm run dev` - Start the Vite development server
- `npm run build` - Build for production (runs TypeScript check + Vite build)
- `npm run preview` - Preview the production build locally
- `npm run test` - Run the Vitest suite once
- `npm run test:watch` - Run Vitest in watch mode
- `npm run lint` - Run ESLint
- `npm run lint:fix` - Run ESLint with auto-fix
- `npm run clean` - Clean build artifacts and dependencies

## Development Tips

- **Hot Reload**: Changes auto-reload in the browser with Vite's fast HMR
- **TypeScript**: Full type safety with strict mode enabled
- **Vibe Coding**: Optimized for AI-assisted development
- **Tailwind CSS**: Utility-first styling with Tailwind CSS 4

## Building with AI Assistants

This stack is designed for AI-assisted development:

1. **Describe your vision**: "Create a document upload component with drag-and-drop"
2. **Leverage shadcn components**: Rich building blocks that AI understands
3. **Iterate quickly**: Make changes and see results instantly

### Example AI Prompts

- "Add a file upload component to the chat interface"
- "Create a sidebar with navigation using shadcn components"
- "Build a settings page with form validation"
- "Add a data table with sorting and filtering"
