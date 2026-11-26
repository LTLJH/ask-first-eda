# Interview and Ambiguity Log

Use the eight items as an internal Ambiguity Log checklist. Record the request, reply, file documentation or verified observation that settles an entry.
A file can establish that a code occurs. Its business meaning may still require an answer.

## Ambiguity Log checklist

| Order | Item | What closes it |
| --- | --- | --- |
| 1 | Domain and business process | Identify the process that creates the record and the stage observed. |
| 2 | Analysis goal and decision | Identify what decision the result should inform and for whom. |
| 3 | Meaning of one row | Identify the observation unit and whether repeated entities are expected. |
| 4 | Relevant columns | Establish the meaning, unit, eligibility rule and denominator of each quantity used. Split entries when answers can differ. |
| 5 | Time basis | Establish timestamp meaning, interval length, timezone and shift or calendar boundary as applicable. |
| 6 | Normal ranges and exceptions | Establish the applicable rule, including shutdowns, changeovers, returns or other exceptions relevant to the process. |
| 7 | Missing values | Count blanks, special codes and recorded zeros in scope. Establish the meaning of those present when relevant. |
| 8 | Join keys | Establish identity, scope of uniqueness, effective dates and which population to preserve. |

## Choosing one question

1. Match the request and verified structure to the checklist. Log supplied definitions and file-confirmed facts as `resolved`, with their sources.
2. Resolve any table choice blocking inspection first. Follow Step 1 for settled headlines and first-turn comparisons. Keep competing definitions open in the log until there is evidence for a choice.
3. For a choice that changes the result, locate the record responsible in the original file and verify candidate values in code. For example, if the last of four shipments has three packages and the others each have one, write “`$.shipments[3].packages` contributes one shipment or three packages. The totals are 4 shipments or 6 packages.” Use the actual path, totals and units for the file at hand.
4. Offer two to four plausible answers grounded in the file. For an interpretation-only choice, explain the decision the reader would make. Allow a correction or “unsure / later.”
5. Ask one question per rule, naming the rows and columns it covers and any exceptions. Wait for the reply.
6. If clarification matters, ask about one case that distinguishes the answers. Keep a deferred choice open.

## Question bank

Each row offers two **separate** good questions for different files and one poor prompt.
Use one question per turn. Replace the illustrative locators with specific verified records and precede any value-changing choice with the calculated comparison.

| Item | Good question A | Good question B | Poor question |
| --- | --- | --- | --- |
| Process | The Runs sheet has a request time and a blank finish time in row 9. Is the row created when work is scheduled or when it starts? | The Counts sheet lists snapshots in column A. Does a technician record them at handover or does a device record them on a timer? | Can you explain the whole operation? |
| Goal | Queue lines 2–18 include both elapsed minutes and a backlog count. Which decision will the reader make from this report? | The audit sheet covers several rooms. Should the comparison guide the next room inspection or a review of the whole building? | Which plots do you want? |
| Row | Tray codes repeat at different stages on sheet Runs. Does a row represent a tray or one stage visit? | Each entry at $.sessions has an array of readings. Should the unit of analysis be a session or a reading? | Can I count every line as one case? |
| Columns | The duration header on sheet Bench has no unit. Are these values seconds or minutes? | The slots table contains staffed and closed rows. Should checks per slot use all logged slots or only staffed slots? | I'll use the usual denominator, OK? |
| Time | Sheet B records one shift on both sides of midnight. Should these entries share a shift date or follow their calendar dates? | No offset appears in the timestamp field at $.runs. Is that clock set to UTC or local site time? | Which timezone, week boundary and shift do you use? |
| Exceptions | A reserve cycle on line 12 exceeds the posted limit for ordinary cycles. Does the same limit apply during reserve operation or is there a separate range? | The state column marks several slots as changeover. Are these scheduled occupied slots or downtime for this measure? | Shall I delete the unusual readings? |
| Missing | Tray rows 8 and 9 record a blank and an explicit zero for rechecks. Does a blank mean unrecorded or ineligible? | The optional review date is empty on pending records. Does that mean review is pending or the date was lost? | Should I fill every blank with zero? |
| Keys | Cabinet codes repeat across wings on sheet Locations. Does a reading match by cabinet alone or by wing and cabinet? | The lookup has two dated rows per code. Should a visit use the definition valid on its date or the latest definition? | Can I join the columns with similar names? |

## Deriving candidates from evidence

Check which observations receive weight in each calculation. All logged hours and open hours can differ by a closed interval. Counting orders and counting item rows can differ for a multi-item order. Dividing totals weights each group rate by its denominator, while averaging the group rates gives each group equal weight. When the candidates yield different values and the request leaves the choice open, calculate and show both with their units, then ask one question about the basis. A phrase such as “for the recorded period” sets the time range while leaving eligibility within it open.

| Evidence to inspect | Candidate answers it supports | Boundary of the inference |
| --- | --- | --- |
| Header names, status transitions and timestamp presence | Planned work, started work or completed work | A field name alone cannot identify the recording event. |
| Requested decision plus available measures | Load per shift, elapsed delay or coverage | Prioritize the decision the user actually named. |
| Repeated identifiers with distinct times or details | Repeated observation, item detail or revision | An observed unique value is only a candidate business key. |
| Unit suffixes, labeled headers, state and duration combinations | Seconds vs minutes, eligible vs elapsed time | Magnitude can flag a unit question. A conversion requires a definition. |
| Timestamps straddling a boundary or lacking offsets | Calendar day, shift-start day, UTC or local time | Keep multiple possible readings if none is documented. |
| Values outside an ordinary range concentrated in one mode | Mode-specific limit, valid excursion or recording issue | Frequency alone cannot establish error. |
| Blanks, literal codes and zeros by state | Unmeasured, inapplicable or recorded absence | A pattern suggests options without settling the meaning. |
| Key overlap, site partitions and validity dates | Simple, composite or effective-dated match | Check actual multiplicity after the user defines identity. |

## Maintaining the log

| Field | Record |
| --- | --- |
| id | Stable identifier, such as A04. Keep it when wording changes. |
| checklist_item | One decision about one checklist item. |
| question | The question actually asked, or JSON null when none was asked. |
| file_evidence | Array of source locators with observed facts. Record the user's definition separately. |
| candidates | Array of distinct interpretations that were considered. |
| status | One of the four statuses below. |
| answer | User's answer, source of resolution, a reason for closure, or null while open. |
| affects | Name a metric only when candidate answers change its value. For interpretation alone, name the decision or reading affected. |

| Status | Example of sufficient evidence |
| --- | --- |
| resolved | The request defines a staffed slot as one marked staffed, including zero checks. |
| user_assumed | “Use local calendar days for this draft.” State that assumption at each dependent comparison. |
| unresolved | A blank field has two plausible meanings and the user has deferred a decision. |
| not_applicable | The item is structurally absent (e.g., only one table and no join). Record the reason in answer. Low impact and unknown business rules stay open. |

## Example log extract

A cabinet log has one complete equal-duration slot per row. The user requests a workload review and defers the basis of the rate.
The two tables below show different fields of the same entries, joined by stable ID. A full log covers all eight checklist items.

| id | checklist_item | question | file_evidence | candidates |
| --- | --- | --- | --- | --- |
| A03 | Row meaning | null | Slots sheet, A2:A6, successive slot numbers | One slot |
| A04 | Denominator | Which slots count toward workload per slot? | Slots sheet, B2:B6, staffed and closed states | All recorded slots / staffed slots |
| A08 | Join keys | null | Slots sheet, A1:C6, only table used | None |

| id | status | answer | affects |
| --- | --- | --- | --- |
| A03 | resolved | User confirmed a row is one complete slot. | Checks per slot |
| A04 | unresolved | User said “later.” | Checks per slot, workload summary |
| A08 | not_applicable | Single table, no linkage. | None |

## Waiting and stopping

With each question, share two or three short lines of verified facts, such as the read range, blank-cell count or repeated-record count.
Do not ask the user for counts that the file can supply. Candidate answers and elapsed time never confer approval.
Keep the working log internal unless requested. On request, show its current fields as a table in the user's language.
Use the question criterion in [Step 2 of the skill](../SKILL.md). If the user asks to proceed, close the interview immediately and leave outstanding items unresolved.
Attach an unresolved ID and condition to alternatives only when their values differ. Keep a settled value unconditional and put any interpretation note in limitations. Withhold only the result whose inputs cannot be verified.
