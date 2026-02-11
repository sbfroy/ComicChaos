# Contributing to Comic Chaos

Thanks for your interest in contributing! This document explains how to get started.

## Development Setup

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/ComicChaos.git
cd ComicChaos

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install pytest ruff

# Copy environment config
cp .env.example .env
# Add your OpenAI API key to .env

# Run the app
python main.py

# Run tests
python -m pytest tests/ -v

# Run linter
ruff check .
```

## Branching and Pull Requests

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/my-feature
   ```
2. Make your changes in small, focused commits.
3. Run tests and linting before pushing:
   ```bash
   python -m pytest tests/ -v
   ruff check .
   ```
4. Push your branch and open a Pull Request against `main`.
5. Fill in the PR template — describe what changed and how to test it.
6. All PRs require at least one review before merging.

## Code Style

- Python code follows [Ruff](https://docs.astral.sh/ruff/) defaults (line length 120).
- Use type hints for function signatures.
- Keep functions focused and reasonably short.
- Prefer Pydantic models for structured data.
- Frontend is vanilla JavaScript in a single `index.html` — keep it that way for simplicity.

## Tests

- Tests live in `tests/` and use pytest.
- Smoke tests (`test_smoke.py`) must pass without an API key.
- If you add a new module, add at least one test covering its core logic.
- Do not commit tests that make real API calls.

## Adding a New Comic

See the "Creating a New Comic" section in [README.md](README.md). Comic contributions are welcome — just add a new directory under `comics/` with a `blueprint.json`.

## Picking Tasks

- Check [Issues](../../issues) for open tasks.
- Issues labeled `good first issue` are great starting points.
- Comment on an issue before starting work to avoid duplicating effort.

## Reporting Bugs

Use the [Bug Report](../../issues/new?template=bug_report.md) issue template. Include:
- Steps to reproduce
- Expected vs. actual behavior
- Browser and Python version

## Requesting Features

Use the [Feature Request](../../issues/new?template=feature_request.md) issue template.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). Please read it before participating.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
