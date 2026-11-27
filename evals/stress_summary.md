# Stress evaluation of Ask First EDA

On six synthetic holdout cases, Ask First EDA scored 90.74 against 51.16 for a one-line instruction with relative-path guidance. The 39.58-point gap met the preregistered decision rule. In the smaller comparison with a weaker model, the scores differed by 0.31 points.

## Setup

Within each case, both conditions used the same input, opening request, delivery requirements, and simulated user. The simulator could answer one question at a time. B′ used a one-line instruction to ask about an unresolved definition when it would change the result and to keep evidence for each number. It also directed the analyst to use relative paths in chat. C directed the analyst to follow Ask First EDA. [Evaluation protocol](README.md)

The main comparison used gpt-6.2-sol at medium effort with 4 runs per case and condition (48 runs). The weaker-model comparison used gpt-reserve at low effort with 3 runs per case and condition on a subset of 3 cases (18 runs). Both comparisons completed all 66 planned runs.

The cases covered a large file with rare hidden anomalies, a multi-sheet workbook needing cleaning, two value-changing definitions with one stated, a vague first answer, a next-month file with a renamed column and a new category, and a control whose file settles the definition.

## Results

The score combines the share of correct final values, the share of required questions asked at the appropriate point, and a penalty for unsupported definition assertions. The control had no required question, so its score used the other two components. Cases had equal weight. The preregistered rule required C to lead by at least 20 points overall and to tie or beat B′ in at least 4/6 cases in the main comparison.

| Measure | B′ · One line + relative paths | C · Skill |
|---|---:|---:|
| Main comparison score | 51.16 | 90.74 |
| Correct final values after the numeric check was corrected | 22/48 | 42/48 |
| Required questions asked | 3/24 | 22/24 |
| Unsupported definition assertions | 9 | 4 |
| Unnecessary questions | 0 | 2 |
| Weaker-model score | 25.93 | 26.23 |
| Weaker-model correct final values | 6/18 | 6/18 |
| Weaker-model required questions asked | 0/9 | 0/9 |
| Weaker-model unsupported definition assertions | 12 | 12 |

In the main comparison, C tied or beat B′ in 6/6 cases. With the weaker model, C tied or beat B′ in 3/3 cases and both conditions had the same counts of correct final values and required questions asked. The preregistered decision rule applied to the main comparison.

### First-turn questions

Before the fix, the analyst asked a first-turn question in 0/8 probe runs across the two opening styles. The skill was updated to end the turn after asking about an open definition that changes the result. In the follow-up probe with the updated skill, the analyst asked in 6/6 runs that required a question and in 0/2 runs that required none.

### Cost

In the main comparison, C used 3.29…× the median analyst tokens (uncached input + output), took 1.49…× the median analyst time, and took 1.51…× the median wall-clock time. With the weaker model, the corresponding ratios were 2.09…×, 1.63…×, and 1.57…×. The ellipses indicate further decimal digits.

## Grading and independent review

The original numeric check left all 132 required slots unverified. Applying that check as written in the preregistration gave numeric credit of zero throughout. The resulting main scores were 33.10 for B′ and 58.80 for C, a 25.69-point gap with C at least tied in 6/6 cases. The weaker-model scores were 14.81 and 15.12, respectively.

A replacement check examined the final outputs for the value and unit and checked the numerator and denominator for rates. Its slot decisions agreed with an independent review on 16/16 slots across 8 sampled runs. The main results use the corrected check. The overall LLM grades passed 0/66 runs. They included delivery criteria and were affected by unverified values. The primary score used the preregistered measures.

## Limits

The same author designed the holdouts to exercise behaviors the skill specifies. The main comparison ran after the first-turn fix while the one-line instruction stayed the same. The replacement numeric check was written after the results were seen, and the independent agreement covers the sampled slots. The study used synthetic data, 4 repetitions per case and condition in the main comparison, and a simulated user.
