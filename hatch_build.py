# SPDX-License-Identifier: Apache-2.0
"""Map this collection into ansible_collections/ at wheel build time.

Repo root stays a normal collection (galaxy.yml + plugins/) so ansible-test and
ansible-galaxy collection build keep working. The wheel installs to
site-packages/ansible_collections/<namespace>/<name>/. ansible_collections/ and
the namespace dir are PEP 420 (no __init__.py) so multiple wheels coexist.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# Galaxy-equivalent payload. Tests, pyproject, CI, and this file stay out.
_COLLECTION_FILES = (
    "galaxy.yml",
    "README.md",
    "README.rst",
    "LICENSE",
    "COPYING",
    "CHANGELOG.md",
    "CHANGELOG.rst",
)
_COLLECTION_DIRS = (
    "plugins",
    "meta",
    "roles",
    "playbooks",
    "changelogs",
    "files",
    "examples",
    "LICENSES",
)


def _galaxy_field(root: Path, key: str) -> str:
    prefix = f"{key}:"
    for line in (root / "galaxy.yml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    raise ValueError(f"galaxy.yml missing {key!r}")


def _assert_versions_match(root: Path) -> None:
    galaxy_version = _galaxy_field(root, "version")
    with (root / "pyproject.toml").open("rb") as fh:
        pyproject_version = tomllib.load(fh)["project"]["version"]
    if galaxy_version != pyproject_version:
        raise ValueError(
            f"galaxy.yml version {galaxy_version!r} != pyproject.toml version {pyproject_version!r}"
        )


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        _assert_versions_match(root)
        ns = _galaxy_field(root, "namespace")
        name = _galaxy_field(root, "name")
        prefix = f"ansible_collections/{ns}/{name}"
        # No __init__.py on ansible_collections/ or <ns>/ — PEP 420 namespaces.
        force = build_data.setdefault("force_include", {})
        for filename in _COLLECTION_FILES:
            src = root / filename
            if src.is_file():
                force[str(src)] = f"{prefix}/{filename}"
        for dirname in _COLLECTION_DIRS:
            src = root / dirname
            if src.is_dir():
                force[str(src)] = f"{prefix}/{dirname}"
