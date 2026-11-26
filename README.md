# Ask First EDA

Ask First EDA asks how you define your metrics before it calculates them and builds a report with charts.

[Korean](README.ko.md)

| Hour | Machine status | Units produced |
| --- | --- | ---: |
| 08:00–09:00 | Running | 18 |
| 09:00–10:00 | Stopped | 0 |
| 10:00–11:00 | Running | 22 |
| 11:00–12:00 | Running | 20 |

[View an example report](https://ltljh.github.io/ask-first-eda/gallery/support_tickets.html) · [Browse the gallery](https://ltljh.github.io/ask-first-eda/gallery/index.html)\
[Download the ZIP from Releases](https://github.com/LTLJH/ask-first-eda/releases/latest)

The line produced 60 units. It averaged 15 units/h over the full shift and 20 units/h over the three running hours.

> Should I include the stopped hour when I calculate hourly output?

![Summary tab of an example report](docs/assets/report-preview.png)

## Install

Requires Python 3.10 or later. In the extracted `ask-first-eda` folder, install dependencies and check the installation:

```sh
python -m pip install -r requirements.txt
python -I scripts/check_install.py
```

### Claude desktop app

1. Download `ask-first-eda.zip` from the [latest Release](https://github.com/LTLJH/ask-first-eda/releases/latest) and upload it in **Settings → Skills** (or **Customize → Skills** / **Plugins**).
2. The app may block package installation, so ask Claude to run the uploaded skill’s `scripts/check_install.py` to check available dependencies.
3. To build the ZIP locally, run `python scripts/package_skill.py` from the repository root and upload `dist/ask-first-eda.zip`.

### Claude Code

- Copy the extracted folder to `<project>/.claude/skills/ask-first-eda/` or `~/.claude/skills/ask-first-eda/` (or unpack the Release ZIP there).
- Open the terminal in the project folder and start Claude Code there, because that is where the work folder is created.
- Use the project path for a single project and the user path for all projects.

### Codex

- Copy the extracted folder to `<project>/.agents/skills/ask-first-eda/` (or unpack the Release ZIP there).
- Open the terminal in the project folder before starting Codex so the skill is available to that project.
- Use the project path when the skill should apply only to that project.

On Windows, use `python` rather than `python3`; in PowerShell, use `Copy-Item -Recurse .\skills\ask-first-eda <project>\.claude\skills\ask-first-eda` (or the `.agents\skills` path for Codex).

To update, replace the installed folder or upload the new Release ZIP. To remove it, delete the folder or remove the skill in the app.

| Client | Version | Date | Verification scope | First run |
| --- | --- | --- | --- | --- |
| Claude Code | 2.1.332 | 2026-11-26 | routing 4/4(install smoke) | pass (2026-11-26, clean project, support_tickets example: eda-work/delivery/report.html and eda_summary.json created in the project folder) |
| Codex | 0.171.0 | 2026-11-26 | routing 4/4(install smoke) | covered by evaluation runs (codex exec) |
| Claude desktop app | — | 2026-11-26 | upload and run, manual | pass (manual, 2026-11-26) |

See the [installation smoke status](evals/install_smoke.json) for the automated results.

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

[Contributing](CONTRIBUTING.md)
