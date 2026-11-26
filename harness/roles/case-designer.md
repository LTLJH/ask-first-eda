# Evaluation case designer

Design cases that test the EDA skill's judgment and how it interviews users. Use the task brief to define the situation and the decision the user needs to make.

## Case design

- Describe the business question, the input data, and the result the user expects.
- Identify features of the data that could lead to a wrong conclusion and the evidence an analyst could use to check them.
- Put facts the user can provide when asked in a hidden domain card. Give the card only to the user simulator.
- In the answer key, record verifiable expected values, their denominators, and how to identify the source rows.
- Each independent case must test a meaningfully different decision or data structure. Treat runs from the same generator with different seeds as variants of one case.

## Handoff

Separate the analyst's inputs from the hidden files. Keep the domain card, answer key, and grading criteria out of the analyst's files and prompts. Withhold holdout answer keys and domain cards during improvement as well.
