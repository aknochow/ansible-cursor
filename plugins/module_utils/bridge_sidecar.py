# SPDX-License-Identifier: Apache-2.0

"""Playbook-owned cursor-sdk-bridge sidecar (double-fork + setsid).

The vendor node must not remain a child of ansible-playbook: nested
Cursor-agent sessions SIGKILL that process (137). ``nohup &`` and
Ansible ``async`` + ``poll: 0`` stay in that tree and are forbidden.

Error messages and return values must never include the bridge URL or
auth token. Reap by pidfile, never by dumping process argv.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

READY_LINE_PREFIX = "cursor-sdk-bridge ready "
DEFAULT_RUNDIR_NAME = "ansible-cursor-sidecar"

PID_NAME = "pid"
URL_NAME = "url"
TOKEN_NAME = "token"
META_NAME = "meta.json"
STDERR_NAME = "stderr.log"
WORKSPACE_NAME = "workspace"


class SidecarError(Exception):
    """Operator-facing sidecar failure. The message must not include secrets."""


def default_rundir() -> Path:
    return Path.home() / ".cache" / DEFAULT_RUNDIR_NAME


def sidecar_paths(rundir: str | os.PathLike[str]) -> dict[str, Path]:
    root = Path(rundir).expanduser()
    return {
        "rundir": root,
        "pid": root / PID_NAME,
        "url": root / URL_NAME,
        "token": root / TOKEN_NAME,
        "meta": root / META_NAME,
        "stderr": root / STDERR_NAME,
        "workspace": root / WORKSPACE_NAME,
    }


def parse_discovery_line(line: str) -> dict[str, Any] | None:
    """Parse a ``cursor-sdk-bridge ready ...`` stderr line.

    Returns the payload mapping, ``None`` if the line is not a discovery
    line, or raises SidecarError if the JSON is malformed. The exception
    must not include the line (it contains the auth token).
    """
    if not line.startswith(READY_LINE_PREFIX):
        return None
    payload = line[len(READY_LINE_PREFIX) :]
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SidecarError("Bridge emitted invalid discovery JSON") from error
    if not isinstance(loaded, dict):
        raise SidecarError("Bridge discovery payload must be an object")
    return loaded


def endpoint_from_discovery(discovery: dict[str, Any]) -> tuple[str, str, int | None]:
    """Return ``(url, token, pid)`` from a discovery payload.

    Raises SidecarError without embedding url/token in the message.
    """
    if discovery.get("schemaVersion") != 1:
        raise SidecarError("Unsupported bridge discovery schema")
    if discovery.get("transport") != "tcp" or discovery.get("protocol") != "connect":
        raise SidecarError("Unsupported bridge transport discovery payload")
    url = str(discovery.get("url") or "")
    if not url:
        host = str(discovery.get("host") or "")
        port = discovery.get("port")
        if not host or not port:
            raise SidecarError("Bridge discovery payload is missing a URL")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        url = f"http://{host}:{port}"
    token = str(discovery.get("authToken") or "").strip()
    token_file = discovery.get("authTokenFile")
    if not token and token_file:
        try:
            token = Path(str(token_file)).read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    if not token:
        raise SidecarError("Bridge discovery payload is missing an auth token")
    pid = int(discovery["pid"]) if discovery.get("pid") is not None else None
    return url, token, pid


def _proc_starttime(pid: int) -> int | None:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    rparen = stat_text.rfind(")")
    if rparen < 0:
        return None
    fields = stat_text[rparen + 2 :].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _proc_ppid(pid: int) -> int | None:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    rparen = stat_text.rfind(")")
    if rparen < 0:
        return None
    fields = stat_text[rparen + 2 :].split()
    try:
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _write_secret_file(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _wipe_sidecar_files(paths: dict[str, Path]) -> None:
    for key in ("pid", "url", "token", "meta", "stderr"):
        _unlink_if_exists(paths[key])


def _read_meta(paths: dict[str, Path]) -> tuple[int, int | None] | None:
    meta_path = paths["meta"]
    pid_path = paths["pid"]
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            pid = int(data["pid"])
            starttime = data.get("starttime")
            starttime_i = int(starttime) if starttime is not None else None
            return pid, starttime_i
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    if pid_path.is_file():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return pid, None
    return None


def running_sidecar(paths: dict[str, Path]) -> dict[str, Any] | None:
    info = _read_meta(paths)
    if info is None:
        return None
    pid, starttime = info
    if not pid_alive(pid):
        return None
    if starttime is not None:
        live_start = _proc_starttime(pid)
        if live_start is None or live_start != starttime:
            return None
    if not paths["url"].is_file() or not paths["token"].is_file():
        return None
    workspace = paths["workspace"]
    return {
        "pid": pid,
        "ppid": _proc_ppid(pid),
        "rundir": str(paths["rundir"]),
        "url_file": str(paths["url"]),
        "token_file": str(paths["token"]),
        "workspace": str(workspace) if workspace.exists() else None,
        "state": "present",
    }


def resolve_launcher(command: str | None = None) -> str:
    if command:
        path = Path(command).expanduser()
        if not path.is_file():
            raise SidecarError("Bridge command does not point to a file")
        return str(path.resolve())
    override = (os.environ.get("CURSOR_SDK_BRIDGE_BIN") or "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise SidecarError("CURSOR_SDK_BRIDGE_BIN does not point to a file")
        return str(path.resolve())
    try:
        from cursor_sdk._vendor import resolve_bridge_path

        return resolve_bridge_path()
    except Exception as exc:  # noqa: BLE001 — map vendor errors to SidecarError
        raise SidecarError("Unable to locate cursor-sdk-bridge") from exc


def _double_fork_exec(argv: list[str], stderr_path: Path) -> int:
    """Detach with setsid + double-fork and exec argv. Return grandchild pid.

    The grandchild is not a child of ansible-playbook (expect ppid 1).
    """
    r_fd, w_fd = os.pipe()
    pid = os.fork()
    if pid > 0:
        os.close(w_fd)
        chunks = []
        while True:
            chunk = os.read(r_fd, 64)
            if not chunk:
                break
            chunks.append(chunk)
        os.close(r_fd)
        os.waitpid(pid, 0)
        raw = b"".join(chunks).strip()
        if not raw:
            raise SidecarError("Failed to start sidecar")
        try:
            return int(raw)
        except ValueError:
            raise SidecarError("Failed to start sidecar") from None

    os.close(r_fd)
    try:
        os.setsid()
        pid2 = os.fork()
        if pid2 > 0:
            os.write(w_fd, str(pid2).encode("ascii"))
            os.close(w_fd)
            os._exit(0)
        os.close(w_fd)
        os.chdir("/")
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        err = os.open(os.fspath(stderr_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(err, 2)
        if devnull > 2:
            os.close(devnull)
        if err > 2:
            os.close(err)
        if os.path.sep in argv[0]:
            os.execv(argv[0], argv)
        os.execvp(argv[0], argv)
    except Exception:  # noqa: BLE001 — grandchild cannot raise to parent
        try:
            os.close(w_fd)
        except OSError:
            pass
        os._exit(1)
    os._exit(1)


def wait_for_ready(stderr_path: Path, timeout: float, pid: int | None = None) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid is not None and not pid_alive(pid):
            raise SidecarError("Bridge exited before discovery")
        if stderr_path.is_file():
            try:
                text = stderr_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for raw_line in text.splitlines():
                discovery = parse_discovery_line(raw_line if raw_line.endswith("\n") else raw_line + "\n")
                if discovery is not None:
                    return discovery
        time.sleep(0.05)
    raise SidecarError("Timed out waiting for bridge discovery")


def _terminate(pid: int, grace_seconds: float = 5.0) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.05)


def start_sidecar(
    *,
    rundir: str | os.PathLike[str] | None = None,
    workspace: str | os.PathLike[str] | None = None,
    timeout: float = 120.0,
    command: str | None = None,
) -> dict[str, Any]:
    """Daemonize the vendor bridge and write url/token/pid under rundir (0600)."""
    paths = sidecar_paths(rundir or default_rundir())
    existing = running_sidecar(paths)
    if existing is not None:
        return dict(existing, changed=False)

    paths["rundir"].mkdir(parents=True, exist_ok=True)
    os.chmod(paths["rundir"], 0o700)
    workspace_path = Path(workspace).expanduser() if workspace else paths["workspace"]
    workspace_path.mkdir(parents=True, exist_ok=True)

    launcher = resolve_launcher(command)
    argv = [launcher, "--workspace", str(workspace_path)]
    _unlink_if_exists(paths["stderr"])

    gpid: int | None = None
    try:
        gpid = _double_fork_exec(argv, paths["stderr"])
        discovery = wait_for_ready(paths["stderr"], timeout, pid=gpid)
        url, token, disc_pid = endpoint_from_discovery(discovery)
        pid = disc_pid or gpid
        starttime = _proc_starttime(pid)
        _write_secret_file(paths["url"], url + "\n")
        _write_secret_file(paths["token"], token + "\n")
        paths["pid"].write_text(f"{pid}\n", encoding="utf-8")
        meta = {"pid": pid}
        if starttime is not None:
            meta["starttime"] = starttime
        paths["meta"].write_text(json.dumps(meta) + "\n", encoding="utf-8")
        _unlink_if_exists(paths["stderr"])
        return {
            "changed": True,
            "pid": pid,
            "ppid": _proc_ppid(pid),
            "rundir": str(paths["rundir"]),
            "url_file": str(paths["url"]),
            "token_file": str(paths["token"]),
            "workspace": str(workspace_path),
            "state": "present",
        }
    except Exception:
        if gpid is not None:
            _terminate(gpid)
        _wipe_sidecar_files(paths)
        raise


def stop_sidecar(*, rundir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Kill the pid from the pidfile and unlink the token file. Idempotent."""
    paths = sidecar_paths(rundir or default_rundir())
    info = _read_meta(paths)
    files_present = any(paths[key].exists() for key in ("pid", "url", "token", "meta", "stderr"))
    if info is None:
        _wipe_sidecar_files(paths)
        return {"changed": files_present, "state": "absent"}

    pid, starttime = info
    matches = pid_alive(pid) and (starttime is None or _proc_starttime(pid) == starttime)
    if matches:
        _terminate(pid)
    _wipe_sidecar_files(paths)
    return {"changed": True, "state": "absent"}
