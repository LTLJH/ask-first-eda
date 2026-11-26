# Contributing

## Reporting a case

Use [the case report template](.github/ISSUE_TEMPLATE/case_report.md).
Prefer a small synthetic or anonymized table instead of company materials.
Include the business question, any ambiguous definitions, the expected and
actual results, and the client and version used.

## Development

Set up the development dependencies with:

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Install the repository hook from the root:

```sh
ln -sf ../../scripts/hooks/pre-commit .git/hooks/pre-commit
```

Run the test suite with `python -m pytest -q`. Write a failing test first,
then make the smallest change that passes it: follow the red-to-green
workflow.

Do not put personal paths, company data, or source text from reference
materials in public files. Keep private notes and sensitive details out of
the repository.
