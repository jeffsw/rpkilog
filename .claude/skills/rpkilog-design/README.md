# rpkilog Design System

> A BBS-era / green-screen terminal design language for **rpkilog.com** — an RPKI history search service.

## What is rpkilog?

[rpkilog.com](https://rpkilog.com) is a public history search service for **RPKI** (Resource Public Key Infrastructure) data. RPKI is the cryptographic system used by network operators to authorize which Autonomous Systems (ASNs) are allowed to originate routes for which IP prefixes — it's a foundational piece of BGP route-origin validation on the modern internet.

rpkilog snapshots **VRP** (Validated ROA Payload) caches over time and lets operators search backwards through that history, by **prefix** or **ASN**, across all five RIR trust anchors (ARIN, RIPE, APNIC, LACNIC, AFRINIC). It's a tool built by and for network engineers — terse, fast, dense with data, and proudly utilitarian.

The service is created and maintained by [Jeff Wheeler (`jeffsw`)](https://github.com/jeffsw) and runs on AWS, backed by an OpenSearch/Elasticsearch cluster (the result footer that says `took: 203ms shards: 162 hits: 1775` is the giveaway). The source code lives at **[github.com/jeffsw/rpkilog](https://github.com/jeffsw/rpkilog)** — explore that repo to do a more faithful job designing around this product than this design system alone can support.

## Why this aesthetic?

rpkilog presents itself as a green-screen terminal: pure black background, bright phosphor-green monospace text, amber-yellow links, dark earth-tone row striping that recalls dBASE / Lotus 1-2-3 / FidoNet-era BBS displays. **This design system formalizes that aesthetic** into reusable colors, type, components, and copy rules so we can extend rpkilog without breaking its character.

It is unmistakably inspired by 1980s/1990s bulletin board systems and "green screen" CRT terminals — but tuned for modern accessibility (no scanline filters by default, AA-compliant contrast, real focus rings, sensible hit targets).

## Sources used to build this system

- **Live site screenshot:** `uploads/rpkilog_screenshot_20260524a.png` (captured 2026-05-24)
- **GitHub repository:** [jeffsw/rpkilog](https://github.com/jeffsw/rpkilog) — *not directly accessed in this build; reader is encouraged to browse it for the full picture, especially the front-end source and any HTML/CSS templates*
- **Live URL:** [rpkilog.com](https://rpkilog.com)

> ⚠️ **Caveat to the reader:** GitHub wasn't connected when this system was assembled, so the visual rules were derived from a screenshot of the live site plus general knowledge of RPKI tooling. Browsing the [`jeffsw/rpkilog`](https://github.com/jeffsw/rpkilog) repo directly will let you confirm exact CSS values, find any logo assets we may have missed, and adapt this system to match the production code more closely.

---

## Index

| File / Folder | What it is |
|---|---|
| `README.md` | This file — context, content rules, visual foundations, iconography |
| `SKILL.md` | Agent Skill manifest — load this in Claude Code or similar |
| `colors_and_type.css` | All design tokens: color vars, type scale, fonts, semantic classes |
| `fonts/` | Web font files (VT323, IBM Plex Mono) |
| `assets/` | Logos, ASCII-art marks, sample illustrations |
| `preview/` | Design-system cards rendered for the Design System tab |
| `ui_kits/rpkilog_web/` | High-fidelity recreation of the rpkilog.com web UI (React/JSX) |
| `ui_kits/rpkilog_web_vanilla/` | Same UI kit, zero-framework. Plain HTML/CSS/JS for production use |

---

## CONTENT FUNDAMENTALS

rpkilog's copy is the copy of a **sysadmin who respects your time**. It is terse, technical, lowercase-leaning, slightly self-deprecating, and assumes the reader already knows what RPKI, a prefix, an ASN, and a trust anchor are. No marketing.

### Voice
- **First person, singular and plural.** The maintainer speaks directly: *"Please give me a star if this helps you."* / *"Thanks!"*
- **Direct address to "you", the network operator.** *"If you work there and can help get this project sponsored, please reach out."*
- **No corporate "we." No mission statement. No tagline.**

### Tone
- **Honest about state.** *"rpkilog.com is available for use, but please consider it a work-in-progress!"* — flaws are surfaced, not hidden.
- **Plain about asks.** *"Please give me a star if this helps you."* No begging, no manipulation; just a clear request.
- **Gracious about dependencies.** *"Thanks to Job Snijders for making his VRP cache snapshots available."* Credit is given by name.
- **No hype words.** Never "revolutionary," "powerful," "seamless," "next-gen," "AI-powered." Never "platform" or "solution."

### Casing
- **Sentence case for prose.** *"This service runs on AWS."*
- **lowercase domain names**: `rpkilog.com` always written in lowercase, even at the start of a sentence.
- **UPPERCASE for protocol verbs and operations**: `REPLACE`, `INSERT`, `DELETE`, `EXPIRE`. These come from RPKI semantics — preserve them as-is.
- **lowercase for column headers and form labels** in the search UI: `prefix`, `maxLength`, `asn`, `ta`, `expires`, `verb`, `observation_timestamp`. camelCase where it matches the underlying field name.
- **Trust anchor names**: lowercase (`arin`, `ripe`, `apnic`, `lacnic`, `afrinic`) — they're identifiers, not brands.

### Punctuation & symbols
- **Exclamation points are allowed**, sparingly, to soften an otherwise dry sentence: *"Thanks!"* / *"...consider it a work-in-progress!"*
- **No emoji.** None. Ever. The terminal aesthetic cannot accommodate them.
- **No em-dashes for drama.** Use them only for parenthetical asides.
- **ISO-8601 timestamps everywhere** (`2026-05-24T14:14:07Z`). Never localized dates.

### Vocabulary cheat sheet
| Use | Don't use |
|---|---|
| prefix | network, IP range, CIDR block (in UI labels) |
| ASN | AS number, autonomous system number |
| trust anchor / `ta` | RIR, registry (when referring to the RPKI TA) |
| ROA / VRP | route object, certificate (when meaning a ROA) |
| observation_timestamp | seen at, observed on |
| `expires` | expiration, end of validity |
| service | platform, app, tool |

### Example copy in the rpkilog voice

> rpkilog.com is available for use, but please consider it a work-in-progress! There is an HTTP API but it should not yet be considered stable/supported. The source is available on GitHub: jeffsw/rpkilog. Please give me a star if this helps you.

> Thanks to Job Snijders for making his VRP cache snapshots available.

> This service runs on AWS. If you work there and can help get this project sponsored, please reach out by email.

> Thanks!

Note the structure: **state → ask → credit → ask → thanks.** Single-paragraph blocks. No headlines. The whole intro to the site is under 80 words.

---

## VISUAL FOUNDATIONS

### The core palette
The live site is built on **three colors plus one stripe color and a few accents**. Restraint is the point.

- **Background:** `#000000` — true black, no off-black. This is a CRT void, not a "dark theme."
- **Phosphor green:** `#33cc66` (primary foreground). This is the color of every body word, every table cell, every form label. Use sparingly *dimmer* greens for secondary text — never lighter.
- **Amber:** `#e6d24a` — links, calls to action, anchors, page-number nav. Underlined when interactive.
- **Stripe brown:** `#3a2a1a` — alternating table-row tint. Warm earth, not gray. This is the color of an old tube monitor's afterglow on dust.

Optional BBS accents — kept for legacy "system-y" surfaces (installer banners, dev overlays); not used for real status signaling:
- **DOS cyan:** `#33cccc` — installer / REPL banners, info-alt
- **DOS magenta:** `#cc33cc` — debug / dev-only callouts

### Status channels
Six redundant signal hues live alongside phosphor green. **Use one channel per surface — never combine two in the same view.** Use status color as a *redundant* signal on top of text or icons; never color-only.

| Token | Hex | Role |
|---|---|---|
| `--rk-green-500` | `#33cc66` | primary (ok / nominal) — also the body fg |
| `--rk-blue` | `#3399ff` | info / alt signal |
| `--rk-yellow` | `#ffcc33` | warning / pending — deliberately more saturated than the link amber so it doesn't read clickable |
| `--rk-gray` | `#8a948a` | inactive / disabled / muted (slightly green-tinted, not cold-neutral) |
| `--rk-red` | `#ff3a3a` | error / expired strikethrough |
| `--rk-fuchsia` | `#ff44bb` | attention / unusual — hue-separated from red so it remains distinguishable for protan/deutan vision |

### Type
- **Display / titles:** **VT323** (Google Fonts) — the classic IBM-VT terminal face. Used for hero text, section markers, big numerals.
- **Body / UI:** **IBM Plex Mono** — humane modern monospace. Used for every line of text in tables, forms, and prose. Weight 400 default, 600 for headers and emphasis.
- **There are no sans-serif or serif typefaces in this system.** Everything is monospace.
- **Numerals are tabular** (Plex Mono is tabular by default). Alignment in tables is non-negotiable.

### Spacing
A **4 px base grid**. Common steps: `0.25rem (4)`, `0.5rem (8)`, `0.75rem (12)`, `1rem (16)`, `1.5rem (24)`, `2rem (32)`. Tables use **2–4 px** of cell padding to maintain density; forms use **6–8 px**. Generous outer page padding (32–48 px) to keep content from kissing the bezel.

### Backgrounds
- **Always solid `#000`.** No gradients, no images, no hero photography, no blurred glass.
- The only "texture" is the **alternating row stripe** in tables (`#3a2a1a` on even rows).
- An *optional* tweakable CRT scanline overlay (off by default for accessibility) recalls a curved monitor without harming legibility.

### Animation
- **Minimal and instant.** No fades over 120 ms, no bounces, no spring physics.
- **Acceptable motions:**
  - Cursor blink (`1s steps(2)`, infinite) on text inputs and the page lede
  - 80 ms color flash on link hover/focus (green → amber)
  - 0 ms transitions on buttons (they should feel mechanical)
  - Optional `monospace typewriter` reveal on the page intro
- **Forbidden:** parallax, page transitions, easing curves softer than `linear`, anything with overshoot.

### Hover states
- **Links:** color flips from amber (`#e6d24a`) to **bright green (`#66ff99`)**, underline stays. No background change.
- **Buttons:** background inverts — green text on green-tinted (`#0e2a14`) background → black text on solid green (`#33cc66`) background. 0 ms.
- **Table rows:** the alternating stripe brightens by ~15% (`#4a3522`).

### Focus / press states
- **Focus ring:** 2 px solid `#e6d24a` (amber), 2 px outline offset. Visible on keyboard navigation. Never use the browser default blue.
- **Press:** buttons gain a **1 px inset border** (no shrink, no shadow change). Mechanical, like pressing a key.

### Borders
- **1 px solid** is the only border weight in normal UI.
- **Fieldsets** use a 1 px green border with the legend overlapping it (preserving the native `<fieldset>` look from the live site — that "RPKI History Search" header sitting on the line is iconic).
- **Tables** have no outer border by default; only horizontal cell separators (a 1 px `#1a3320`) and the row stripe handle visual separation.
- **Inputs** are bordered 1 px green; on focus the border brightens to amber.

### Shadows
- **No drop shadows.** None. A terminal has no light source.
- The only "shadow" effect permitted is the **CRT glow** — a soft `text-shadow: 0 0 4px currentColor` on the display typeface in hero contexts, off by default and exposable as a tweak.

### Protection gradients vs capsules
- **Capsules are forbidden.** No pills, no chips, no rounded-rect badges. If you need to mark a label, use **`[brackets]`** in text or a bordered box.
- **Protection gradients are forbidden.** Overlays must be solid `#000` with optional dotted/dashed borders.

### Layout rules
- **Single column.** rpkilog has no sidebar, no top nav, no footer chrome.
- **Page max-width: 1280 px**, centered with 32–48 px outer padding.
- **The page lede** sits at the top as a 2–4 line paragraph block. No hero card.
- **The search fieldset** sits directly below the lede, full width.
- **Result table** is full width, no max, scroll horizontally if needed.
- **Pagination** is a flat row of numbers at the bottom-left, prefixed with `Page:`.

### Transparency & blur
- **Forbidden.** Nothing is translucent. Nothing is blurred. The CRT is opaque.

### Imagery
- **No photography.** No illustrations. No 3D renders.
- **Acceptable imagery:**
  - **ASCII art** (the `rpkilog` wordmark in Figlet-style block letters)
  - **Box-drawing characters** (`╔═╗║╚╝├┤┬┴┼─│`) for decorative dividers
  - **Pixel-grid SVGs** with no anti-aliasing for any custom marks
- If full-bleed imagery is ever required, **black + green wireframe schematics** only.

### Corner radii
- **`border-radius: 0` everywhere.** Sharp corners. No exceptions. (The live site uses no rounding.)

### Cards
- **There are no cards in the modern sense.** A "card" in this system is a **bordered rectangle** with 1 px green border, black fill, sharp corners, internal padding of 16–24 px. No shadow, no rounding, no inner gradient.

### Color vibe of imagery
- **Cool green-dominant.** Any incidental graphics tint toward CRT phosphor green or amber. No warm pinks, no skin tones, no full-color photography. If grain is needed, it's **monochrome noise** at low opacity.

---

## ICONOGRAPHY

rpkilog uses **almost no icons**. The live site's iconography is effectively *zero* — every UI cue is conveyed in text, with the calendar input being the sole exception (it's the browser-native picker glyph from `<input type="datetime-local">`).

### Approach
- **Text-first.** Replace icons with words wherever possible: `[search]` not 🔍, `expand` not a chevron, `delete` not a trash can.
- **Box-drawing characters** are preferred when a non-text mark is needed: `┌─┐ │ │ └─┘`, `►`, `▼`, `◄`, `▲`, `■`, `□`, `●`, `○`.
- **ASCII art** for the wordmark/logo. The `rpkilog` mark in this system is a Figlet-style block-letter rendering (see `assets/logo.txt` and `assets/logo.svg`).
- **Unicode geometric shapes** for status: `●` (active), `○` (inactive), `■` (selected), `□` (unselected), `✓` (pass — used sparingly), `✗` (fail). Never check-circle SVGs.
- **No emoji.** None. The aesthetic forbids it.
- **No icon font.** The system intentionally does not ship an icon set — this is a discipline, not a gap. If you absolutely must add an icon, see the substitution rule below.

### Substitution rule (if you must)
If a future surface genuinely needs an icon set (e.g., a settings panel with mixed actions), substitute **[Lucide](https://lucide.dev)** at `1.25 rem`, `stroke-width: 1.5`, color `currentColor`. Choose the **outline** variants only — no filled shapes. **Flag the substitution in the file's header comment** so a future designer knows it's a departure from the canonical no-icon rule.

### SVGs in this system
- `assets/logo.svg` — the `rpkilog` ASCII wordmark rendered as monospace SVG text
- `assets/cursor.svg` — a single blinking green block, used as the lede cursor
- `assets/scanlines.svg` — a 1×4 tileable pattern for the optional CRT overlay
- `assets/wordmark-figlet.txt` — the raw ASCII wordmark, for terminal embeds

---

*Continued in the corresponding files. Start with `colors_and_type.css` and `ui_kits/rpkilog_web/index.html` to see this system in motion.*
