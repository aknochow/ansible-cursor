# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import stat
import textwrap
from pathlib import Path

import pytest
from ansible_collections.aknochow.cursor.plugins.module_utils.bridge_sidecar import (
    SidecarError,
    parse_discovery_line,
    start_sidecar,
    stop_sidecar,
)

FAKE_BRIDGE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json
    import os
    import signal
    import sys
    import time

    payload = {
        "schemaVersion": 1,
        "transport": "tcp",
        "protocol": "connect",
        "url": "http://127.0.0.1:54321",
        "authToken": "super-secret-bridge-token",
        "pid": os.getpid(),
    }
    sys.stderr.write("cursor-sdk-bridge ready " + json.dumps(payload) + "\\n")
    sys.stderr.flush()

    def _term(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    while True:
        time.sleep(0.2)
    """
)

FAKE_BRIDGE_BAD_JSON = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import sys
    import time
    sys.stderr.write("cursor-sdk-bridge ready {not-json super-secret-bridge-token}\\n")
    sys.stderr.flush()
    time.sleep(30)
    """
)

FAKE_BRIDGE_DIE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import sys
    sys.stderr.write("not a ready line\\n")
    sys.stderr.flush()
    raise SystemExit(1)
    """
)


def _install_fake(tmp_path: Path, source: str, name: str = "fake-bridge") -> Path:
    path = tmp_path / name
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _assert_no_secrets(payload) -> None:
    text = json.dumps(payload) if not isinstance(payload, str) else payload
    assert "super-secret-bridge-token" not in text
    assert "authToken" not in text


class TestParseDiscoveryLine:
    def test_ready_line(self):
        line = (
            'cursor-sdk-bridge ready {"schemaVersion": 1, "transport": "tcp", '
            '"protocol": "connect", "url": "http://127.0.0.1:9", "authToken": "t"}\n'
        )
        got = parse_discovery_line(line)
        assert got["url"] == "http://127.0.0.1:9"

    def test_non_ready_is_none(self):
        assert parse_discovery_line("noise\n") is None

    def test_bad_json_does_not_include_payload(self):
        with pytest.raises(SidecarError, match="invalid discovery JSON") as exc:
            parse_discovery_line("cursor-sdk-bridge ready {nope secret-token}\n")
        assert "secret-token" not in str(exc.value)
        assert "{nope" not in str(exc.value)


class TestSidecarLifecycle:
    def test_present_daemonizes_and_absent_reaps(self, tmp_path):
        rundir = tmp_path / "rundir"
        fake = _install_fake(tmp_path, FAKE_BRIDGE)
        result = start_sidecar(rundir=rundir, command=str(fake), timeout=5)
        try:
            assert result["changed"] is True
            assert result["state"] == "present"
            pid = result["pid"]
            assert pid_alive_or_fail(pid)
            assert result["ppid"] == 1
            token_mode = stat.S_IMODE((rundir / "token").stat().st_mode)
            dir_mode = stat.S_IMODE(rundir.stat().st_mode)
            assert token_mode == 0o600
            assert dir_mode == 0o700
            assert (rundir / "token").read_text().strip() == "super-secret-bridge-token"
            assert (rundir / "url").read_text().strip() == "http://127.0.0.1:54321"
            _assert_no_secrets(result)
            assert not (rundir / "stderr.log").exists()
            again = start_sidecar(rundir=rundir, command=str(fake), timeout=5)
            assert again["changed"] is False
            assert again["pid"] == pid
        finally:
            stop = stop_sidecar(rundir=rundir)
        assert stop["state"] == "absent"
        assert not (rundir / "token").exists()
        assert not (rundir / "pid").exists()
        assert not pid_alive_or_fail(pid, require_alive=False)

    def test_absent_is_idempotent(self, tmp_path):
        rundir = tmp_path / "rundir"
        first = stop_sidecar(rundir=rundir)
        second = stop_sidecar(rundir=rundir)
        assert first["state"] == "absent"
        assert first["changed"] is False
        assert second["changed"] is False

    def test_bad_json_fail_has_no_secrets(self, tmp_path):
        rundir = tmp_path / "rundir"
        fake = _install_fake(tmp_path, FAKE_BRIDGE_BAD_JSON)
        with pytest.raises(SidecarError) as exc:
            start_sidecar(rundir=rundir, command=str(fake), timeout=2)
        _assert_no_secrets(str(exc.value))
        assert not (rundir / "token").exists()
        assert not (rundir / "stderr.log").exists()

    def test_exit_before_discovery_has_no_stderr_dump(self, tmp_path):
        rundir = tmp_path / "rundir"
        fake = _install_fake(tmp_path, FAKE_BRIDGE_DIE)
        with pytest.raises(SidecarError, match="exited before discovery") as exc:
            start_sidecar(rundir=rundir, command=str(fake), timeout=2)
        assert "not a ready line" not in str(exc.value)


def pid_alive_or_fail(pid: int, require_alive: bool = True) -> bool:
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    if require_alive:
        assert alive, f"pid {pid} is not alive"
    return alive
