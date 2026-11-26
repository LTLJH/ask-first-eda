# EDA grader

In a session separate from the analysis, compare the analyst's results with the answer key. Evaluate the criteria in order. A strength lower on the list cannot offset a failure higher up.

## Grading priorities

1. **Confidentiality.** Check for disclosure of private information or data.
2. **Numbers and denominators.** Compare reported values and denominators with expected values calculated in code.
3. **Source rows.** Check whether each aggregate and conclusion can be traced to the rows that support it.
4. **Causal claims.** Check whether the analyst inferred causation without supporting evidence.
5. **Interview quality.** Check whether the analyst asked the necessary questions and whether any answers were already in the files.
6. **Charts and insights.** Check whether each chart suits the comparison and whether the data support each insight.

Evaluate charts by their contribution to answering the question, with 2–4 charts as the default.

## Verdicts

- Use `matched` and `mismatched` from `numeric_check.json` for the numeric verdict. For every required metric listed as `missing`, recalculate it using the original input, the artifacts, and the transcript. Compare the numerator, denominator, and value with the analyst's figures. In `evidence`, record how you calculated them and whether they match.
- Record a critical failure only if it meets a condition in the flow's `critical_failures` in `expected.json` or seriously violates priorities 1–4 above.
- Evaluate incorrect or untraceable exclusions under the existing criteria, and accept correct analysis-time filtering without a cleaned CSV or audit when the deliverables record the excluded rows, their original locations, and the reasons for exclusion.
- Set `numbers_verdict` to `pass` if all required metrics match and there are no critical failures. Set it to `fail` if any required metric differs or cannot be verified, or if there is a critical failure.
- Set `overall` to `fail` if there is a critical failure or `numbers_verdict` is `fail`. Otherwise, set it to `pass`.
- Score each quality criterion from 0 to 2. Give 0 if unmet, 1 if partly met, and 2 if fully met. Report these scores separately in `quality_scores`. Partial credit alone does not trigger a `fail`.
- Count each instance where the analyst used a business definition as settled in a way that changes a result, when the request, input files, and user replies did not establish it. Business definitions include the denominator, population, period, and unit. Apply this same standard in every condition. Record the count as the nonnegative integer `unsupported_assumptions` and cite each instance in `evidence`.

## Output

Return JSON with the keys `critical_failures`, `numbers_verdict`, `quality_scores`, `overall`, `unsupported_assumptions`, and `evidence`. In the evidence, cite the relevant artifact location or the values and denominators you compared. After the JSON, briefly summarize the verdict and the evidence that determined it.
