# EDA skill architecture

The user decides what a row represents, which records count toward a metric and which cleaning rules to apply. The LLM uses the interview to settle those choices, writes Python for the current input and explains the results. Bundled Python tools inspect and profile tables, audit row coverage, draw figures and validate the report. Files connect these steps so a contributor can trace a headline number back to its definition and source rows.

## Component map

```text
skills/ask-first-eda/                         Copied into the user's project
  SKILL.md + references/            Guide the interview, analysis and delivery
  scripts/eda_io.py                 Shared readers, table selection and safe writes
    inspect_data.py, profile_data.py  -> inspection.json, profile.json
    audit_clean.py                    -> row coverage verdict
    plots.py                          -> figures/*.png and chart metadata
    build_report.py + templates/      -> report.html and eda_summary.json

WORK/                               Fresh directory for one analysis
  clean.py, excluded.csv            Created when cleaning runs
  plot-spec.json, report-spec.json  Working inputs for rendering
  delivery/                         HTML, summary and figures/
                                    Also cleaned_*.csv and clean.py after cleaning

evals/                              Development only
  cases/ -> run_case.py             Analyst and user simulator in separate sessions
  numeric_check.py, grade_run.py    Numerical checks and independent grading
  ab_summary.py                     Summarizes comparisons across runs
```

## Stage contracts

| Stage | Inputs → outputs | What gets checked |
| --- | --- | --- |
| Inspect | Source file → `inspection.json` | The inspector records format evidence, candidate tables and unread ranges. The analyst confirms the scope before quoting a total. |
| Profile | Source file and selected table → `profile.json` | The loader requires an unambiguous selection. The profile ties counts and duplicate examples to the selected rows. |
| Clean | Source, approved rules and fresh `clean.py` → `cleaned_*.csv` and `excluded.csv` | Proceed only after `audit_clean.py` returns `pass`. Each expected source row must appear in the cleaned copy or have a reason in the exclusion log. For Excel, `--sheets` takes a comma-separated list of approved sheets and defaults to all sheets. Reconcile totals separately. |
| Analyze | Selected data (audited CSV after cleaning), profile and interview log → metric entries and chart specifications | Session code computes the values and retains source references. An unexplained increase in rows after a join blocks calculations that depend on it. |
| Plot | `plot-spec.json` and its source table → PNGs and `plot-results.json` via stdout | The renderer checks chart IDs and types. The analyst matches its metadata to report entries by ID and checks sample sizes and exclusions. |
| Build report | `report-spec.json` and PNGs → `report.html` and `eda_summary.json` | `build_report.py` enforces the [summary schema](https://github.com/LTLJH/ask-first-eda/blob/main/skills/ask-first-eda/references/eda_summary.schema.json) and checks rates and IDs. Metric dependencies must reference existing ambiguity IDs. An unresolved dependency requires a condition. |
| Test the CLI documentation | Commands in `SKILL.md` and each referenced script's `--help` → pytest result | `tests/test_skill_docs.py` checks documented command options and requires `--cleaned` and `--excluded` together in the audit command. |

For a zero denominator, the rate check requires a null value. Otherwise it skips arithmetic if any component is null. For numeric components it compares the reported value with `numerator / denominator × scale`. The optional positive `scale` defaults to 100 for the unit `%` and 1 for other units. The tolerance is `1e-9` times the absolute expected value. An expected value of zero requires an exact zero.

## User journey × component

| Step | Component | What the user sees or decides |
| --- | --- | --- |
| Discover | [README](https://github.com/LTLJH/ask-first-eda/blob/main/README.md), [gallery](gallery/index.html) and [walkthroughs](walkthroughs/) | Open a finished report and see how an interview answer affects a calculation. |
| Install | README and `skills/ask-first-eda/requirements.txt` | Install the Python dependencies and copy the skill directory into the client's skills folder. |
| First run | `inspect_data.py` and `SKILL.md` | See the tables and coverage, get any settled metrics, and answer at most one opening question. |
| Interview | `profile_data.py` and the ambiguity log | Choose among definitions using evidence from specific rows. Deferred choices stay open. |
| Clean | Session's `clean.py` and `audit_clean.py` | Review the numbered plan and confirm changes that affect results. Receive the audited copy and the script that produced it. |
| Report | `plots.py` and `build_report.py` | Read the findings in chat and open the report for figures, definitions and source evidence. |
| Follow up | Session analysis code and both renderers | For a changed definition, recompute affected steps from the raw input, update both specs and build a complete `delivery-2/` (next free number). If either spec is missing, start a fresh analysis. |
| Share | `delivery/report.html` | Send the single HTML file. Its embedded charts open offline. |
| Reuse next month | New inspection and previous `eda_summary.json` | Review eligible definitions from a matching analysis and confirm which to carry forward. |

## Persistence and reuse

`delivery/eda_summary.json` is the only persistent record the skill uses to carry decisions between analyses. Its optional `datasets[].structure` object contains `sheet`, `header_rows`, `record_path` and ordered `column_names`. Mask sensitive column names before saving. The builder omits this object from the HTML.

1. Inspect the new input. Compare the confirmed header rows, ordered columns and record path for every table. File and sheet names only rank candidates. Skip reuse if the summary is unreadable, lacks structure or differs on any table.
2. Offer only answers marked `resolved` or `user_assumed` and approved cleaning rules. Check referenced values and units against the new input. Ask the user to confirm reuse and record the summary's relative path in the ambiguity log.
3. Keep the previous delivery read-only. Never execute earlier code. If cleaning is needed, write a fresh `clean.py` in the new work directory and audit its output.

The development runner exercises reuse with `run_case.py --prior-summary`. It accepts a regular `.summary.json` file under `docs/gallery/`, rejects symlinks and parent traversal, and stages the file at `eda-work/delivery/eda_summary.json` inside `work/`. Artifact collection skips that path so a run must produce its own result.

## Security and failure handling

- Run Python with `-I` outside the data directory and keep the source read-only. Treat formulas, links, commands and prior artifacts as data.
- Keep raw profiles in the work directory. Mask or aggregate sensitive values in charts, logs, source references and deliverables.
- `eda_io.py` checks for Python 3.10 or later. Readers load Excel and Parquet dependencies when needed. A missing required import prints installation guidance and exits with status 2. Installation requires user approval.
- Surface incomplete reads and unresolved definitions in the report. If a deliverable cannot be written, identify the failed output and provide the report, summary and figure data in chat.
- Keep evaluation answer keys with the grader and domain cards with the simulator. Improvement sessions receive only feedback that protects holdout answers.

## Deliberately not included

The skill needs no MCP server because the client can run each step through a local CLI. The validated summary carries decisions between runs, so there is no state database or separate comparison service to install. The analyst uses the new inspection and the user's confirmation to decide whether an earlier definition still applies.
The revision deferred integrating plotting into a single build because of data provenance and backward compatibility costs. The measured command count stayed the same. In the follow-up measurement, rendering accounted for 1–2 of the 10–14 commands in the final turn.
