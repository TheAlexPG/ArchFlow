# ArchFlow Redesign v1 — Plan

Reference: `~/Downloads/archflow-redesign.html` (static HTML concept, 4 screens:
dashboard / diagrams list / canvas / feature diff).

Goal: ship a cohesive visual refresh that matches the reference closely (not 1:1)
while working inside the existing React/Vite/Tailwind v4 codebase. Preserve all
current features (drafts, realtime, C4, connections) — this is a **UI/UX refresh**,
not a rewrite.

Branch: `feat/redesign-v1` (off `main`, includes update-pack fixes).

---

## Design language (extracted from reference)

### Colors

Dark-first palette driven by CSS variables. Port into Tailwind v4 `@theme`:

| Token                 | Hex / value                     | Usage                                             |
| --------------------- | ------------------------------- | ------------------------------------------------- |
| `bg`                  | `#0a0a0b`                       | page background                                   |
| `panel`               | `#111113`                       | window chrome, sidebars, popovers                 |
| `surface`             | `#16161a`                       | cards, inputs, buttons                            |
| `surface-hi`          | `#1d1d22`                       | hover / active                                    |
| `border`              | `#26262c`                       | default dividers                                  |
| `border-hi`           | `#35353d`                       | hover border                                      |
| `text` / `-2/-3/-4`   | `#fafafa / a1a1aa / 71717a / 52525b` | 4-step ramp                                  |
| `coral` / `coral-2`   | `#FF6B35 / #FF8552`             | brand accent, primary CTA                         |
| `green / purple / blue / amber / pink` | standard Tailwind 400-shade tokens | semantic (done/actor-review/processing-edge/input/draft-AI) |
| `*-glow`              | 12-15% alpha of matching accent | translucent glow backgrounds                      |

### Typography

- **IBM Plex Sans** 400/500/600/700 — body + headings (features `ss01 ss02 cv11`)
- **IBM Plex Mono** 400/500/600 (feature `zero`) — metadata, slugs, counts, kbd hints
- **IBM Plex Serif** italic 500 — single decorative glyph (coral em-dash in hero)
- Tight px-scale: `8.5 / 9 / 9.5 / 10 / 10.5 / 11 / 11.5 / 12 / 12.5 / 13 / 14 / 15 / 22 / 28 / 32`
- Section labels: mono 10.5px uppercase `tracking-[0.08em]`
- Pills: mono 10.5px `tracking-[0.02em]`

### Effects / motion

- Page bg: coral + pink radial gradients over `#0a0a0b`
- Canvas bg: 24px dotted grid (`radial-gradient circle #26262c 1px`)
- Noise overlay: SVG fractalNoise at 1.5% alpha — subtle grain
- Window shadow: `0 40px 80px -20px rgba(0,0,0,.6), 0 20px 40px -20px rgba(0,0,0,.4)`
- Selected node glow: `0 0 0 3px coral-glow, 0 0 40px coral-glow`
- Pulse keyframe (presence dot), fab-ring keyframe (FAB breathing),
  popup-in + item-stagger (add-popup reveal), dash (animated edges)
- Themed scrollbars: 10px, transparent track, floating pill thumb

### Component inventory (to port as React components)

**Primitives** — `Pill`, `PillDot`, `StatusPill` (done/review/processing/input/draft),
`Button` (default / primary / ghost), `Kbd`, `SectionLabel`, `LevelBar`, `Pulse`,
`Avatar` (gradient initials with configurable color pair).

**Nav** — `NavItem` (icon + label + count + coral left-stripe when active),
`TreeItem` (hover surface, active coral-glow), `SidebarSection` (label + count).

**Cards** — `StatCard`, `PreviewCard` (canvas-bg thumbnail + footer meta),
`QuickActionCard` (first one coral-accented).

**Canvas** — `FlowNode` (surface + coral-selected variant), `ActorNode` (circle +
purple glow), `AnimatedEdge` (dashed + keyframe), `FAB` (pulsing coral),
`AddPopup` (3 sections, stagger, `ObjRow` / `CreateTypeButton` / `AnnotationPill`),
`Minimap` (dot grid + colored rects + viewport rectangle).

**Feature diff** (later phase) — `FeatureTimelineCard`, `DiffCard` (side-by-side with
SOURCE·LIVE / DRAFT·PROPOSED halves), `DiffNodeBadge` (dashed green NEW / solid
amber MODIFIED with strikethrough diff), `ChangesModal`, `FullscreenDiffModal`.

---

## Scope phases

### Phase A — Foundation (blocks everything)

1. Install IBM Plex fonts (self-host via `@fontsource/ibm-plex-{sans,mono,serif}`
   to avoid Google Fonts call).
2. Extend Tailwind v4 `@theme` with the full color/shadow/keyframe/font token set.
3. Port reusable CSS from the reference into `@layer components`: `page-bg`,
   `canvas-bg`, `noise`, themed scrollbars, `fab-ring`, `popup-in`, `item-stagger`.
4. Build primitives (`Pill`, `Button`, `Kbd`, `SectionLabel`, `Pulse`,
   `LevelBar`, `Avatar`) under `frontend/src/components/ui/`.

**Exit criteria:** tokens compile, Storybook-style gallery route (`/design` dev-only)
shows every primitive.

### Phase B — Shell & navigation

5. Redesign sidebar (`components/nav/`): workspace switcher button, sectioned
   nav (Overview / Diagrams / Model Objects / Connections / Workspace /
   Team), bottom account block. Coral left-stripe active state.
6. Redesign top toolbar pattern used on every page: breadcrumb mono + context
   title + right-side search (`⌘K` kbd) + primary action.
7. Add radial-gradient `page-bg` and window chrome on content areas.

**Exit criteria:** every existing page loads inside the new shell without regressions.

### Phase C — Overview page

8. Hero greeting (date section-label + h1 with serif-italic coral em-dash +
   mono entity counters) + online presence pill with `Pulse`.
9. Stats grid: total diagrams / model objects / connections / drafts-awaiting
   (pink-accented variant).
10. Recent diagrams grid (`PreviewCard` with SVG thumbnail over `canvas-bg`).
11. Activity stream + Quick-start column.

### Phase D — Diagrams list page

12. Folder sidebar: pinned / packs (colored folder icons) / C4 level filter
    using `LevelBar`.
13. Pack header (breadcrumb + h2 + meta) + toolbar (search / filters /
    list-grid toggle / create).
14. Table: sticky mono group headers, colored row icon tint-wells, level-bar
    column, status pills.

### Phase E — Canvas redesign

15. Redesign `FlowNode` type-pill / name / description / metadata-row /
    `● editing` presence indicator. Actor circle variant (purple glow).
16. Selected state: coral border + double glow. Keep React Flow edge system;
    restyle edges to match (animated dash for active edge, semantic colors).
17. Top bar: presence avatar stack (overlapping with panel border), breadcrumb,
    `DRAFT · UNSAVED` pill, Publish button.
18. Bottom-left zoom controls + bottom-center tag/filter tray + bottom-right
    minimap with viewport rectangle.
19. Right inspector redesign (reuse existing `EdgeSidebar` / `NodeSidebar`
    state, restyle with tech-stack pills, tags, connections list with
    coral-highlighted selected edge, owners avatar stack).
20. FAB + Add popup: pulsing coral button, 340px slide-out popup with three
    sections (object pool search / create-type grid / annotation pills).

### Phase F — Feature diff (deferred, new epic)

21. Feature diff timeline screen.
22. Side-by-side `DiffCard` with color-coded diff visual language.
23. Changes modal with grouped list.
24. Fullscreen diff modal with sync pan/zoom, sliding handle, collab pins,
    change navigator strip.

### Phase G — Polish

25. Noise overlay on windows (optional, gated by setting).
26. Animations tuning (reduced-motion respect).
27. Empty states and skeleton loaders in new style.

---

## Out of scope

- No backend changes required. Pure frontend refresh.
- No new data models. Feature-diff UI (Phase F) reuses existing draft/diff
  backend endpoints.
- Demo "screen switcher" harness from the reference HTML is a preview shell
  only — skip.

## Non-goals

- We don't match the reference 1:1; the intent is the *feel* (dark panel /
  mono metadata / coral accent / IBM Plex / semantic colors / subtle glow).
- No brand/marketing-site changes in this plan.

## Risks

- React Flow edge/node overrides may fight custom styling — validate early
  in Phase E.
- Self-hosting fonts increases bundle size; budget ~80 kB woff2 subset.
- `canvas-bg` dotted grid may conflict with React Flow's own `<Background />` —
  pick one, don't stack.

## Open questions

- Do we ship the AI bar (pink-tinted input at canvas bottom) now or defer
  until AI features epic is scheduled? Reference shows it prominently.
  **Current plan:** defer visual to AI epic.
- Should the workspace switcher be a real multi-workspace UX, or mock until
  multi-workspace backend lands? **Current plan:** render the styled button
  but keep it non-interactive for now.
