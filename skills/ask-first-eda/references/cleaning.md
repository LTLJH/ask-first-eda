# Cleaning patterns

Use the sketches for confirmed choices. Read identifiers and placeholder tokens as text, preserving their spelling until their meaning is settled.

| Pattern | Sign | Ask the user (question) | pandas sketch (code) |
| --- | --- | --- | --- |
| Title or sign-off rows | A heading or signature sits outside the record block. | Which row range contains the records? | `records = df.loc[df["_source_row"].between(first, last)]` |
| Multi-row merged header | A merged label spans several field names. | Which group label belongs to these fields? | `df.columns = pd.MultiIndex.from_arrays([groups, fields])` |
| Wide table | Each line or date has its own measurement column. | Should these columns become values of one field? | `df.melt(id_vars=keys_and_lineage, value_vars=measure_cols, var_name="line_or_date")` |
| Subtotal or total rows | A stated total follows a block of detail rows. | Should this total be excluded from the metric? | `computed = detail["amount"].sum(min_count=1)` |
| Separators, mixed units and placeholders | Amounts contain commas, use different scales, or include a literal `-` or `N/A`. | What unit and number format should these values use? Does the token mean missing, zero or something else? | `amount = pd.to_numeric(text.str.replace(",", "", regex=False))`<br>`scaled = amount * units.map(confirmed_factors)`<br>`df[col] = df[col].replace(token, confirmed_value)` |
| One sheet per month | Tabs repeat the same fields for different months. | Which sheets belong in the requested period? | `df = pd.concat([tables[s].assign(_source_sheet=s) for s in months], ignore_index=True)` |
| Exact duplicate rows | Two or more rows match across every original column. | Were these rows copied by mistake, or do they represent repeated measurements? | `df[df.duplicated(keep=False)]` |
| Implausible values | A value differs by an order of magnitude from typical values in the same column, such as 1.32 where 13.2 is typical or 1800 where 180 is typical. | Should this be treated as a typo and read using the value in the original table, excluded, or kept as recorded? | `df.loc[df[col].notna() & ~df[col].between(low, high), col]` |

The audit checks whether each source row address was kept or logged as excluded and flags formula-like text in the cleaned CSV. Validate values separately by reconciling counts and totals, for example by date × line after a wide-to-long reshape. Use `--passthrough` to verify carried-through values and `--expand` when a confirmed reshape repeats a source row address.
