---
name: rpkilog-design
description: Use this skill to generate well-branded interfaces and assets for rpkilog (rpkilog.com — an RPKI history search service), either for production or throwaway prototypes/mocks. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping in a 1980s/1990s BBS / green-screen-terminal aesthetic.
user-invocable: true
---

Read the `README.md` file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## Files at a glance

- `README.md` — Brand context, content fundamentals, visual foundations, iconography rules
- `colors_and_type.css` — All design tokens (color vars, type, spacing, motion) + semantic classes
- `fonts/README.md` — Font choices (VT323 + IBM Plex Mono) and self-hosting instructions
- `assets/` — Logos and small marks (`logo.svg`, `logo-inline.svg`, `cursor.svg`, `wordmark-figlet.txt`)
- `preview/` — One-concept-per-file design system cards
- `ui_kits/rpkilog_web/` — Recreation of the rpkilog.com web UI in React/JSX (reference only)
- `ui_kits/rpkilog_web_vanilla/` — Same UI kit in plain HTML/CSS/JS. **Use this one for production work on the rpkilog vanilla site.** Has a `components.html` with anchored snippets (`#fieldset`, `#table`, etc) suitable for direct copy-paste.

## Quick start

1. Read `README.md` end-to-end. The CONTENT, VISUAL, and ICONOGRAPHY sections are non-negotiable.
2. Link `colors_and_type.css` at the top of any HTML you generate. Use the `--rk-*` CSS variables.
3. For any UI surface, look in `ui_kits/rpkilog_web/` for an existing component pattern before inventing one.
4. Forbidden by default: emoji, gradients, drop shadows, rounded corners, sans-serif fonts, easing curves softer than `linear`, durations over 120ms, blurred/translucent surfaces, "platform" or "AI-powered" marketing language.
5. Required defaults: pure `#000` background, IBM Plex Mono body, phosphor green `#33cc66` foreground, amber `#e6d24a` links, sharp 1px borders, ISO-8601 timestamps, lowercase trust anchors, UPPERCASE verbs.

## When in doubt

The product is a **terminal-era tool for network engineers**. Copy is terse and lowercase-leaning. Interfaces are dense and tabular. Animation is mechanical. If a design choice would feel at home in a 1989 BBS, it probably belongs. If it would feel at home in a 2023 SaaS landing page, it almost certainly does not.
