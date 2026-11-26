# Factory Utility walkthrough

This synthetic manufacturing workbook is licensed under MIT. The conversation includes replies from a simulated user.
[Dataset provenance and license](../../examples/factory_utility/SOURCE.md)

## Step 0 — Input

| File | Size | Format |
| --- | --- | --- |
| [`utility_batches.xlsx`](../../examples/factory_utility/utility_batches.xlsx) | 6,324 bytes | Excel (.xlsx) |

The report read `batches!A1:G12` and `meter_readings!A1:D12`. Both sheets have grouped headings on row 1, field names on row 2, and 10 data records on rows 3–12.

## Interview

> **User:** I'm preparing materials for our daily plant meeting. Please use the attached batch production and steam meter records to compare steam consumption in kilograms per tonne of output on January 1 and 2. For each day, I'd also like to know how much the ratio of total steam consumption to total output differs from the simple average of the individual batch rates. The product mix changed between the two days. Can we conclude from these numbers that the plant became less efficient? Please check with me before deciding which day to assign batches that cross midnight.

> **Analyst:** Batch B-0016 (`batches`, row 7) started at 23:00 on January 1 and ended at 01:00 on January 2. Which day should receive the whole batch in the steam-per-tonne comparison, or does your plant use another rule?

> **User:** Assign all of B-0016’s production and steam consumption to January 1, its start date in Korea Standard Time.

> **Analyst:** For batch B-0012, `meter_readings` rows 3–4 show 80 kg and 120 kg. Are these separate amounts to add (200 kg total), or is the second reading the cumulative total for the batch (120 kg total)?

> **User:** They’re separate amounts. Add them for 200 kg total.

> **Analyst:** Batch B-0016 produced 1 tonne, and `meter_readings` row 8 records 0 kg of steam. Does that zero mean the batch used no steam, or that its steam consumption is unavailable?

> **User:** The zero is a measured value. B-0016 used no fresh steam.

> **Analyst:** Batch B-0017 produced 1 tonne, and `meter_readings` row 9 also records 0 kg. Does that zero represent measured zero fresh-steam use or an unavailable reading?

> **User:** It’s a measured zero. B-0017 used no fresh steam.

> **Analyst:** Rows 10 and 12 in `batches` are identical and both list B-0019 with 0.5 tonnes of output. Should I count them once as one physical batch?

> **User:** Yes. Count B-0019 once, using the first occurrence in row 10.

> **Analyst:** In `batches` row 6, B-0015 is marked `shutdown` and shows 0 kg of production. Does that zero mean the shutdown produced no output, or that production was inapplicable or unrecorded?

> **User:** The shutdown produced no output.

> **Analyst:** In `meter_readings` row 7, B-0015’s shutdown has a steam reading of 0 kg. Was that a measured zero or was steam use unrecorded during the shutdown?

> **User:** It was a measured zero. The shutdown used no steam.

## What the analysis did

### Quality checks and aggregation

The analyst converted output to tonnes, kept B-0019 from `batches` row 10, and excluded its duplicate in row 12. The meter readings were summed by `batch_id`, then joined one-to-one to the nine distinct batch records. For B-0012, rows 3–4 in `meter_readings` contributed 80 + 120 = 200 kg of steam. B-0016 was assigned to its January 1 KST start date.

### Excluded rows

The B-0015 shutdown (`batches` row 6, `meter_readings` row 7) contributed 0 t and 0 kg to the pooled totals. Its individual rate is undefined, so it was excluded from the simple average. B-0016 and B-0017 had positive output and measured zero fresh steam. Their zero rates were included.

### Metric definitions

The pooled rate divides total steam by total output. The simple average gives each positive-output batch equal weight.

| Date | Steam / output | Pooled rate | Simple average | Pooled minus simple |
| --- | --- | ---: | ---: | ---: |
| January 1 | 500 kg / 4.5 t | 111.11 kg/t | 150.00 kg/t | −38.89 kg/t |
| January 2 | 4,300 kg / 14.0 t | 307.14 kg/t | 225.00 kg/t | +82.14 kg/t |

Product H stayed at 400 kg/t and L at 75 kg/t. H’s output share increased from 11.11% to 71.43%, accounting arithmetically for the 196.03 kg/t increase in the pooled rate. A change in plant efficiency remains unproven by the two-day comparison.

## Report

[HTML report](../gallery/factory_utility.html) · [JSON summary](../gallery/factory_utility.summary.json)

### Report headline

> Fresh steam per tonne rose from 111.11 kg/t on January 1 to 307.14 kg/t on January 2 (utility_batches.xlsx, both sheets). The two-day comparison does not establish a loss of efficiency.

### Chart questions

- How far apart are the two daily calculations?
- Which individual batch rates underlie the daily averages?

## Ambiguity log

| ID | Topic | Status | Decision |
| --- | --- | --- | --- |
| <a id="a01"></a>A01 | Business process | resolved | Batch production and fresh-steam metering, with one shutdown. |
| <a id="a02"></a>A02 | Decision | resolved | Compare daily steam use per tonne for the plant meeting. |
| <a id="a03"></a>A03 | Row meaning | resolved | Count B-0019 once using row 10. |
| <a id="a04"></a>A04 | Denominators | resolved | Use tonnes for the pooled ratio and equal weights across positive-output batches for the simple average. |
| <a id="a04b"></a>A04B | Meter reading meaning | resolved | Add the 80 kg and 120 kg readings. |
| <a id="a05"></a>A05 | Time basis | resolved | Assign the entire B-0016 batch to its January 1 start date in KST. |
| <a id="a06"></a>A06 | Shutdown output | resolved | The shutdown produced zero output. |
| <a id="a06b"></a>A06B | Shutdown steam | resolved | The meter recorded zero steam during shutdown. |
| <a id="a07"></a>A07 | January 1 zero steam | resolved | B-0016 used no fresh steam. |
| <a id="a07b"></a>A07B | January 2 zero steam | resolved | B-0017 used no fresh steam. |
| <a id="a08"></a>A08 | Join keys | resolved | Aggregate steam increments by batch ID before the join. All nine IDs match. |
