# Seoul Bike walkthrough

Seoul Bike Sharing Demand comes from the UCI Machine Learning Repository under CC BY 4.0. The conversation includes replies from a simulated user.
[Dataset provenance and license](../../examples/seoul_bike/SOURCE.md)

## Step 0 — Input

| File | Size | Format |
| --- | --- | --- |
| [`SeoulBikeData.csv`](../../examples/seoul_bike/SeoulBikeData.csv) | 604,166 bytes | CSV |

The analysis read lines 1–8,761 in Windows-1252. Line 1 is the header. The 8,760 records contain 14 fields and cover every recorded hour across 365 dates, with no blank cells.

## Interview

> **User:** I'd like to use these Seoul public bike rental records to understand demand patterns. This will help our operations team plan staffing for bike redistribution.

> **Analyst:** For redistribution staffing, should I use only hours marked `Functioning Day = Yes` (729.16 recorded rentals per hour across 8,465 hours) or include all 8,760 hours (704.60 per hour if the 295 `No` entries count as zeros, as recorded on line 3146 of `SeoulBikeData.csv`)?

> **User:** Use only `Functioning Day = Yes` hours to compare typical demand for redistribution staffing. Count the `No` hours separately as service suspensions.

> **Analyst:** Does `Rented Bike Count` represent rentals that started during the listed hour, so that the 254 recorded on line 2 of `SeoulBikeData.csv` are pickups during the midnight hour?

> **User:** I don't know whether those rentals started during the midnight hour. The count is the number of completed rentals systemwide for that hour.

> **Analyst:** Should I interpret `Date` and `Hour` in `SeoulBikeData.csv` as Seoul local time when identifying peak staffing windows?

> **User:** I don't know.

## What the analysis did

### Quality checks

The analysis checked that each `Date` and `Hour` pair occurs once. The rental count on line 2 is 254 systemwide completions. The file has no UTC offset, so the report uses the recorded clock hours.

### Aggregation

The analyst grouped 8,465 operating hours by hour of day, day type, and season. The 295 `Functioning Day = No` hours were counted separately as service suspensions. Line 3146 is the first excluded row. All three charts use the operating-hour cohort.

### Metric definitions

Average demand is the sum of completed rentals divided by eligible operating hours in each group.

| Peak | Completed rentals | Operating hours | Mean per operating hour |
| --- | ---: | ---: | ---: |
| Overall, 18:00 | 548,568 | 353 | 1,554.02 |
| Weekdays, 18:00 | 432,737 | 251 | 1,724.05 |
| Weekends, 17:00 | 118,423 | 102 | 1,161.01 |

At 08:00, the weekday mean was 1,306.02 and the weekend mean was 420.79. The peaks identify windows to review for redistribution coverage. Assigning them to local shifts requires confirming the time zone, and sizing crews requires station and workload data.

## Report

[HTML report](../gallery/seoul_bike.html) · [JSON summary](../gallery/seoul_bike.summary.json)

### Report headline

> 1,554 completed rentals per operating hour at 18:00 was the highest mean across recorded clock hours in SeoulBikeData.csv.

### Chart questions

- When are completed rentals most concentrated?
- How much do individual observations vary by recorded hour?
- How common are high-volume operating hours?

## Ambiguity log

| ID | Topic | Status | Decision |
| --- | --- | --- | --- |
| <a id="a01"></a>A01 | Recording stage | resolved | The field counts systemwide completions for the recorded hour. |
| <a id="a02"></a>A02 | Decision | resolved | Identify hours to review for redistribution staffing. |
| <a id="a03"></a>A03 | Row grain | resolved | One count per recorded date and hour. |
| <a id="a04"></a>A04 | Denominator | resolved | Use operating hours for demand comparisons. Report suspensions separately. |
| <a id="a05"></a>A05 | Time basis | unresolved | The time zone is unknown. Group by the date and hour labels as recorded. |
| <a id="a06"></a>A06 | Exceptions | resolved | Service suspensions are marked `No`. The operating distribution retains high-volume hours. |
| <a id="a07"></a>A07 | Missing values and zeros | resolved | There are no blank cells. All zero counts appear on suspension rows. |
| <a id="a08"></a>A08 | Join keys | not applicable | The analysis uses one table. |
