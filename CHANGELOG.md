# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-02-11

### Added
- `README.md` with project overview, quickstart, architecture docs, and comic creation guide
- `LICENSE` (MIT, Copyright (c) 2026 Simen)
- `CONTRIBUTING.md` — Development setup, PR process, code style, and task-picking guide
- `CHANGELOG.md` (this file)
- `tests/test_smoke.py` — 20 smoke tests covering config, state, registry, detection, rendering, and prompts (no API key required)
- `.github/workflows/ci.yml` — GitHub Actions CI running tests on Python 3.10/3.11/3.12
- `.github/ISSUE_TEMPLATE/bug_report.md` — Bug report template
- `.github/ISSUE_TEMPLATE/feature_request.md` — Feature request template
- `.github/pull_request_template.md` — PR template

### Changed
- `.gitignore` — Added `.claude/` directory exclusion

### Notes
- No core functionality was changed. All modifications are documentation, testing, and repository hygiene.
- The following files should be created manually: `CODE_OF_CONDUCT.md`, `SECURITY.md`
