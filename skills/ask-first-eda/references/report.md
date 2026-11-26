# Building the report

Use the [report input example](report_spec.example.json) for field names and nesting. Replace its values with verified results. The [sidecar schema](eda_summary.schema.json) describes the generated summary. Write prose, titles and axis labels in the user's language and keep JSON keys in English.

## Summary tab

- `headline` gives the conclusion in 1–2 sentences (up to 300 characters). Lead with a verified number, unit, population and source. State any partial coverage or condition alongside the value.
- `kpis` lists up to four metric names. A listed metric with empty `source_refs` stops the build. Empty `source_refs` for other metrics, including any legacy defaults, produce a warning.
- `key_charts` lists zero to two chart IDs. Write each selected chart's `domain_interpretation` as a one-line caption.
- `insights` lists up to three findings. For each, write one sentence with a verified number and unit in `text` (up to 200 characters) and cite the original location in `source`.

The builder rejects entries that exceed the count or character limits. Meta commentary and repeated sentences trigger warnings.

## Details tab

Select a section heading to expand or collapse it. Charts are open by default, and all sections expand in print.

1. **Charts.** Include every chart and its question. In `observation`, give the measured pattern, source, units, used and excluded counts (including zero) and reasons. Base `domain_interpretation` on confirmed context. Include `hypothesis` or `next_check` only when the evidence supports it.
2. **Assumptions & limitations.** Identify the affected result for each assumption, coverage gap or unresolved interpretation. Record the reason for each omitted chart view here.
3. **Ambiguity Log.** Use a table to account for all eight items with stable IDs, evidence, candidate answers, status, decision source and dependencies.
4. **Data overview.** Identify the selected tables, row grain, format evidence and extension conflicts. Give dimensions, read and unread ranges and reasons. For each Excel sheet, give the actual header rows and exact merged spans, “none” if verified or “unknown” with a reason.
5. **Metrics.** Include the full metric table with definitions, values, units, conditions and sources.
6. **Reproducibility.** Preserve filters, exclusions, transforms in order, before/after counts, sample sizes, original source locators and the code used for numbers and figures.

Always report quality findings for the analyzed scope. Include single-variable, relationship or time findings and domain metrics when the question and data support them. Use 2–4 charts by default, including a raw data figure. See the [figure selection criteria](methods.md#default-figures).

## Evidence and metrics

Use input filenames or paths relative to `$WORK` and retain original row, sheet or record coordinates. Record a join once for each input with its own before count and the same transform, output and after count. Reconcile unmatched rows, cardinality and additive totals.

For optional `datasets[].structure`, use confirmed header rows. Fill horizontally merged header cells, then join each column's nonempty header values from top to bottom with `" / "`. Mask sensitive column names. Store this structure in the sidecar for future input comparisons.

Define eligibility, window and weighting for each metric. Cite numerator and denominator sources separately when they differ. Store the unrounded result in `value` and round only in prose.
For a rate, verify numerator ÷ denominator × scale. The default scale is 100 for `%` and 1 otherwise. Set any other multiplier explicitly. Use null for undefined results or inapplicable components and explain why.

Compare candidate answers before display rounding with other definitions held fixed. Link an ambiguity ID only when changing its answer changes the value. Show unresolved alternatives side by side in a chart or table with each condition, numerical components, unit, source and shared ID. Keep questions affecting only interpretation in the log and limitations.

## Render and build

Adapt the [plot input example](plot_spec.example.json), which runs against its adjacent [synthetic CSV](plot_example.csv). Select only the charts that answer the user's questions. Relative source paths resolve from the plot spec directory. Pass any source file outside that directory with `--input`. Match the confirmed table, sheet, header or record path. For filtered or aggregated input, preserve the mapping to original rows in the analysis code.

```sh
python3 -I "$SKILL_DIR/scripts/plots.py" --spec "$WORK/plot-spec.json" --input "$INPUT" --outdir "$WORK/delivery/figures" > "$WORK/plot-results.json"
```

Match results to report charts by ID. With `--plot-results`, the builder checks each specified `type`, `source_columns`, `n_used`, `n_excluded` and `exclusion_reason` against the renderer and fills omitted fields from its results. Every renderer entry needs a report chart. A matched chart uses the renderer image path when available. A chart without a renderer image path needs a direct `image_path`. Copy any pairwise counts and verify the source table, locator, read extent and warnings. Distinguish upstream filters from rendering exclusions in each observation. Image paths must resolve within the report spec directory. If `missing_glyphs` lists characters, tell the user which are missing and recommend a system font that covers them.

Include the analysis code and its working directory. To use the bundled modules, set `SKILL_DIR` to the installed skill directory and follow the imports in the report example.

```sh
python3 -I "$SKILL_DIR/scripts/build_report.py" --spec "$WORK/report-spec.json" --outdir "$WORK/delivery" \
  --plot-results "$WORK/plot-results.json" --input "$INPUT"
```

Repeat `--input` for each original file. When input files are supplied, the sidecar includes `provenance` with their basenames and SHA-256 hashes, the skill and schema versions, and the versioned builder name. It also lists the hashes of referenced PNGs under the delivery `figures/` directory, with paths relative to the delivery directory. Without `--input`, the sidecar omits `provenance`. Builds without `--plot-results` use the chart metadata and image paths supplied in the report spec.

## Delivery checks

- Re-read every cited location in code. For a duplicate claim, compare both original rows on the key and fields used to identify the duplicate. Verify Excel headers, merged spans and skipped ranges against the workbook.
- Reconcile HTML and JSON values, units, conditions and source scopes with the calculation. Each conditional badge needs an unresolved answer that changes the metric.
- Open the HTML offline and verify the section order and embedded PNGs. Check labels, rare groups, paths, log entries and code for disclosures. Verify authored text and display labels in the user's language.
- Deliver `report.html`, `eda_summary.json` and `figures/` together. Follow [Step 5](../SKILL.md#step-5--report) for the chat handoff and text fallback if an output fails.
