# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Fixed

- End the first turn after asking which definition to use when the choice changes the result.

### Added

- Add `prompted_rel` to give the analyst guidance on relative paths in chat.
- Add `--opening-style` and `--analyst-model` to the evaluation harness.
- Give each evaluation role a separate Codex home.
- Let `--prior-summary` load a private summary from `_private/`.
- Summarize the stress evaluation in both READMEs.

## [0.5.0] - 2026-11-26

### Added

- Windows support for running the skill scripts.
- A Claude desktop app ZIP that includes the project license.

### Changed

- Renamed the skill to Ask First EDA (`ask-first-eda`).
- Run analyses from the project folder and write reports and supporting files there.
- Strengthened checks on source references, chart metadata, and provenance. Cleaning audits account for row expansion and compare values with the source.
