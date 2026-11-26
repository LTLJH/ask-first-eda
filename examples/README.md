# EDA demo data

All five examples use Flow B, which starts with the user's opening request and asks about business rules as needed. The opening request is in `case.md`. Only the simulated user uses `domain_card.md` to answer questions.

| Example | Data and opening request | Source and license |
|---|---|---|
| [Seoul bike rental demand](seoul_bike/case.md) | Use `SeoulBikeData.csv` to understand rental patterns by time of day and season and plan bike redistribution staffing | UCI Machine Learning Repository, CC BY 4.0. [Source and file details](seoul_bike/SOURCE.md) |
| [Support ticket SLAs](support_tickets/case.md) | Use `tickets.jsonl` to assess Q2 SLA compliance and identify delays for next quarter's staffing meeting | Synthetic data, MIT. [Source and generator](support_tickets/SOURCE.md) |
| [Batch steam consumption](factory_utility/case.md) | Use `utility_batches.xlsx` to compare daily steam consumption per tonne of output | Synthetic evaluation input from this repository, MIT. [Source](factory_utility/SOURCE.md) |
| [Equipment sensors](equipment_sensors/case.md) | Use `sensor_readings.parquet` to identify unusual operating periods for four pumps and prioritize inspections for next week | Synthetic Parquet data, MIT. [Source and generator](equipment_sensors/SOURCE.md) |
| [Daily production report](messy_production_report/case.md) | Clean up merged headers, mixed units, and subtotals in `daily_report.xlsx` to compare production and utilization trends by line | Synthetic Excel data, MIT. [Source](messy_production_report/SOURCE.md) |

UCI's recommended citation for the Seoul bike rental dataset

> Easwaramoorthy, S. (2020). Seoul Bike Sharing Demand [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5F62R.

Each example takes one data file as input. From the repository root, run `python3 -I examples/support_tickets/make_data.py` to regenerate `tickets.jsonl` and `expected_facts.json`. Run `python3 -I examples/support_tickets/check_facts.py` to verify the calculated totals.

To run an example with `evals/run_case.py`, specify its directory with an argument such as `--case-dir examples/support_tickets`.
