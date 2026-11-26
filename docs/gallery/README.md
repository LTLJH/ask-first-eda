# Report gallery

The [gallery](index.html) shows five reports generated with the `eda` skill. The analyst and simulated user both used `gpt-6.2-sol` in all five runs. Each run started with an [example dataset and opening request](../../examples/README.md).

| Report | Description | Input | Analyst turns | Charts | Conversation | Data |
| --- | --- | --- | --- | --- | --- | --- |
| [Seoul Bike](seoul_bike.html) | Compare hourly rental demand to plan bike redistribution staffing. | CSV | 4 | 3 | [Walkthrough](../walkthroughs/seoul_bike.md) | [JSON summary](seoul_bike.summary.json) |
| [Factory Utility](factory_utility.html) | Compare fresh steam per tonne across two days and quantify the effect of the product mix. | Excel (.xlsx) | 8 | 2 | [Walkthrough](../walkthroughs/factory_utility.md) | [JSON summary](factory_utility.summary.json) |
| [Support Tickets](support_tickets.html) | Measure first-response SLA attainment and find where tickets spend time before resolution. | JSONL | 5 | 4 | [Walkthrough](../walkthroughs/support_tickets.md) | [JSON summary](support_tickets.summary.json) |
| [Equipment Sensors](equipment_sensors.html) | Use current and vibration readings to prioritize pump inspections. | Parquet | 5 | 3 | [Walkthrough](../walkthroughs/equipment_sensors.md) | [JSON summary](equipment_sensors.summary.json) |
| [Messy Production Report](messy_production_report.html) | **Korean conversation.** Clean a multi-sheet Excel workbook and compare production and utilization by line. | Excel (.xlsx) | 7 | 3 | [Walkthrough](../walkthroughs/messy_production_report.md) | [JSON summary](messy_production_report.summary.json) · [Cleaned CSV](messy_production_report/cleaned_daily_report.csv) · [Cleaning script](messy_production_report/clean.py) · [Exclusion log](messy_production_report/excluded.csv) · [Audit](messy_production_report/audit.json) |

Analyst turn counts come from the transcripts and include the final response. Chart counts come from the corresponding JSON summary.
