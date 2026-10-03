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

## Pip wheels

The git root stays a normal collection (`galaxy.yml` + `plugins/`) so
`ansible-test` and `ansible-galaxy collection build` keep working. `pip install`
maps that layout into `site-packages/ansible_collections/aknochow/cursor/`.
The PyPI name is `aknochow-cursor` (not `ansible-cursor` — Ansible trademark).
`ansible_collections/` and `aknochow/` are PEP 420 namespaces: wheels must not
ship `__init__.py` there, or a second collection installed in the same venv
clobbers the first.

`galaxy.yml` `version:` and `[project].version` must stay identical.

Build a wheel (does not upload to PyPI):

```bash
pip install build
python -m build
```

Smoke two collections in one clean venv (no `ANSIBLE_COLLECTIONS_PATH`). From
the ansible-ai-dev checkout:

```bash
python -m venv /tmp/coll-wheels && source /tmp/coll-wheels/bin/activate
pip install ./ansible-claude ./ansible-openshell
ansible-doc aknochow.claude.message
ansible-doc aknochow.openshell.sandbox
ansible-galaxy collection list
```

From this repo alone: `pip install .`

Do not upload to PyPI unless a release explicitly says so. Galaxy tarballs
remain the AAP channel (`ansible-galaxy collection build`).


## Branch names

The branch name says what the change is. Use one conventional prefix and a short description:

| Prefix | Use for | Example |
|---|---|---|
| `feat/` | a new capability | `feat/commit-range-review` |
| `fix/` | a bugfix | `fix/spinner-no-wrap` |
| `docs/` | documentation only | `docs/branch-names` |
| `test/` | tests only | `test/commit-range` |
| `chore/` | tooling, dependencies, maintenance | `chore/lockfile` |
| `refactor/` | a behavior-preserving restructure | `refactor/commit-context` |

Do not name a branch after the tool that opened it. `cursor/`, `claude/`, `codex/`, and any other agent or product prefix do not describe the change. Do not append a generated id (`-1bbb`, `-edab`, and the like) to force the name to be unique.

When a branch name is wrong, rename that branch and leave the existing pull request in place. Do not open a second pull request for the same change.

## Commit Standards

- Sign off all commits (`git commit -s`).
- Include AI assistance attribution via trailer when applicable:
  `Assisted-by: <model>` (never `Co-Authored-By:`).
