# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _galaxy_field(key: str) -> str:
    prefix = f"{key}:"
    for line in (_ROOT / "galaxy.yml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    raise AssertionError(f"galaxy.yml missing {key!r}")


def test_galaxy_version_matches_pyproject():
    with (_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    assert _galaxy_field("version") == pyproject["project"]["version"]


def test_pypi_name_matches_fqcn():
    with (_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    expected = f"{_galaxy_field('namespace')}-{_galaxy_field('name')}"
    assert pyproject["project"]["name"] == expected
