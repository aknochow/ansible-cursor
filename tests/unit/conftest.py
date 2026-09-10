# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[2]


def _create_namespace_shim(prefix: str, collection_name: str, project_root: Path) -> Path:
    namespace_root = Path(tempfile.mkdtemp(prefix=prefix))
    ns_path = namespace_root / "ansible_collections" / "aknochow" / collection_name
    ns_path.parent.mkdir(parents=True, exist_ok=True)
    if not ns_path.exists():
        ns_path.symlink_to(project_root)
    atexit.register(shutil.rmtree, str(namespace_root), ignore_errors=True)
    return namespace_root


_namespace_root = _create_namespace_shim("ansible_cursor_test_", "cursor", _project_root)
sys.path.insert(0, str(_namespace_root))

_BRIDGE_ENV_KEYS = (
    "CURSOR_SDK_BRIDGE_URL",
    "CURSOR_SDK_BRIDGE_TOKEN",
    "CURSOR_SDK_BRIDGE_AUTH_TOKEN",
    "CURSOR_SDK_BRIDGE_URL_FILE",
    "CURSOR_SDK_BRIDGE_TOKEN_FILE",
    "CURSOR_SDK_BRIDGE_BIN",
)


@pytest.fixture(autouse=True)
def _clear_bridge_env(monkeypatch):
    for key in _BRIDGE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def namespace_shim_factory():
    return _create_namespace_shim
