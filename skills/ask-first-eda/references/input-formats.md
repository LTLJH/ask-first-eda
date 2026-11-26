# Reading file formats

Open sources read-only. Start with the extension, detected format, evidence, conflicts and read extent from inspection.
A readable container can hold several incompatible tables. Establish the unit and range before counting records.

## Coverage record

| Field | What to retain |
| --- | --- |
| Source | A safe file alias and original format. Use the alias consistently in locators and reproduction code. |
| Format evidence | Suffix, signature or structural evidence, encoding where applicable, and any competing reading. |
| Selected scope | Table ID, sheet and range, JSON path, JSONL lines or Parquet row groups and selected columns. |
| Rows and columns | Dimensions for that scope, header handling and observed rows versus expected total. |
| Boundaries | Exact ranges known to be read, skipped or failed, reason for each and unknown extent where necessary. |
| Coordinates | Original line spans, sheet rows and cells, JSON indices/paths or group and row ranges. Preserve them after filtering. |

## CSV and TSV

| Decision | Evidence and handling |
| --- | --- |
| Encoding | Check the BOM first, then strict UTF-8, then compare legacy decodes. If `encoding_ambiguous` is true, show both header interpretations from `encoding_candidates` in **Data at a glance** and ask the user to confirm the encoding. Pass the confirmed codec with `--encoding` for strict decoding during inspection, profiling, plotting and auditing. |
| Decode failure | Locate byte offsets and the affected extent when known. Avoid replacing undecodable bytes to make a numeric column pass. |
| Delimiter | Compare field counts across logical records under plausible delimiters. Quoted delimiters and quoted newlines belong inside fields. |
| Header | Check whether the first record contains field names or data. Keep the physical header line span and explain any selection. |
| Ragged row | Locate short or long records, compare actual and expected widths, and retain the irregular cells. Withhold totals whose columns may have shifted. |
| Broken quoting | Record the first failed record and how much of the remaining stream is unread. A physical newline may be inside a quoted value. |
| IDs and blanks | Read literal text so 0042 keeps its leading zeros. Distinguish empty fields, missing cells, a literal NA code and recorded zero. |
| Override | Use `--delimiter` with a single actual character and `--header yes` or `--header no` only when justified. Repeat the selection during profiling and plotting. |

Example: if a quoted note begins on line 3 and ends on line 4, cite the record as lines 3–4.
For a semicolon-delimited file, a comma inside a decimal value may be part of the number. Confirm the numeric convention before conversion.

## Excel

| Decision | Evidence and handling |
| --- | --- |
| Container | For XLSX look for workbook parts inside the ZIP. The reader recognizes legacy XLS by its binary signature and requests an XLSX export. Report unread extent as unknown. |
| Sheets | Inventory sheet names, ranges and warnings. Select by name or by inspection ID. Record unselected sheets and why they are outside scope. |
| Header | Check title and field-name rows separately. In Data overview give each sheet's name and actual header row number(s), or state that there is no header. If `header_inferred_without_type_evidence` appears, confirm the header with the user before treating the row total as known. |
| Multiple regions | Blank rows, notes and subtotals may sit inside the sheet's bounding rectangle. Establish the relevant block and reconcile any filtering. |
| Cell limit | A sheet whose bounding rectangle exceeds 20,000,000 cells is recorded as unread. Copy a smaller range to a new workbook or export that range to CSV. |
| Merges | In Data overview list each sheet's exact merged ranges in A1 notation, including title and header spans. State “none” for a verified empty list, or “unknown” and the reason for an unread sheet. Preserve anchor coordinates. |
| Formulas | Distinguish literal formula text, stored cached result and missing cache. Read cache metadata separately. Never recalculate formulas, run macros or resolve external links. |
| Freshness | A present cache may predate edits. Identify the value source and withhold dependent totals when freshness or availability is unknown. |
| Protection or read failure | Record the sheet, part or cell range and reason. A protection flag alone does not establish that a readable sheet failed. |
| Display format | A number displayed as a padded ID or date may carry a different stored representation. Check the intended identifier or calendar before deriving values. |

Select a sheet with `--sheet` and optionally `--header-row` (one-based, or 0 for no header) during profiling.
For example, if a title spans A1:F1 and field names occupy row 4, give both coordinates under the sheet name. Use the final header selection after any override. For unread sheets, mark unverified header information unknown. Retain original sheet rows through filtering and sorting so duplicate pairs can be checked against their batch and compared cells.
The profile may contain formula expressions as text. Use an independently verified cache mapping or request a values-only export when a metric requires those results.

## JSON documents

| Decision | Evidence and handling |
| --- | --- |
| Container | Check whether the entire stream parses as one document. Newlines within a formatted document are layout. |
| Record unit | List candidate arrays and paths. A root object can itself be a record. Choose the unit that matches the decision. |
| Path | Keep the selected path pattern and concrete indices for contributing records. Report nested field paths and absent branches. |
| Nesting | Preserve nested lists and objects until there is a reason to expand. Measure parent and child counts before using repeated parent attributes. |
| Missing fields | Distinguish absent key, explicit null, empty string and zero. Count how often each occurs in the chosen record set. |
| Parse failure | Report error position and unknown extent as applicable. Avoid silently repairing duplicate keys, trailing delimiters or clipped records. |

Example: one session under `$.sessions` contains a list of samples. A session count uses the parent array.
For a sample distribution, select `$.sessions[*].samples` and keep each sample's parent index.
A session with no samples still belongs to the session population. Explain its contribution under either grain.
Use a candidate `--table-id` or quote the path passed to `--json-record-path` to protect brackets and wildcards in a shell.

## JSON Lines

| Decision | Evidence and handling |
| --- | --- |
| Unit | Check each physical line as one JSON value. Record encoding, line range and nested field paths. |
| Blank or malformed line | List each failed line and its reason. Scope results to successfully decoded records. |
| Inconsistent structure | Count scalar, array and object records separately if their interpretation differs. Preserve each original line number. |
| Several lines per document | Test document structure before interpreting line breaks as record boundaries. |

Example: if lines 1 and 3 parse and line 2 fails, report two usable records and cite lines 1 and 3.
The intended record count at the failed location can remain unknown. Do not renumber line 3 to line 2.

## Parquet

| Decision | Evidence and handling |
| --- | --- |
| Container | Compare leading and trailing PAR1 markers with readable footer metadata. Describe a missing or unreadable footer. |
| Schema | Preserve column names, physical/logical types as available, decimal precision, time units and timezone metadata. Numeric storage alone does not make a code a measure. |
| Groups | Record footer row count, row group indices, expected rows and successfully decoded columns and row ranges. |
| Partial read | List failed groups, columns, ranges and reasons. Metadata counts describe the file but cannot substitute for observed measure values. |
| Nested columns | Keep lists and structs at their original grain until expansion has a defined use and a recorded count change. |

Example: if group 1 fails between readable groups 0 and 2, retain group 2's original positions.
Limit findings to the readable groups and identify the columns for which values were unavailable.

## Markdown tables

| Decision | Evidence and handling |
| --- | --- |
| Boundaries | Locate the header and alignment row, confirm pipe-separated cells and record the table index or heading and physical lines. |
| Multiple tables | Compare headers, nearby headings and grain. Select a single inspection ID for profiling. |
| Literal pipes | Respect escapes. A pipe inside cell content can resemble a new column. Check irregular field counts before using a measure. |
| Non-table text | Mark surrounding paragraphs, code fences and intervening lines outside the selected table. Leave links inert. |
| Content | Preserve blanks, numeric-looking codes and formatting whose meaning is uncertain. Report encoding and unresolved cells. |

Example: a document may contain a unit legend followed by readings. Cite the readings table by its own ID and line range.
If a literal pipe makes the width ambiguous, keep the row visible and withhold the affected column total.

## Unknown or conflicting input

Show what the reader established, where it stopped and what remains unknown. Preserve the original file.
If two viable readings change the result, ask which one is intended or request a readable export.
Use separate report dataset entries or explicit scope names when parts of the same file have different grains.
