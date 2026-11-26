# Support Tickets walkthrough

This synthetic B2B support ticket log is licensed under MIT. The conversation includes replies from a simulated user.
[Dataset provenance and license](https://github.com/LTLJH/ask-first-eda/blob/main/examples/support_tickets/SOURCE.md)

## Step 0 — Input

| File | Size | Format |
| --- | --- | --- |
| [`tickets.jsonl`](https://github.com/LTLJH/ask-first-eda/blob/main/examples/support_tickets/tickets.jsonl) | 861,940 bytes | JSONL |

The full UTF-8 read covered lines 1–1,500, with one ticket per line and 12 fields per ticket. The creation timestamps span Q2 2025 in KST. Status events are nested within each ticket.

## Interview

> **User:** I'd like to use these support tickets to see how well we met our Q2 SLAs and where delays occurred. I'll use the findings in our staffing meeting for next quarter.

> **Analyst:** What first-response and resolution time targets should I use to score the Q2 2025 tickets, by priority (P1–P4) or any other grouping your SLA policy uses?

> **User:** The first-response targets are 1 business hour for P1, 4 for P2, 8 for P3, and 24 for P4. Business hours are weekdays from 09:00 to 18:00 KST, excluding May 5 and June 6, 2025. I don't know the resolution SLA targets.

> **Analyst:** Should I count the 54 tickets with no recorded first response whose deadlines had passed by quarter-end as SLA misses, or calculate attainment only among the 1,428 tickets with a recorded response?

> **User:** Yes, count the 54 unanswered tickets whose deadlines had passed as SLA misses and include them in the compliance denominator.

> **Analyst:** Should tickets marked `duplicate_of`, such as line 161 of `tickets.jsonl`, count separately toward the first-response SLA (1,280 of 1,482 met, 86.37%), or should I exclude those 15 tickets (1,268 of 1,467 met, 86.43%)?

> **User:** Exclude tickets marked `duplicate_of` from the first-response SLA and count the original tickets.

> **Analyst:** For the delay analysis, should I measure time to first resolution (median 45.4 elapsed hours across 1,353 tickets) or to the last recorded resolution, including work after reopening (median 47.5 hours across the same tickets)?

> **User:** Use the time from receipt to the first `resolved` status, even if the ticket was reopened. Subtract each period from entry into `waiting_customer` until the next recorded status.

## What the analysis did

### Quality checks and aggregation

The analyst retained original line numbers and scored all eligible first-response tickets in KST at quarter-end. Of the 1,500 receipts, 15 linked duplicates and 18 unanswered tickets with time left were excluded, leaving 1,467 eligible tickets. Of 199 misses, 147 had a late response and 52 were still unanswered. The interview’s count of 54 overdue unanswered tickets was calculated before linked duplicates were excluded. The raw response-time chart used the 1,415 eligible tickets with a recorded first response.

### Metric definitions

First-response attainment counts responses at or below the target among eligible originals. P2 had the lowest attainment, at **82.61% (247/299)**, and 48 of its 52 misses came from tickets received outside business hours.

Resolution timing uses receipt to the first `resolved` event. The median fell from 45.4 elapsed hours to 40.4 hours after subtracting customer waits for the 1,353 tickets with a first resolution, including 13 linked duplicates. The `assigned` status accounted for 88.4% of recorded pre-resolution elapsed time. That is time spent in a recorded status. Resolution SLA targets were unavailable.

### SLA clock comparison

The report uses weekdays 09:00–18:00 KST, excluding May 5 and June 6. The elapsed-time comparison counts all time since receipt. Both calculations use the same per-priority thresholds, exclude linked duplicates, and count overdue unanswered tickets as misses. Faster deadline expiry under elapsed time puts 12 more originals in the denominator.

| Clock | Met | Missed | Pending | Attainment |
| --- | ---: | ---: | ---: | ---: |
| Business hours | 1,268 | 199 | 18 | 86.43% (1,268/1,467) |
| Elapsed time | 346 | 1,133 | 6 | 23.39% (346/1,479) |

The elapsed-time result comes from a separate recalculation on the same input. [Fact-check script](https://github.com/LTLJH/ask-first-eda/blob/main/examples/support_tickets/check_facts.py)

## Report

[HTML report](../gallery/support_tickets.html) · [JSON summary](../gallery/support_tickets.summary.json)

### Report headline

> 1,268 of 1,467 eligible tickets met the first-response SLA (86.43%) in tickets.jsonl. Of the 199 misses, 52 were unanswered past deadline.

### Chart questions

- How did first-response attainment change through Q2?
- How close were individual responses to their targets?
- How widely did customer-wait-adjusted time to first resolution vary?
- Which recorded status accounted for the most time before first resolution?

## Ambiguity log

| ID | Topic | Status | Decision |
| --- | --- | --- | --- |
| <a id="a01"></a>A01 | Business process | resolved | Measure to first resolution, even if reopened. Subtract intervals in `waiting_customer`. |
| <a id="a02"></a>A02 | Decision | resolved | Use Q2 SLA and delay findings to discuss next-quarter staffing. |
| <a id="a03"></a>A03 | Row meaning | resolved | One ticket per JSON line, with its own event sequence. |
| <a id="a04"></a>A04 | SLA targets | resolved | Use business-hour thresholds of 1, 4, 8, and 24 hours for P1–P4. |
| <a id="a05"></a>A05 | Time basis | resolved | Score Q2 KST arrivals at quarter-end. Apply the business calendar for first response and elapsed time for resolution. |
| <a id="a06"></a>A06 | Duplicate tickets | resolved | Exclude tickets with `duplicate_of` from first-response SLA. |
| <a id="a07"></a>A07 | Unanswered tickets | resolved | Count overdue originals as misses and leave originals with open deadlines pending. |
| <a id="a08"></a>A08 | Join keys | not applicable | The analysis uses one table. |
| <a id="a09"></a>A09 | Resolution SLA targets | unresolved | Targets were unavailable. Resolution SLA attainment remains unknown. |
