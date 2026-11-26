# A/B/C evaluation of Ask First EDA

On six synthetic cases, independent review credited both the one-line instruction and the skill with 24/24 correct numeric results. In each condition, 18/24 results could be reported as final. The distinction mattered when a calculation was correct under a stated assumption and the user had yet to confirm it.

## Setup

On 2026-11-26, the analyst ran each case twice under each of three conditions, for 36 runs. Within each case, all conditions used the same input, opening request, delivery requirements (an offline HTML report and a JSON file of calculated metrics), and simulator card. All used interview flow B, in which the simulator answers one question at a time so the analyst can use the confirmed definition. Only the simulator saw the card. The analyst used gpt-6.2-sol at medium effort, the simulator used gpt-6.2-sol at low effort, and a separate grading session used gpt-6.2-astra at high effort. [Evaluation protocol](README.md)

- **A (no skill)** used the common analyst instructions.
- **B (one-line instruction)** used A’s instructions plus the following sentence from the harness.

  > Ask about a business definition only when the request and the file cannot settle a choice that changes the result, and keep the evidence for each number.

- **C (skill)** used the common analyst instructions and directed the analyst to read and follow Ask First EDA.

Run metadata recorded two repository commits after the 0.5.0 release, `19d08ba` and `a9e9699`. Five runs at the first commit recorded a modified working tree. All 12 C runs recorded the same skill fingerprint. [Harness](run_case.py)

| Case | Prior use | Input format | Decision tested |
|---|---|---|---|
| case-1 | New | Pipe-delimited text | When to ask which denominator to use |
| case-2 | Previously tested | JSON | Which records a sentinel value applies to |
| case-3 | Previously tested | Parquet | Control with a defined calculation |
| case-4 | New | GeoJSON Lines | When the available evidence makes a question unnecessary |
| case-5 | Previously tested | Markdown table | How to handle mixed interpretations of source units |
| case-6 | Previously tested | CSV | Which rows belong in the calculation |

## Results

Each condition produced 12 runs with two required metrics per run. The first two rows count metrics. A labeled alternative could earn numeric credit if its value and population matched. A confirmed final value also required a settled definition and a consistent deliverable.

| Measure | A · No skill | B · One line | C · Skill |
|---|---:|---:|---:|
| Correct numeric results after independent review | 18/24 | 24/24 | 24/24 |
| Confirmed final values | 14/24 | 18/24 | 18/24 |
| Unsupported definition assertions | 8 | 4 | 0 |
| Runs with at least one such assertion | 6/12 | 2/12 | 0/12 |
| Runs exposing an absolute home path in a delivery link | 12/12 | 12/12 | 0/12 |
| Runs that asked the required denominator question (case-1) | 0/2 | 0/2 | 0/2 |
| Runs that proceeded without an unnecessary question (case-4) | 2/2 | 2/2 | 2/2 |
| Median analyst time per run (seconds) | 75.3 | 86.4 | 152.5 |
| Median analyst tokens per run (uncached input + output) | 15,876 | 26,295.5 | 52,705.5 |

Each unsupported definition counts once per run, even if repeated in several files. The question rows count questions addressed to the user during the conversation. The cost rows use analyst logs only. Relative to B, C took 1.76× the median analyst time and used 2.00× the median analyst tokens.

On case-1, all three conditions missed the denominator question in both runs. A committed to one denominator. B and C gave conditional values and left the choice open. On case-5, C left the source units open in one run and confirmed them with the user in the other. Across all six cases, C made no unsupported definition assertions and exposed no home paths. A one-line instruction can direct the analyst to use relative links. This experiment did not measure the effect of that instruction alone.

## Grading and independent review

The automated numeric check matched 14/24 metrics for A, 20/24 for B, and 24/24 for C. Independent review found eight false negatives, all marked unverified. They fell into two groups.

- **Six totals** (four in A, two in B). The evidence mapper treated the row-selection rule as a condition on the reported totals. The quotation check then required a condition the analyst had never attached to the totals. Review credited the correct numbers and counted unsupported source-unit assertions separately.
- **Two conditional rates** (both in B). The table identified the denominator through its heading and row label. The extracted quotation lost that context. Review credited the conditional values. The required denominator question remained unanswered.

The original overall grades passed 0/12 runs in A, 0/12 in B, and 11/12 in C. Those grades also covered delivery failures. In all 12 B runs, the exposed path was the only critical failure. The independent corrections above apply to numeric credit.

## Limits

This was a small comparison with two repetitions per condition per case, synthetic data, one analyst model, and a simulated user. The same author supplied all six cases, four of which had appeared in earlier tests. These observations apply to this setup and do not establish general superiority.
