# Equipment Sensors walkthrough

These synthetic current and vibration readings for four pumps are licensed under MIT. The conversation includes replies from a simulated user.
[Dataset provenance and license](../../examples/equipment_sensors/SOURCE.md)

## Step 0 — Input

| File | Size | Format |
| --- | --- | --- |
| [`sensor_readings.parquet`](../../examples/equipment_sensors/sensor_readings.parquet) | 716,362 bytes | Parquet |

The analysis read all four Parquet row groups, covering 34,560 rows and seven columns. Each observation is for one pump and one five-minute timestamp in September 2025, Asia/Seoul.

## Interview

> **User:** Here are current and vibration readings for four pumps. Could you look at September as a whole and tell me when any of the pumps ran abnormally and whether any need inspection? I'll use this to plan next week's maintenance.

> **Analyst:** When `run_cmd` is blank, should I infer that a pump was running from its motor current, as for P-01 at 21:45 on September 27 when it drew 43.368 A, or count only readings with `run_cmd = 1`?

> **User:** Yes. When `run_cmd` is blank, count the pump as running if its current exceeds 20% of its rated current. Otherwise, count it as stopped. That P-01 reading counts as running.

> **Analyst:** What rated current should I use for P-01 and P-04, the two pumps with blank `run_cmd` readings?

> **User:** Use 42 A for P-01 and 31 A for P-04.

> **Analyst:** Should I use your site’s current and vibration limits to flag abnormal operation, or compare each pump with its own typical running readings?

> **User:** For vibration during operation, use 2.8 mm/s RMS for caution, 4.5 mm/s for alarm, and 7.1 mm/s for danger. A rise that lasts at least two weeks warrants inspection even below the alarm threshold. I don't know what current limits to use for abnormal operation.

> **Analyst:** Should I assess the first five-minute reading after each pump starts separately from steady operation when flagging abnormal current?

> **User:** Yes. Treat the first 10 minutes after a restart as a transient period and exclude inrush current during that time when flagging equipment anomalies.

## What the analysis did

### Quality checks and aggregation

The analyst retained source row numbers and sorted readings by pump and timestamp. A command of 1 identifies running observations. When the command is blank, the analyst used current strictly above 20% of rated current (42 A for P-01 and 31 A for P-04). The report found 264 readings with a missing field.

### Excluded rows and metric definitions

Running-vibration comparisons use 31,416 readings after excluding 3,090 stopped readings and 54 missing vibration readings from P-04 (rows 28,648–28,701). Site thresholds for running vibration are 2.8 mm/s RMS for caution, 4.5 for alarm, and 7.1 for danger. The current screen sets aside 66 restart readings in the first 10 minutes after an observed restart and uses the remaining 31,404 readings for pump-specific comparison. Engineering limits for current were unavailable.

### Inspection findings

- **P-02** had 60 readings at or above alarm out of 7,854 running readings. Of these, 24 reached danger, with a peak of 7.89 mm/s RMS. The three episodes were September 4, 09:10–10:40, September 12, 15:20–17:15, and September 24, 01:35–02:55. All 44 unusual steady-current readings fell in these episodes.
- **P-03** met the two-week inspection rule. Daily median running vibration rose for 24 days, from 2.09 mm/s RMS on September 6 to 4.20 on September 30. Its peak was 4.40 mm/s RMS.
- **P-01** showed a drop in median running vibration from 2.101 to 0.083 mm/s RMS around September 20, while median steady current stayed near 42 A. The report calls for checking its vibration channel.
- **P-04** peaked at 2.40 mm/s RMS in observed running readings. Its September 10 vibration gap ran from 11:15 to 15:40.

## Report

[HTML report](../gallery/equipment_sensors.html) · [JSON summary](../gallery/equipment_sensors.summary.json)

### Report headline

> Inspect P-02 first after three vibration episodes reached danger, peaking at 7.89 mm/s RMS. Inspect P-03 for 24 days of rising daily median vibration in sensor_readings.parquet.

### Chart questions

- Which pumps show sustained changes in running vibration?
- When did individual readings breach operating limits?
- How did P-02 current behave during its three vibration alarms?

## Ambiguity log

| ID | Topic | Status | Decision |
| --- | --- | --- | --- |
| <a id="a01"></a>A01 | Business process | resolved | Current and vibration monitoring for four pumps. |
| <a id="a02"></a>A02 | Decision | resolved | Prioritize inspections based on September readings. |
| <a id="a03"></a>A03 | Row grain | resolved | One pump and timestamp per five-minute observation. |
| <a id="a04"></a>A04 | Operating eligibility | resolved | Use the run command and apply the rated-current fallback only when the command is blank. |
| <a id="a05"></a>A05 | Time basis | resolved | Use September 2025 in Asia/Seoul. |
| <a id="a06"></a>A06 | Thresholds and exceptions | resolved | Apply the site vibration thresholds, two-week rise rule, and 10-minute current exclusion after restarts. |
| <a id="a06a"></a>A06a | Engineering limits for current | unresolved | Limits are unknown. Screen against each pump’s own steady running current. |
| <a id="a07"></a>A07 | Missing measurements | resolved | Leave missing vibration unobserved. Apply the agreed fallback to command gaps. |
| <a id="a08"></a>A08 | Join keys | not applicable | The analysis uses one Parquet table. |
