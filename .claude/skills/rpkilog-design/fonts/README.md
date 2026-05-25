# Fonts

This system uses two web fonts, both loaded from **Google Fonts** via `@import` in `colors_and_type.css`:

| Family | Role | Google Fonts URL |
|---|---|---|
| **VT323** | Display / hero / big numerals | https://fonts.google.com/specimen/VT323 |
| **IBM Plex Mono** (400, 500, 600, 700) | Body / UI / tables / forms | https://fonts.google.com/specimen/IBM+Plex+Mono |

## ⚠️ Caveat — font substitution

These are **substitutes for an unverified original**. The live rpkilog.com site uses the user agent's default monospace stack (we did not have repository access to confirm a specific declared font). VT323 + IBM Plex Mono are the closest faithful pair for the BBS / green-screen aesthetic we documented:

- **VT323** is a direct modern revival of the IBM VT terminal typeface — exactly the look of the era.
- **IBM Plex Mono** is the accessible, modern-readable body face that pairs with it.

If the user prefers a different mix (e.g. **IBM 3270** for display, **Berkeley Mono** for body, or a more pixel-perfect MS-DOS font), please drop the `.ttf` / `.woff2` files into this folder and replace the `@import` at the top of `colors_and_type.css` with local `@font-face` declarations.

## Self-hosting (recommended for offline / production)

If you need offline support or want to avoid the Google Fonts CDN, download:

- VT323: https://fonts.google.com/download?family=VT323
- IBM Plex Mono: https://fonts.google.com/download?family=IBM%20Plex%20Mono

…unpack the `.ttf`s into this folder and replace the `@import` line at the top of `colors_and_type.css` with:

```css
@font-face {
  font-family: "VT323";
  src: url("fonts/VT323-Regular.ttf") format("truetype");
  font-display: swap;
}
@font-face {
  font-family: "IBM Plex Mono";
  src: url("fonts/IBMPlexMono-Regular.ttf") format("truetype");
  font-weight: 400;
  font-display: swap;
}
/* …repeat for 500/600/700 weights */
```
