# EDA A/B summary

Runs before 2026-11-25 used the skill name `eda` (now `ask-first-eda`).

| Run ID | Case | Flow | Condition | Overall | Numbers verdict | Critical failures | Mismatched | Analyst questions | Turns | Wall time (s) | Tokens | Report | Charts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ab1_orders_nested_json_C_noskill | orders_nested_json | C | noskill | fail | fail | 0 | 0 | 1 | 2 | 40.819021 | 425190 | no | — |
| ab1_orders_nested_json_C_skill | orders_nested_json | C | skill | pass | pass | 0 | 0 | 1 | 2 | 266.117609 | 1077491 | yes | 4 |
| ab1_throughput_hourly_B_noskill | throughput_hourly | B | noskill | pass | pass | 0 | 0 | 1 | 2 | 32.832846 | 390437 | no | — |
| ab1_throughput_hourly_B_skill | throughput_hourly | B | skill | fail | fail | 1 | 0 | 0 | 1 | 174.537571 | 630551 | yes | 3 |
| ab1_throughput_hourly_C_noskill | throughput_hourly | C | noskill | pass | pass | 0 | 0 | 1 | 2 | 39.355324 | 371679 | no | — |
| ab1_throughput_hourly_C_skill | throughput_hourly | C | skill | fail | fail | 1 | 1 | 0 | 1 | 119.961149 | 592745 | yes | 3 |
| ab1_utility_batches_excel_B_noskill | utility_batches_excel | B | noskill | pass | pass | 0 | 0 | 3 | 4 | 87.144821 | 910099 | no | — |
| ab1_utility_batches_excel_B_skill | utility_batches_excel | B | skill | pass | pass | 0 | 0 | 3 | 4 | 347.703073 | 2599873 | yes | 3 |
| ab2_orders_nested_json_C_skill | orders_nested_json | C | skill | pass | pass | 0 | 0 | 1 | 2 | 218.920026 | 1033823 | yes | 3 |
| ab2_throughput_hourly_B_skill | throughput_hourly | B | skill | pass | pass | 0 | 0 | 2 | 3 | 193.875618 | 1471940 | yes | 3 |
| ab2_throughput_hourly_C_skill | throughput_hourly | C | skill | pass | pass | 0 | 0 | 1 | 2 | 163.001339 | 822064 | yes | 3 |
| ab2_utility_batches_excel_B_skill | utility_batches_excel | B | skill | pass | pass | 0 | 0 | 4 | 5 | 266.394152 | 2284014 | yes | 4 |
| ab3_throughput_hourly_B_skill | throughput_hourly | B | skill | pass | pass | 0 | 0 | 2 | 3 | 168.498494 | 1158373 | yes | 3 |
| ab3_throughput_hourly_C_skill | throughput_hourly | C | skill | pass | pass | 0 | 0 | 1 | 2 | 165.238204 | 827648 | yes | 4 |

## Skill vs noskill

Each comparison shows skill / noskill. Commas separate repeated runs.

| Case | Flow | Skill run IDs | Noskill run IDs | Overall | Numbers verdict | Critical failures | Mismatched | Analyst questions | Turns | Wall time (s) | Tokens | Report | Charts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| orders_nested_json | C | ab1_orders_nested_json_C_skill, ab2_orders_nested_json_C_skill | ab1_orders_nested_json_C_noskill | pass, pass / fail | pass, pass / fail | 0, 0 / 0 | 0, 0 / 0 | 1, 1 / 1 | 2, 2 / 2 | 266.117609, 218.920026 / 40.819021 | 1077491, 1033823 / 425190 | yes, yes / no | 4, 3 / — |
| throughput_hourly | B | ab1_throughput_hourly_B_skill, ab2_throughput_hourly_B_skill, ab3_throughput_hourly_B_skill | ab1_throughput_hourly_B_noskill | fail, pass, pass / pass | fail, pass, pass / pass | 1, 0, 0 / 0 | 0, 0, 0 / 0 | 0, 2, 2 / 1 | 1, 3, 3 / 2 | 174.537571, 193.875618, 168.498494 / 32.832846 | 630551, 1471940, 1158373 / 390437 | yes, yes, yes / no | 3, 3, 3 / — |
| throughput_hourly | C | ab1_throughput_hourly_C_skill, ab2_throughput_hourly_C_skill, ab3_throughput_hourly_C_skill | ab1_throughput_hourly_C_noskill | fail, pass, pass / pass | fail, pass, pass / pass | 1, 0, 0 / 0 | 1, 0, 0 / 0 | 0, 1, 1 / 1 | 1, 2, 2 / 2 | 119.961149, 163.001339, 165.238204 / 39.355324 | 592745, 822064, 827648 / 371679 | yes, yes, yes / no | 3, 3, 4 / — |
| utility_batches_excel | B | ab1_utility_batches_excel_B_skill, ab2_utility_batches_excel_B_skill | ab1_utility_batches_excel_B_noskill | pass, pass / pass | pass, pass / pass | 0, 0 / 0 | 0, 0 / 0 | 3, 4 / 3 | 4, 5 / 4 | 347.703073, 266.394152 / 87.144821 | 2599873, 2284014 / 910099 | yes, yes / no | 3, 4 / — |

These 4 pairs are an exploratory sample, too small to draw statistical conclusions.

## Lightweight revision (2026-11-23)

We ran each case and flow twice before and twice after the revision in an isolated Codex home. The cases were `throughput_hourly` (C), `utility_batches_excel` (B), and `production_next_month` (B). We calculated the figures below with code. The small sample makes this comparison exploratory.

| Case | Version | Commands | Uncached input + output | Total input | Analyst time (s) |
| --- | --- | --- | --- | --- | --- |
| production_next_month | before | 10, 9 | 271,472, 141,232 | 1,841,513, 1,390,182 | 247, 241 |
| production_next_month | after | 11, 7 | 201,106, 125,313 | 1,462,120, 1,165,644 | 271, 232 |
| throughput_hourly | before | 8, 10 | 84,707, 109,905 | 576,862, 636,141 | 150, 186 |
| throughput_hourly | after | 6, 7 | 75,892, 69,044 | 577,612, 460,309 | 134, 149 |
| utility_batches_excel | before | 12, 9 | 217,115, 423,710 | 2,414,372, 3,987,612 | 299, 398 |
| utility_batches_excel | after | 13, 14 | 196,169, 217,485 | 2,521,679, 3,185,372 | 325, 352 |

Across 6 runs per version, the command count held at 58 before and 58 after (+0.0%). Uncached input plus output tokens fell from 1,248,141 to 885,009 (-29.1%), total input tokens from 10,846,682 to 9,372,736 (-13.6%), and analyst time from 1521 to 1464 seconds (-3.8%).

All 12 runs passed both the overall and numeric checks. The runs had 0 critical failures, 0 instances of external skill access, and 0 absolute paths. The average quality score out of 12 rose from 11.17 to 11.67. Reports contained 3–4 charts before the revision and 2–4 after. The number of PNGs embedded in the HTML matched the figure count.

Commands that read skill script source fell from 1 to 0. Two recurring tasks kept the overall command count steady. The analyst rewrote the Ambiguity Log file on each question turn and ran `plots.py` separately for charts that used different data. We deferred folding plotting into a single build.

### Follow-up revisions

Each revision used the same 3 cases with 2 runs per case in an isolated environment. The table compares totals across 6 runs with the baseline (b0).

| Version | Change | Quality avg (of 12) | Commands | Uncached input + output | Total input | Analyst time |
| --- | --- | --- | --- | --- | --- | --- |
| b0 | baseline | 11.17 | 58 | 1,248,141 | 10,846,682 | 1,521 s |
| a1 | self-contained rules, examples, lighter procedure | 11.67 | 58 (+0.0%) | 885,009 (−29.1%) | 9,372,736 (−13.6%) | 1,464 s (−3.8%) |
| a2 | + Ambiguity Log kept in conversation | 11.00 | 69 (+19.0%) | 926,388 (−25.8%) | 8,493,600 (−21.7%) | 1,434 s (−5.7%) |
| a3 | + one chart shows the requested comparison on a shared axis | 11.33 | 61 (+5.2%) | 1,225,225 (−1.8%) | 8,499,345 (−21.6%) | 1,571 s (+3.3%) |

All 18 runs passed both the overall and numeric checks, with 0 instances of external skill access and 0 absolute paths.

In a2, the analyst ran 0 commands on question turns. The average quality score fell below baseline, with deductions for 2 charts, so a3 strengthened the chart guidance.

Differences in command count and analyst time across versions fell within the variation between repeated runs. Total input tokens fell consistently, by about 14–22%.

The remaining cost comes from the number of interview turns and the work required on the final turn (cleaning, auditing, analysis, rendering, building, and verification). We deferred a single build because it would save only 1–2 commands.
