# Ask First EDA

Ask First EDA asks how you define your metrics before it calculates them and builds a report with charts.

| Hour | Machine status | Units produced |
| --- | --- | ---: |
| 08:00–09:00 | Running | 18 |
| 09:00–10:00 | Stopped | 0 |
| 10:00–11:00 | Running | 22 |
| 11:00–12:00 | Running | 20 |

The line produced 60 units. It averaged 15 units/h over the full shift and 20 units/h over the three running hours.

> Should I include the stopped hour when I calculate hourly output?

![Summary tab of an example report](docs/assets/report-preview.png)

## Install

Requires Python 3.10 or later. Install dependencies from the repository root.

```sh
python3 -m pip install -r skills/ask-first-eda/requirements.txt
python3 -I skills/ask-first-eda/scripts/check_install.py
```

Replace `<project>` with the path to the project where you want to use the skill, then run the commands for your client.

```sh
# Claude Code
mkdir -p "<project>/.claude/skills"
cp -r skills/ask-first-eda "<project>/.claude/skills/ask-first-eda"

# Codex
mkdir -p "<project>/.agents/skills"
cp -r skills/ask-first-eda "<project>/.agents/skills/ask-first-eda"
```

Claude Code also supports the user-level path `~/.claude/skills/ask-first-eda/`.

Before the rename, project-scoped routing passed all four checks per client on Claude Code 2.1.330 and Codex 0.171.0. Routing under the new name is pending. [Installation smoke status](evals/install_smoke.json)

### Claude desktop app

1. Run `python scripts/package_skill.py` from the repository root.
2. In the Claude desktop app, upload `dist/ask-first-eda.zip` from **Settings → Skills** if available. You can also look under **Customize → Skills** or the **Plugins** sidebar.
3. The app may block package installation. Ask Claude to run the uploaded skill’s `scripts/check_install.py` to check which dependencies are available.

### Try it in one minute

Copy `examples/messy_production_report/daily_report.xlsx` into your project, then invoke `/ask-first-eda` and ask “Show production and utilization by line.”

Expected flow: data at a glance → ask about the utilization denominator → confirm the cleaning plan → report.

## Explore the reports

The skill asks one question at a time in your language. The report’s Summary tab shows the findings and charts. The Details tab gives the evidence and calculations.

[Report gallery](docs/gallery/index.html)

- [Seoul Bike](docs/gallery/seoul_bike.html) · [Walkthrough](docs/walkthroughs/seoul_bike.md)
- [Factory Utility](docs/gallery/factory_utility.html) · [Walkthrough](docs/walkthroughs/factory_utility.md)
- [Support Tickets](docs/gallery/support_tickets.html) · [Walkthrough](docs/walkthroughs/support_tickets.md)
- [Equipment Sensors](docs/gallery/equipment_sensors.html) · [Walkthrough](docs/walkthroughs/equipment_sensors.md)
- [Messy Production Report](docs/gallery/messy_production_report.html) · [Walkthrough](docs/walkthroughs/messy_production_report.md)

See how the [choice of clock affects first-response compliance](docs/walkthroughs/support_tickets.md#sla-clock-comparison) or how a [cleaning plan accounts for excluded rows](docs/walkthroughs/messy_production_report.md#cleaning).

[System architecture](docs/architecture.md)

## Supported inputs

The gallery includes examples in CSV, Excel, JSONL, and Parquet.

| Input | Support |
| --- | --- |
| CSV / TSV | Inspect and analyze |
| `.xlsx` | Inspect and analyze |
| JSON / JSONL | Inspect and analyze |
| Parquet | Inspect and analyze |
| Markdown table | Inspect and analyze |
| `.xls` | Detect; reading support is not promised |

Korean chart labels require a system font that supports Hangul.

## What it will not do

- Model training or tuning
- Automatic hypothesis testing or p-values
- Causal claims
- Modify the source file

## Evaluation

Across the first four pairs, total wall time with the skill was 4.54× the total without it. Runs without the skill produced no reports, so the times cover different deliverables. The revised harness requires both conditions to deliver an HTML report and a results file. [A/B summary](evals/ab_summary.md) · [Evaluation method](evals/README.md)

Revision a1 changed uncached input plus output tokens by −29.1% from baseline (b0). The later revision a3 changed the same total by −1.8% from b0. [Revision results](evals/ab_summary.md#lightweight-revision-2026-11-23)

These small exploratory comparisons do not guarantee performance for the current version.

## License

The code is licensed under [MIT](LICENSE). [Example datasets](examples/README.md) retain their own licenses.
