# Data source

Synthetic, MIT

These data simulate a fictional B2B SaaS support desk. They use no real companies, people, contact details, or external source data. From the repository root, run `python3 -I examples/support_tickets/make_data.py` to regenerate `tickets.jsonl` and `expected_facts.json` using the Python standard library and the fixed seed `20250630`. Run `python3 -I examples/support_tickets/check_facts.py` to recalculate the metrics from the JSONL file and compare them with the generated results.

- Business hours versus elapsed time for the first-response SLA, including how unanswered tickets affect the denominator
- Pausing the resolution SLA clock while waiting for the customer and choosing the resolution endpoint for reopened tickets
- Survivorship bias from omitting unresolved tickets from average resolution time
- Timestamps with a KST offset alongside UTC timestamps
- The effect of a higher share of P1 tickets on resolution times during the mid-June outage
- Repeat submissions marked with `duplicate_of` and CSAT collected only for resolved tickets
