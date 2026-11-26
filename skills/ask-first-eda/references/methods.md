# Choosing EDA methods

Always check quality. Select single-variable summaries, relationships or time comparisons, and domain metrics when both the request and the available observations support them.

## Quality and joins

- Check parsing against the source, including lost leading zeros, shifted columns and failed numeric or date conversions. Keep the original coordinates for affected rows.
- Count missing cells and affected rows, exact duplicates and repeated keys. Check unit markers within each measure. The profiler is optional if analysis code checks missingness, duplicates and units on the same scope. Repeat the checks on the changed data after cleaning or a scope change.
- Keep recorded zeros distinct from blanks. Confirm the meaning of an exception in each affected column. Keep unusual values and flag the rows against a documented limit or, for an exploratory flag, the quartiles and IQR.
- Before joining, establish key identity, null-key handling and expected multiplicity. For each matched key, multiply its left and right row counts to predict the matched rows. Account separately for unmatched rows retained by the join.
- Reconcile both inputs with the output row count and additive totals. Stop dependent calculations if row multiplication is unexplained. When stacking files, check for overlapping populations or periods and incompatible units.

## Default figures

Use 2–4 charts by default. Use one chart to show the requested headline or comparison directly, plotting the values being compared on the same axis. Include a raw data figure showing the observations behind the answer, even for a small sample. Keep eligible zeros visible and mask sensitive labels. Choose the remaining views by question and record a specific reason for each omitted view.

| Question | Display and decision criteria |
| --- | --- |
| How much does a measure vary? | Use a histogram for shape or a boxplot for spread. Compare bin widths before describing peaks. For sparse groups, show the individual values. |
| Which categories are common? | Count records by category. Give the denominator and account for unknown labels. Counts represent time only if each record covers the same duration. |
| How do groups differ? | Compare distributions on the same scale and give group sizes. Check whether the group mix could explain a change in the overall result. |
| How do measurements vary together? | Plot complete pairs. Use Pearson correlation for a linear pattern or Spearman for a monotonic pattern. Give the paired count for each coefficient. Check curvature, clusters and influential pairs. |
| When does a measure change? | Plot observations at the confirmed time grain. Show gaps and partial intervals. Connect points only across verified continuous periods. |

One figure may answer more than one question. Record used and excluded counts, including zero, and the reasons for exclusions. Distinguish plotted aggregates from contributing rows. Use a labeled table when the question needs exact comparisons.

## Summaries and requested metrics

- Use mean and standard deviation for a roughly symmetric distribution, or median and quartiles for a skewed one. Give valid n and units. For a mixture, compare centers and spread within groups.
- For each KPI, identify the eligible observations, time window, calculation, unit and source rows. A time-based rate needs verified exposure. An entity count needs a confirmed identity key.
- Compute the numerator and denominator over the same eligible rows, including any that contribute zero to the numerator, and cite the full set in `source_refs`.
- For a pooled rate, divide the total numerator by the total eligible denominator across compatible, non-overlapping groups. Equal weighting of group rates requires a question about the average group. If the requested denominator or weighting is open, show the verified alternatives and ask before selecting a headline.
- Keep the observed components when a rate is undefined. Use null for an unavailable value or an inapplicable component and explain why. Compare unresolved alternatives with their conditions, source locations and shared ambiguity ID.
