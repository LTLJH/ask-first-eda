# EDA evaluation cases

| Case | Input | Flows | Availability |
|---|---|---|---|
| throughput_hourly | Hourly line log, CSV | A, B, C | Existing input.csv |
| orders_nested_json | Orders with nested items, JSON | B, C | Generation specification only |
| utility_batches_excel | Batch production and meter increments, Excel | B | Stage ③ design only |
| production_next_month | Next month of the messy production log, Excel, run with --prior-summary | B | Generated input.xlsx |

Each case tests a different decision or data structure. Runs with different interview flows or random seeds are variants of the same case.

## Interview flows

- A — Proceed on the definition supplied in the opening request. Report the result immediately. Follow up on remaining interview items without holding the result.
- B — Ask one evidence-based question at a time, wait for the relevant answer and use the confirmed definition.
- C — The metric choice remains unanswered. On an explicit stop, close the interview. If simulating silence, the runner closes the turn without a reply. Report dependent results only as labeled alternatives.

## Running a case

- `--condition prompted_rel` extends `prompted` by asking the analyst to use relative file paths in chat.
- `--opening-style {current,conversational}` defaults to `current`. The conversational style encourages questions when an unresolved choice affects the result.
- `--analyst-model` and `--analyst-effort` override `gpt-6.2-sol` and `medium`, respectively.
- `--dry-run` shows the selected style, analyst model, and effort. Actual runs record them in `meta.json`.

Use `--prior-summary PATH` to stage a `.summary.json` file from `docs/gallery` or `_private` at `eda-work/delivery/eda_summary.json` inside `work/`.

List input filenames in an `inputs: a.csv, b.xlsx` line above the first flow heading in `case.md`. Without that line, the runner stages only regular files matching `input.*`. Symlinks are rejected.
For reproducibility, `meta.json` records input SHA-256 fingerprints, the Git commit and dirty status, the staged skill hash when used, grader file hashes, and Python and package versions.

1. A fixture preparer uses gen_spec.md in a separate session. An independent verifier recomputes the expected values from the actual input before the case is released for evaluation.
2. Stage a clean analyst workspace containing only the input and the selected opening message from case.md. Give the analyst no access to the case directory, other flows, generation specification, answer key or rubric.
3. Only the user simulator receives `domain_card.md`. It replies in the card's language. If the card does not cover a question, it says the equivalent of “I don't know” in that language. Relay only the answer to the current question and preserve the interview transcript.
4. Collect `delivery/report.html` and `delivery/results.json` in both conditions, along with any `eda_summary.json` produced by the analyst. In a separate grading session, provide the input, selected request, transcript, artifacts and expected.json. The grader does not receive the simulator card.
5. Check the section 9 acceptance criteria in docs/requirements.md, including coverage, source integrity, interview log, reproducibility and agreement between HTML and JSON. Apply each flow's must, must_not and critical_failures.
6. Keep holdout keys, cards and revealing per-case feedback out of improvement sessions. Share only findings that cannot disclose holdout answers.

## Isolation

The analyst, simulator, and grader each use a temporary home outside the repository. When available, a copy of `auth.json` is stored with mode `0600` and deleted when the run ends, even on error. Only the simulator receives the domain card. The analyst's read boundary is checked after the run from recorded events, with no OS-level enforcement. A recorded analyst command accessing an external skill causes grading to fail.
Each role's Codex configuration disables bundled skills, plugins, and apps. The runner records these settings in `meta.json` under `skills_isolation`.
The analyst's `.zprofile` and `.bash_profile` prepend `<cache>/bin` to the login shell's `PATH`. The runner sets `ZDOTDIR` to the analyst's temporary home for analyst sessions and records this setup as `login_shell_path_fix: true` in `meta.json`.

## Grading priority

Apply the following order. Lower-priority strengths cannot offset a higher-priority failure.

1. Privacy and confidentiality.
2. Grounded numbers, populations, units and denominators.
3. Source-row traceability and reconciled transform counts.
4. Descriptive interpretation without causal claims.
5. Interview fidelity, stopping and conditional reporting.
6. Chart fit and evidence for each insight.

Metric matching prioritizes structured scope fields, rejects conflicting dates, and compares known units by dimension and conversion factor.
A flow's `sign_agnostic_metrics` permits a listed difference series to match with every date's sign reversed together. Mixed directions are mismatches.
Numeric grading uses visible HTML to fill gaps and to flag conflicting values for metrics matched in the summary. Missing or mismatched required metrics and invalid summaries fail grading.
Required metrics with unpaired numeric evidence (`unparsed`) or different, dimensionally unknown unit labels (`unverified`) receive `review` when there are no grading failures.
External cases use their own answer key, and recorded SHA-256 fingerprints must match the current input files.

Grading uses a blind evidence mapper for required metrics marked `missing` or `unparsed`, cleaning checks with unresolved columns, and failed value checks on exact alias columns. The mapper receives target descriptions and analyst excerpts. The evaluators verify cited locations and exact CSV headers, then compare the values against the case key in code. Runs reuse `evidence_map.json`, and `grade_run.py --remap` refreshes it. The cleaning checker uses saved column mappings and can request missing entries with `--map`. If mapping fails, the evaluators retain the original results and record the reason.

With the project's virtual environment active, run `python3 -I evals/cleaning_check.py --run <run_dir>` to verify a cleaned CSV from a run. The checker treats byte-identical copies as one, prioritizes recorded deliveries with a same-work-directory exclusion log, and breaks ties by delivery revision. It reruns the source-row audit and writes `cleaning_check.json`. List the single source file in the case's `inputs:` manifest. The case's `cleaning_expected.json` gives the `flow`, allowed `audit_args`, optional `cleaned_rows`, and checks keyed by source `sheet` and `row`. Use `must_not_keep` for forbidden rows, `values` with `column_aliases`, `kind`, and `any_of` for typed cells, and `tuples` for key-value pairs produced by expanding a source row.
The optional boolean `cleaning_required` defaults to `true`. When set to `false`, the check passes and records the reason. If a cleaned CSV exists, the checker also sets `unnecessary_cleaning` to `true` and records the rerun audit result for reference.
For runs with `cleaning_required: true` that finish with `simulator_end` and deliver no cleaned CSV, the checker returns `not_applicable` and the grader evaluates analysis-time filtering.
For each value, tuple key, or tuple value, the checker selects the column directly when exactly one CSV header equals a listed alias. With no unique exact alias, it uses a verified mapper selection when available or returns `review`. When a value comparison fails on the exact alias, the checker retries with a different verified header if the mapper supplies one and records both headers.
If the selected delivery has no exclusion log in its work directory, the checker uses the sole exclusion log recorded in `meta.artifacts` when that file is available.

[A/B summary](ab_summary.md) · [Installation smoke results](install_smoke.json)
