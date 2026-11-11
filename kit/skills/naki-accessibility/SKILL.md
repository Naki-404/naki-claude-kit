---
name: naki-accessibility
description: Accessible web UI to WCAG 2.2 Level AA: semantic HTML, keyboard operation, focus management, contrast, forms and errors, dynamic content, and screen reader checks. Use when building or reviewing UI components, forms, dialogs, menus or tables, or when auditing a page for keyboard and screen reader support.
---

# Accessibility (WCAG 2.2 AA)

Accessible UI is mostly correct HTML plus keyboard and focus discipline. ARIA fills gaps; it does not
replace native elements. Pair with `naki-react` and `naki-frontend-testing`. Follow the project rules skill
if the project has one (for example `naki-myapp`).

## When to use

- Building any interactive component: buttons, forms, dialogs, menus, tabs, tables, toasts.
- Reviewing a UI diff.
- Auditing a page before a demo or release.

## Core rules

1. **Use native elements first.** `<button>` for actions, `<a href>` for navigation, `<label>` for inputs,
   `<table>` for tabular data, headings in order. A native element brings keyboard support and roles for free.
2. **Everything works with the keyboard.** Tab reaches every control in a logical order, Enter/Space activate,
   Escape closes overlays, arrow keys move inside composite widgets (tabs, menus, listboxes).
3. **Focus is always visible** (WCAG 2.4.7) and not hidden behind sticky headers (2.4.11). Never
   `outline: none` without a clear replacement such as `:focus-visible` styles.
4. **Every control has an accessible name.** Visible label preferred; `aria-label` for icon-only buttons.
   The visible text should be part of the accessible name (2.5.3).
5. **Contrast:** 4.5:1 for normal text, 3:1 for large text (18.66px bold or 24px), 3:1 for UI component
   borders, focus indicators and meaningful icons (1.4.3, 1.4.11).
6. **Do not convey meaning by color alone.** Add text, an icon with a label, or a pattern (1.4.1).
7. **Target size at least 24 by 24 CSS pixels** or enough spacing (2.5.8).
8. **Forms:** each input has a programmatic label, required fields are marked in text, errors are described
   in text next to the field and linked with `aria-describedby`, focus moves to the first error on submit.
9. **Manage focus on context changes.** Opening a dialog moves focus inside it and traps it; closing returns
   focus to the trigger. Route changes move focus to the main heading.
10. **Announce dynamic updates** with live regions (`role="status"` for polite, `role="alert"` for urgent),
    rendered in the DOM before the message changes.
11. **Images:** meaningful images get descriptive `alt`, decorative images get `alt=""`.
12. **Respect user settings:** `prefers-reduced-motion`, zoom to 200 percent and reflow at 320px width
    without horizontal scrolling (1.4.10).
13. **ARIA rules:** no ARIA is better than wrong ARIA. Do not put `role="button"` on a `div` when a
    `<button>` works. If you use a role, implement its full keyboard contract.

## Component patterns

| Component | Must have |
|---|---|
| Icon button | `<button type="button" aria-label="Delete alert">` with the icon `aria-hidden="true"` |
| Toggle | `<button aria-pressed={on}>` or a checkbox |
| Dialog | native `<dialog>` with `showModal()`, or `role="dialog"` + `aria-modal` + `aria-labelledby`, focus trap, Escape closes, focus returns |
| Tabs | `role="tablist"`, `tab` with `aria-selected` and `aria-controls`, arrow key navigation, one tab in tab order |
| Disclosure | button with `aria-expanded` controlling a region |
| Data table | `<th scope="col">`, `<caption>`, sortable header buttons with `aria-sort` on the `th` |
| Toast | live region present on load; do not auto-dismiss errors |
| Skip link | first focusable element, jumps to `<main id="main">` |

## Workflow

1. Write semantic HTML for the component before styling.
2. Tab through it: order logical, focus visible, nothing trapped by accident.
3. Operate it with keyboard only, including Escape and arrow keys where applicable.
4. Check names and roles in the browser accessibility tree (DevTools, Accessibility pane).
5. Run an automated check (axe DevTools, Lighthouse, or `@axe-core/playwright` in e2e). Automated tools find
   roughly a third of issues; manual checks are still required.
6. Spot check with a screen reader: NVDA (Windows, free) with Firefox or Chrome, VoiceOver on macOS/iOS.
7. Zoom to 200 percent and narrow the window to 320px.

## Examples

Field with error message:

```tsx
<label htmlFor="email">Email (required)</label>
<input
  id="email"
  type="email"
  autoComplete="email"
  aria-invalid={!!error}
  aria-describedby={error ? "email-error" : undefined}
/>
{error && <p id="email-error">{error}</p>}
```

Status announcement:

```tsx
// Render once at page level, then change its text.
<div role="status" aria-live="polite" className="sr-only">{statusMessage}</div>
```

Visually hidden but readable text:

```css
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
:focus-visible { outline: 3px solid #1a5fb4; outline-offset: 2px; }
```

Severity badge that does not rely on color:

```tsx
<span className={`badge badge-${level}`}>
  <SeverityIcon level={level} aria-hidden="true" /> {level.toUpperCase()}
</span>
```

## Checklist

- [ ] Native elements used for buttons, links, inputs, tables.
- [ ] Full keyboard operation; visible focus; no keyboard traps.
- [ ] Every control has an accessible name; icons hidden from assistive tech when decorative.
- [ ] Contrast meets 4.5:1 text and 3:1 UI.
- [ ] Color is not the only signal.
- [ ] Form errors in text, linked to fields, focus moved on submit.
- [ ] Dialogs trap and restore focus; Escape closes.
- [ ] Dynamic updates announced via live regions.
- [ ] Headings in order, one `h1`, landmarks (`header`, `nav`, `main`).
- [ ] Works at 200 percent zoom and 320px width; reduced motion respected.

## Common mistakes

| Mistake | Fix |
|---|---|
| `<div onClick>` as a button | `<button type="button">` |
| Placeholder used as label | real `<label>` |
| `outline: none` globally | `:focus-visible` style |
| Live region inserted together with its message | keep the region mounted, change its text |
| `aria-label` on a `div` with no role | give it a role or use visible text |
| Disabled submit with no explanation | keep enabled, show errors on submit |
| `tabindex="5"` to fix order | fix DOM order; use only `0` or `-1` |
| Red/green status dots only | add text labels |
