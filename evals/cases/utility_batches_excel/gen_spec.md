# Batch steam consumption workbook · Stage ③ design

Generate input.xlsx in a separate session. Use the following fixed population and order. There is no random sampling (seed: none). The tables below are the entire data distribution. All cells are constants, with no formulas, hidden rows, totals, external links or missing values.

## Workbook layout

Create exactly two sheets in order. Excel coordinates are one-based. Merge only the first-row spans shown. Put each group title in the top-left cell of its span. Row 2 contains unique column names; data start on row 3. Store text IDs, product, status and unit as Excel text, amounts as numbers, and timestamps as native Excel datetimes with minute precision and display format yyyy-mm-dd hh:mm. All times are Korean local civil time in 2026. Expand each date-time below from MM-DD HH:MM to the full year. The row labels below are coordinates and are omitted from the data.

## batches · A1:G12

Merge A1:B1 (Batch), C1:D1 (Interval), E1:G1 (Production). Use the column order below. Every row, including the repeated row, has an explicit production unit.

| Row | batch_id | product | start_at | end_at | status | production | production_unit |
|---:|---|---|---|---|---|---:|---|
| 3 | B-0012 | L | 01-01 01:00 | 01-01 03:00 | running | 2000 | kg |
| 4 | B-0013 | L | 01-01 04:00 | 01-01 05:00 | running | 1 | t |
| 5 | B-0014 | H | 01-01 06:00 | 01-01 07:00 | running | 500 | kg |
| 6 | B-0015 | NONE | 01-01 16:00 | 01-01 17:00 | shutdown | 0 | kg |
| 7 | B-0016 | L | 01-01 23:00 | 01-02 01:00 | running | 1 | t |
| 8 | B-0017 | L | 01-02 02:00 | 01-02 03:00 | running | 1000 | kg |
| 9 | B-0018 | L | 01-02 04:00 | 01-02 06:00 | running | 3 | t |
| 10 | B-0019 | H | 01-02 07:00 | 01-02 08:00 | running | 0.5 | t |
| 11 | B-0020 | H | 01-02 09:00 | 01-02 22:00 | running | 9500 | kg |
| 12 | B-0019 | H | 01-02 07:00 | 01-02 08:00 | running | 0.5 | t |

## meter_readings · A1:D12

Merge A1:B1 (Identifiers) and C1:D1 (Meter). Each steam value is the increment in kg for this reading. Do not generate cumulative register values.

| Row | reading_id | batch_id | reading_at | steam_kg |
|---:|---|---|---|---:|
| 3 | R01 | B-0012 | 01-01 02:00 | 80 |
| 4 | R02 | B-0012 | 01-01 03:00 | 120 |
| 5 | R03 | B-0013 | 01-01 05:00 | 100 |
| 6 | R04 | B-0014 | 01-01 07:00 | 200 |
| 7 | R05 | B-0015 | 01-01 17:00 | 0 |
| 8 | R06 | B-0016 | 01-02 01:00 | 0 |
| 9 | R07 | B-0017 | 01-02 03:00 | 0 |
| 10 | R08 | B-0018 | 01-02 06:00 | 300 |
| 11 | R09 | B-0019 | 01-02 08:00 | 200 |
| 12 | R10 | B-0020 | 01-02 22:00 | 3800 |

## Planted evidence

- Row 12 repeats batches row 10 exactly. Meter rows 3–4 are distinct legitimate increments. The two patterns require different handling before a join.
- Batches row 6 has a shutdown zero and no defined batch rate. Rows 7–8 have running zero-steam readings and positive production. Retain both in the batch mean and production totals.
- Row 7 crosses midnight. Its reading is on the second calendar date. The assigned operating day must cover the entire batch.
- Row 11 is a feasible large batch. Its meter row 12 is the sole largest steam draw. It also accounts for most of the second day's H output.
- The design varies the production share of product H across the two dates while holding both product-specific aggregate rates fixed. Compute product shares by tonnes.
