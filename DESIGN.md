---
name: Aisomedo
description: Plain, modern, powerful Turkish-language publishing workspace.
colors:
  light-canvas: "#f7f9fc"
  light-surface: "#ffffff"
  light-surface-soft: "#f0f4f9"
  light-text: "#0d1b31"
  light-muted: "#61718b"
  light-line: "#dce4ef"
  light-accent: "#2563eb"
  light-accent-hover: "#1d4ed8"
  light-accent-soft: "#eff5ff"
  light-success: "#008568"
  light-danger: "#c52d43"
  light-danger-soft: "#fff1f2"
  light-warning: "#7b4c0d"
  light-warning-soft: "#fff5e5"
  light-selection: "#dbe9ff"
  dark-canvas: "#080d15"
  dark-surface: "#101827"
  dark-surface-soft: "#172234"
  dark-text: "#f1f5fc"
  dark-muted: "#93a6c2"
  dark-line: "#223047"
  dark-accent: "#5195ff"
  dark-accent-hover: "#78adff"
  dark-accent-soft: "#172b4b"
  dark-success: "#00c997"
  dark-danger: "#ff7788"
  dark-danger-soft: "#321e2a"
  dark-warning: "#f4c57d"
  dark-warning-soft: "#30271b"
  dark-selection: "#24416b"
typography:
  headline:
    fontFamily: '"Manrope", "Segoe UI", sans-serif'
    fontSize: "clamp(1.7rem, 3vw, 2rem)"
    fontWeight: 800
    lineHeight: 1.25
    letterSpacing: "-.04em"
  section:
    fontSize: "1rem"
    fontWeight: 750
  title:
    fontSize: "1.25rem"
    fontWeight: 750
    lineHeight: 1.4
    letterSpacing: "-.02em"
  body:
    fontFamily: '"Manrope", "Segoe UI", sans-serif'
    fontSize: "15px"
    lineHeight: 1.65
  button:
    fontSize: ".875rem"
    fontWeight: 600
  navigation:
    fontSize: ".8125rem"
    fontWeight: 600
  metadata:
    fontSize: ".8125rem"
  numeric:
    fontFamily: 'ui-monospace, "Cascadia Code", Consolas, monospace'
rounded:
  control: "6px"
  brand: "8px"
  panel: "10px"
  media-card: "12px"
spacing:
  compact: "4px"
  small: "8px"
  label: "12px"
  control: "16px"
  mobile-panel: "20px"
  panel: "24px"
  column: "28px"
  section: "32px"
components:
  button-primary:
    backgroundColor: "{colors.light-accent}"
    textColor: "{colors.light-surface}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.light-accent-hover}"
  button-secondary:
    rounded: "{rounded.control}"
    typography: "{typography.button}"
    padding: "9px 16px"
  button-danger:
    rounded: "{rounded.control}"
    typography: "{typography.button}"
    padding: "9px 16px"
  input:
    rounded: "{rounded.control}"
    padding: "10px 12px"
  navigation-link:
    typography: "{typography.navigation}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  status:
    typography: "{typography.button}"
  panel:
    rounded: "{rounded.panel}"
    padding: "24px"
  pending-panel:
    rounded: "{rounded.panel}"
    padding: "24px 28px"
---

# Design System: Aisomedo

## Overview

**Creative North Star: "A publishing workspace, not a social feed."**

Plain, modern, powerful: a blue/navy workspace for scanning task state and taking existing publishing actions. The seven user-approved `docs/design/*.png` references define the visual direction; `PRODUCT.md` defines the unchanged product. Unpictured pages use the same shell, panels, forms, and status language.

**Key Characteristics:**
- Cool canvas, quiet panels, fine borders, and blue action cues.
- Compact line icons, strong headings, and readable task-oriented density.
- Light and dark appearances with the same hierarchy and interactions.

Implementation authority: `web/src/styles.css`, `web/src/App.tsx`, and `web/src/theme.tsx`. Verification is recorded in `docs/design/redesign-progress.md`; independent review of all 32 desktop/mobile, light/dark captures returned **ship**, with no material fixes.

## Colors

Frontmatter records both palettes exactly. Each `light-*` / `dark-*` pair maps to the matching CSS custom property without its theme prefix (for example, `dark-surface-soft` maps to dark `--surface-soft`). Sidecar tonal ramps are synthesized preview aids, not additional application tokens.

### Primary
- **Workspace blue:** accent for links, current navigation, focus, progress, selection controls, and the pending-panel edge. Accent-soft supplies quiet active/action backgrounds; accent-hover supplies theme-aware interaction color.
- **Solid action blue:** primary buttons and the Aisomedo brand mark retain the light accent with white text in both themes. Primary-button hover likewise retains the light hover color; do not substitute the brighter dark accent here.

**The Solid Action Rule.** Keep primary buttons blue with white text in both themes; use the theme accent for links, focus, and active navigation.

### Neutral
- **Cool paper / midnight canvas:** page background.
- **White / navy surface:** sidebar, cards, forms, and dialogs; surface-soft distinguishes inset controls and supporting information.
- **Ink / pale text:** primary copy; muted colors carry descriptions and metadata; line colors define panel boundaries and row dividers.
- **Selection:** theme-specific text and timeline selection fill.

### Semantic states
Success is teal; danger is red; warning is amber. Danger-soft and warning-soft back destructive hover and notices. Keep visible status words and error explanations alongside color.

Appearance initially follows `prefers-color-scheme`, including system changes until overridden. The toggle remembers an explicit light/dark choice in `localStorage` under `dojo-theme`; storage failure does not prevent switching. The implementation has no separate system-reset control.

## Typography

Manrope is the shared variable face, self-hosted at `web/public/fonts/manrope-variable.ttf` (weights 200–800, normal, `font-display: swap`), with Segoe UI and sans-serif fallbacks. Dates, time readouts, and duration summaries use the system monospace stack and tabular numerals where specified. No additional font is required.

The headline role is the page h1; section is the compact h2; title is the default h3. Body supplies the inherited rhythm. Supporting text and controls use the smaller frontmatter roles. Desktop h3 reduces to `1.2rem` at the mobile-shell breakpoint; panel-specific headings keep their existing overrides. Uppercase is confined to existing compact summary/connection labels, not page headings or buttons.

Font provenance: [Google Fonts Manrope variable TTF](https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/Manrope%5Bwght%5D.ttf); [SIL Open Font License](https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/OFL.txt), distributed locally as `web/public/fonts/OFL.txt`. No external font request at runtime.

## Layout

- Desktop shell: sticky, vertically scrollable sidebar (248px), five navigation links, paired-browser identity and appearance control at the bottom. Main content has a maximum width of 1320px and padding `24px 32px 60px 56px`.
- Heading/divider precedes content. Dashboard pending panel spans the width, then publishing information and connections form a `1.4fr / minmax(260px, 1fr)` grid with a 28px gap. Package panels stack; activity uses divided rows; settings uses two equal columns.
- Shared panels generally use 24px padding and 24–32px separation. Media cards wrap; open editors expand to full width. Long text wraps and grid children can shrink rather than force page overflow.
- At **1000px and below**: dashboard becomes one column, main horizontal padding becomes 28px, and pairing gap narrows.
- At **900px and below**: video section editor stacks.
- At **800px and below**: setup stacks and its step navigation becomes horizontally scrollable.
- At **700px and below**: sidebar becomes a compact top region with two-column navigation; appearance control moves top-right (36px minimum height). Main padding becomes `24px 16px 40px`; shared panels use 20px padding. Settings, review, and pairing stack; action/activity rows become vertical. Panel tools wrap without dropping actions.
- At **600px and below**: optional setup cards stack and upload headings stack. At **500px and below**: range-field pairs stack.

## Elevation & Depth

Fine borders and tonal layering do most of the work. Light panels use `--shadow`; dark panels have no resting shadow. The brand mark has a small blue glow; editor dialogs use a larger soft shadow and dim backdrop. Exact shadow values are in the sidecar. There are no decorative gradients or floating feed-like tiles.

## Shapes

Controls and navigation have gently curved corners; panels are slightly softer; media cards use the largest shared radius. Boundaries are generally 1px. Current navigation adds a narrow blue marker (3px), and the pending panel deliberately retains the reference's blue left edge (4px). Avoid converting status text to decorative pill badges.

## Components

- **Buttons:** minimum height 44px, compact semibold labels; secondary uses surface/text/line and accent-soft hover. Primary stays solid blue/white in both themes. Danger uses danger text and border with danger-soft hover. Disabled buttons use opacity `.55` and a not-allowed cursor.
- **Inputs:** theme surface, text, fine border, and muted placeholders; standard inputs have minimum height 44px. Textareas resize vertically where specified. Keep native file/select controls and existing validation, fieldsets, labels, and error text.
- **Navigation:** compact line icons (18px), text labels, and `aria-current="page"`. Hover uses surface-soft; current page uses accent-soft, accent text, stronger weight, and the left marker. Setup uses the same accent treatment with `aria-current="step"`.
- **Panels:** surface, line border, panel radius, and theme shadow. Shared heading rows reserve room for tools and a 44px toggle. Preserve existing collapsed/expanded defaults. The pending variant adds the reference-led accent edge and quieter blue action links.
- **Status and notices:** status is colored text, not a chip. Warning notices use semantic background/text with wrapping actions. Activity is a divided list, not a card grid. Upload progress, timeline selection, media editing, review, completed packages, setup, and pairing retain their existing controls in this vocabulary.
- **Accessibility and motion:** preserve the keyboard skip link to focusable main content, visible labels, accessible icon-button names, alerts/status announcements, dialog focus behavior, confirmations, and permissions. Focus-visible uses a 3px accent outline with 3px offset. Most buttons/action links are at least 44px high; the mobile appearance toggle is the documented 36px exception. Color never replaces status text. Buttons and sidebar links transition only background, border, and text color (`140ms ease-out`) when `prefers-reduced-motion: no-preference`; no added movement.

## Do's and Don'ts

### Do:
- Do reuse the shared shell, panel, form, navigation, and status vocabulary on every page.
- Do preserve existing actions, content, validation, permissions, confirmations, panel defaults, and live updates.
- Do check both themes and narrow layouts, retaining visible keyboard focus and readable status text.

### Don't:
- Don't introduce social-media styling, invented metrics, decorative imagery, or new functionality.
- Don't add fonts, UI dependencies, or speculative tokens to extend this visual system.
- Don't remove the screenshot-led pending-panel accent edge or replace the fixed blue/white primary-button treatment.
