# Contributing to ansible-cursor

## Running Tests Locally

This repository uses `uv` for reproducible environment management with a pinned lockfile (`uv.lock`). All unit tests are deterministic and require no API keys or live credentials. Mock `cursor_sdk`; never put a live `CURSOR_API_KEY` in CI.

### Quick test run:
```bash
uv run pytest
```

### Syncing dependencies:
```bash
uv sync --extra dev
uv run pytest -v
```

### Running lint:
```bash
uv run ruff check .
```

### Running sanity tests:
Ansible sanity tests require the repository to be within an `ansible_collections/aknochow/cursor` directory hierarchy:
```bash
uv run ansible-test sanity --local --python 3.13 -v
```

## Commit Standards

- Sign off all commits (`git commit -s`).
- Include AI assistance attribution via trailer when applicable:
  `Assisted-by: <model>` (never `Co-Authored-By:`).
