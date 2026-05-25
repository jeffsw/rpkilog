# rpkilog Web — UI Kit

High-fidelity recreation of the **rpkilog.com** RPKI history search web UI, built as React components.

## What's here

| File | Role |
|---|---|
| `index.html` | The interactive prototype — drop-in mock of the live site |
| `AsciiWordmark.jsx` | Figlet-style block-letter `rpkilog` mark for the page header |
| `LedePanel.jsx` | The canonical four-paragraph intro block |
| `SearchFieldset.jsx` | The `<fieldset>` + `<legend>` "RPKI History Search" form |
| `Inputs.jsx` | `<TextInput>`, `<Button>`, `<Label>` primitives |
| `ResultsTable.jsx` | Stripe-row result table + `took/shards/hits` line |
| `Pagination.jsx` | Flat row of amber page numbers |
| `data.js` | Deterministic fake-VRP record generator |

## Try it

Open `index.html`. The default search shows fake records for `8.8.8.0/24`. Change the **Prefix** or **ASN**, click **Search** — the table re-populates with a new deterministic set. Click any page number at the bottom to flip pages.

## Faithfulness caveats

This kit was rebuilt **from a single screenshot** of the live site (`uploads/rpkilog_screenshot_20260524a.png`) plus general knowledge of the RPKI domain. We did **not** have GitHub access to the [`jeffsw/rpkilog`](https://github.com/jeffsw/rpkilog) repo when this kit was assembled.

Known places where we may have drifted from the production code:

- **Exact phosphor green hex** — we chose `#33cc66`; production may use a brighter or differently-saturated value.
- **Font stack** — we use VT323 + IBM Plex Mono; production appears to use the user agent's default monospace stack.
- **Calendar input chrome** — we approximate with a styled text input rather than the browser-native `<input type="datetime-local">` widget visible in the screenshot.
- **Trust anchor labels** — we render trust anchors as plain lowercase text. Production may render them as links to the corresponding RIR.
- **Pagination row count** — we cap at 50 visible page numbers; production appears to render all of them inline.

If you have access to the repo, open `index.html`, compare it to the live site side-by-side, and adjust the specific component files. The system tokens in `../../colors_and_type.css` are the right place to tune colors and type globally.

## How the components compose

```jsx
<AsciiWordmark />            {/* hero, top of page */}
<LedePanel />                {/* intro paragraphs */}
<SearchFieldset onSearch />  {/* the form */}
<ResultsTable                {/* the table */}
  rows={result.rows}
  took={result.took}
  shards={result.shards}
  hits={result.hits}
/>
<Pagination page pageCount onChange />
```

The components are deliberately small and cosmetic — they do not implement a real OpenSearch query. Substitute `RpkilogData.search()` with a real `fetch()` against the rpkilog API to wire this up to production.
