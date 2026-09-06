# Contributing to ansible-cursor

This repository uses `uv` for a pinned lockfile (`uv.lock`). Unit tests are
deterministic and require no API keys.

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Ansible sanity tests need the collection path layout:

```bash
uv run ansible-test sanity --local --python 3.13 -v
```

## Commit standards

- Sign off all commits (`git commit -s`).
- AI assistance trailer: `Assisted-by: Cursor (cursor-grok-4.6-high)` —
  never `Co-Authored-By:`.
