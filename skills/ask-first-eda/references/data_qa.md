# Data QA

Read this guide before joining or stacking tables, when missing values could change a requested result, or when producing a cleaned copy.

## Missing values

Use `missing_patterns` from the profile for the confirmed scope. In the Details tab’s **Data overview** table, report observed missing counts by group and month and identify fields missing together. Do not label the mechanism MCAR, MAR or MNAR from observed data alone.

Never fill blanks by default. Calculate the requested value under each applicable treatment. Compare excluding affected observations, treating blanks as zero and using a value specified by the user. Hold other definitions fixed. In **Metrics**, show the conditional values, units and differences. Follow Step 2 when the choice changes the requested result.

## Outliers

Flag outliers using the existing IQR fences and retain the rows. Compute the requested value with and without the flagged rows. Only when the result changes, show both values and their difference in **Metrics** and follow Step 2. Exclude outliers only after the user confirms.

## Joins and stacks

Run the check with the intended keys and join type. For example, check a left join and an additive column from the left input:

```sh
python3 -I "$SKILL_DIR/scripts/check_join.py" "$LEFT" "$RIGHT" --left-key id --right-key id --how left --total left:amount
```

Repeat the command with `--joined "$JOINED"` to compare actual rows and control totals with expectations. On `fail`, stop dependent calculations. On `warn`, record the key relationship and blank-key counts for both inputs in the **Reproducibility** table. For a stack, check overlapping periods or populations and compatible units before adding totals.

## Cleaned copy

Map each additive cleaned column to its source column and source grouping field. Leave unit-converted columns out of the mapping. Use the confirmed source reading options.

```sh
python3 -I "$SKILL_DIR/scripts/audit_clean.py" "$INPUT" --cleaned "$CLEANED" --excluded "$WORK/excluded.csv" --reconcile CLEANED=SOURCE@GROUP
```

Record the grouped totals and any discrepancies in **Reproducibility**. Use the cleaned copy only after the audit passes.

Do not run hypothesis tests or report p-values.
