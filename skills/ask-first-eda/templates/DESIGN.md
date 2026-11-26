# Analysis report design

## Type scale

- Use the same system sans-serif stack for headings and body text. Use monospace for code.
- Keep body text at 1rem with comfortable leading. Limit running notes and captions to around 68ch.
- Set the title at 1.75–2.5rem and the opening conclusion at 1.375–1.875rem. Give the conclusion enough weight to stand out below the tabs.
- Use 1.25rem for section headings and 1.75rem for KPI values. Set KPI values and tables in tabular numerals. Align the value, numerator, and denominator columns to the end.

## Spacing

- Use the spacing scale from .25rem to 2rem. Keep labels close to values and captions close to their charts. Leave more space between groups.
- Give charts a thin border and an inset. Let cards reflow at narrow widths and keep horizontal table scrolling inside the table wrapper.
- Use space, weight, and borders to organize the page. Keep chart artwork on white in both themes.

## Color tokens

- Use `--paper` for the page, `--surface` for quiet blocks, and `--line` for separators. Set body text in `--ink` and supporting text in `--muted`.
- Use `--accent` for KPI values, selected tabs, and focus. Keep conditional badges on their paired background and text tokens.
- Define the light palette at the root and override it for the system dark preference. Keep fonts and chart content available offline.

## Contrast

- Keep `--ink`, `--muted`, and `--accent` at 4.5:1 or higher against `--paper` in each theme. Check text on tinted surfaces as well.
- Pair color with a visible tab underline, toggle direction, or focus outline so state remains apparent.

## Interaction

- Start on the Summary tab. Use the radio controls for keyboard tab selection and keep keyboard focus visible on the label.
- Start the Details tab with Charts open. Keep each section toggle operable with the keyboard and respect reduced motion on its indicator.
- Use the same labeled checkbox to zoom in and close a summary chart. Show a localized close hint while enlarged and keep the image and caption in the reading order.

## Print

- Use a light print palette. Show both panels and expand all section toggles. Hide the interactive controls and let tables use the printable width.
- Keep KPI cards, figures, and table rows intact where page space allows. Wrap long code lines on paper.

Design review informed by the Impeccable skill (Apache-2.0)
