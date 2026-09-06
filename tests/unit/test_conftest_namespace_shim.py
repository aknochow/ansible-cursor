# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import atexit
import shutil


def test_namespace_shim_registers_working_cleanup(namespace_shim_factory, monkeypatch, tmp_path):
    registered = []
    monkeypatch.setattr(atexit, "register", lambda fn, *args, **kwargs: registered.append((fn, args, kwargs)))

    result = namespace_shim_factory("test_shim_", "cursor", tmp_path)
    try:
        assert result.exists()
        assert len(registered) == 1
        fn, args, kwargs = registered[0]
        fn(*args, **kwargs)
        assert not result.exists()
    finally:
        shutil.rmtree(str(result), ignore_errors=True)
