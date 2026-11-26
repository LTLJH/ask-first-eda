# Hourly production log fixture

Retain the existing input.csv byte for byte. The table specifies its complete contents in source order for independent verification. The header is CSV line 1. Use UTF-8, a comma delimiter and one physical line per record. The fixture is hand-set and has no random seed.

| CSV line | hour_start | line_status | units_produced |
|---|---|---|---:|
| 2 | 2026-03-02 08:00 | open | 20 |
| 3 | 2026-03-02 09:00 | open | 0 |
| 4 | 2026-03-02 10:00 | closed | 0 |
| 5 | 2026-03-02 11:00 | open | 40 |

Each local timestamp starts one complete hour, including the final interval. Preserve both zeros and the status strings.
