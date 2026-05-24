# rpkilog Web — Vanilla UI Kit

Zero-framework recreation of the rpkilog.com web UI. Same look as `../rpkilog_web/`, but written in plain HTML / CSS / JS — no React, no build step, no transpiler. **This is the kit to use as a reference when migrating the production site.**

## What's here

| File | Role |
|---|---|
| `index.html` | Full interactive prototype — drop-in mock of the live site |
| `components.html` | **Anchored snippet reference** — every component in isolation with copy-paste HTML next to it |
| `styles.css` | Component-scoped class rules (`.rk-fieldset`, `.rk-table`, `.rk-link`, etc) |
| `app.js` | Plain DOM rendering + event handlers (search, pagination) |
| `data.js` | Deterministic fake-VRP generator (same file as the React kit) |

Depends only on `../../colors_and_type.css` (the design tokens) — that's the only file you actually need to link from your production site.

## How to use this from Claude Code

When migrating an element on the live site, point Claude Code at the matching anchor in `components.html`:

> "Restyle the search form in `index.html` to match `.claude/skills/rpkilog-design/ui_kits/rpkilog_web_vanilla/components.html#fieldset`. Keep the existing event handlers."

Available anchors:

- `#wordmark` — ASCII figlet `rpkilog.com` mark
- `#lede` — intro copy block
- `#fieldset` — RPKI History Search container
- `#input` — text inputs (default / focused / disabled)
- `#button` — primary button + states
- `#stats` — `took / shards / hits` line
- `#table` — results table with stripe rows + expired + verb
- `#expired` — strikethrough date span
- `#verb` — UPPERCASE RPKI verb token
- `#link` — `<a class="rk-link">` styling
- `#pagination` — flat page-number row with `data-page` attrs
- `#cursor` — blinking cursor flourish
- `#status-icons` — six-channel status palette

## Production integration — recommended path

1. **Drop both `colors_and_type.css` and `styles.css`** into your site (or link them directly from the skill folder).
2. **Add to your page `<head>`:**
   ```html
   <link rel="stylesheet" href="path/to/colors_and_type.css">
   <link rel="stylesheet" href="path/to/styles.css">
   ```
3. **Migrate element-by-element.** For each existing element on rpkilog.com, find the matching component anchor here, apply the `.rk-*` class(es), and remove the old custom CSS. Most edits will be:
   - Add a class name to an element
   - Remove a competing hand-rolled CSS rule
   - Possibly tweak inline `style="width:…"` to match the form-row widths

4. **Add the flourishes last** (wordmark, cursor, status-icon coloring of verbs) once the foundation is solid.

## Faithfulness caveats (same as React kit)

Recreated from a screenshot of the live site, not from the source. See the parent `../rpkilog_web/README.md` for the full caveat list — the same applies here.
