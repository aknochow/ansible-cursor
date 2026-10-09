# SPDX-License-Identifier: Apache-2.0

"""Start serialization and retry. No live SDK and no CURSOR_API_KEY."""

from __future__ import annotations

import fcntl
import hashlib
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _params(cwd: str) -> dict:
    return dict(
        prompt="x",
        model="grok-4.6",
        cwd=cwd,
        api_key="cursor_test",
        effort=None,
        tools=[],
        disallowed_tools=None,
        structured_tool=None,
        agents=None,
        setting_sources=[],
        mode=None,
    )


def _finished():
    return SimpleNamespace(
        result="pong",
        status="finished",
        model=SimpleNamespace(id="grok-4.6"),
        agent_id="agent-1",
        id="run-1",
        duration_ms=10,
        usage=None,
    )


def _lock_path(cwd: str):
    root = Path(os.environ["ANSIBLE_CURSOR_START_LOCK_DIR"])
    digest = hashlib.sha256(cwd.encode("utf-8")).hexdigest()
    return root / f"agent-start-{digest}.lock"


def _lock_held(path) -> bool:
    if not path.exists():
        return False
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _install(monkeypatch):
    from ansible_collections.aknochow.cursor.plugins.modules import agent as agent_module

    tls = threading.local()

    def ansible_module(**kwargs):
        return tls.module

    monkeypatch.setattr(agent_module, "AnsibleModule", ansible_module)
    monkeypatch.delenv("CURSOR_SDK_BRIDGE_URL", raising=False)
    monkeypatch.delenv("CURSOR_SDK_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("CURSOR_SDK_BRIDGE_AUTH_TOKEN", raising=False)

    mock_sdk = MagicMock()
    mock_sdk.CursorAgentError = type("CursorAgentError", (Exception,), {})
    mock_sdk.AgentOptions = SimpleNamespace
    mock_sdk.LocalAgentOptions = SimpleNamespace
    mock_sdk.ModelSelection = SimpleNamespace
    mock_sdk.ModelParameterValue = SimpleNamespace
    mock_sdk.AgentDefinition = SimpleNamespace

    import sys

    monkeypatch.setitem(sys.modules, "cursor_sdk", mock_sdk)
    return agent_module, tls, mock_sdk


def _bind_module(tls, cwd: str):
    module = MagicMock()
    module.params = _params(cwd)
    tls.module = module
    return module


def _agent(mock_sdk, *, on_send=None):
    agent = MagicMock()
    agent.agent_id = "agent-1"
    run = MagicMock()
    run.events.side_effect = lambda: iter(())
    run.wait.return_value = _finished()

    def send(prompt):
        if on_send is not None:
            on_send()
        return run

    agent.send.side_effect = send
    return agent


def _run_pair(agent_module, tls, cwd_a: str, cwd_b: str):
    errors = []

    def run(cwd):
        try:
            _bind_module(tls, cwd)
            agent_module.main()
        except Exception as exc:  # noqa: BLE001 — surface thread failures
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(cwd,)) for cwd in (cwd_a, cwd_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    alive = [thread.is_alive() for thread in threads]
    return errors, alive


def test_same_cwd_starts_are_serialized(monkeypatch):
    agent_module, tls, mock_sdk = _install(monkeypatch)
    cwd = "/tmp/review-same"
    state = {"active": 0, "max": 0}
    gate = threading.Lock()
    lock_path = _lock_path(cwd)

    def launch_bridge(**kwargs):
        with gate:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        try:
            deadline = time.monotonic() + 0.4
            while time.monotonic() < deadline:
                with gate:
                    if state["active"] >= 2:
                        break
                time.sleep(0.01)
        finally:
            with gate:
                state["active"] -= 1
        return MagicMock()

    mock_sdk.Client.launch_bridge.side_effect = launch_bridge
    mock_sdk.Agent.create.side_effect = lambda options, client=None: _agent(mock_sdk)
    errors, alive = _run_pair(agent_module, tls, cwd, cwd)
    assert errors == []
    assert alive == [False, False]
    assert state["max"] == 1
    assert lock_path.is_file()


def test_different_cwd_starts_are_not_serialized(monkeypatch):
    agent_module, tls, mock_sdk = _install(monkeypatch)
    cwd_a = "/tmp/review-a"
    cwd_b = "/tmp/review-b"
    state = {"active": 0, "max": 0}
    gate = threading.Lock()

    def launch_bridge(**kwargs):
        with gate:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        try:
            deadline = time.monotonic() + 0.4
            while time.monotonic() < deadline:
                with gate:
                    if state["active"] >= 2:
                        break
                time.sleep(0.01)
        finally:
            with gate:
                state["active"] -= 1
        return MagicMock()

    mock_sdk.Client.launch_bridge.side_effect = launch_bridge
    mock_sdk.Agent.create.side_effect = lambda options, client=None: _agent(mock_sdk)
    errors, alive = _run_pair(agent_module, tls, cwd_a, cwd_b)
    assert errors == []
    assert alive == [False, False]
    assert state["max"] == 2
    assert _lock_path(cwd_a).is_file()
    assert _lock_path(cwd_b).is_file()
    assert _lock_path(cwd_a) != _lock_path(cwd_b)


@pytest.mark.parametrize(
    ("message", "where"),
    [
        ("internal: database is locked", "create"),
        ("Network request failed", "launch"),
        ("resource_exhausted", "create"),
    ],
)
def test_retryable_start_error_then_succeeds(monkeypatch, message, where):
    agent_module, tls, mock_sdk = _install(monkeypatch)
    cwd = f"/tmp/review-{where}"
    module = _bind_module(tls, cwd)
    lock_path = _lock_path(cwd)
    calls = {"launch": 0, "create": 0}
    closed = []
    held_during_create = []
    free_during_send = []

    def launch_bridge(**kwargs):
        calls["launch"] += 1
        if where == "launch" and calls["launch"] == 1:
            raise mock_sdk.CursorAgentError(message)
        client = MagicMock()
        client.close.side_effect = lambda: closed.append(client)
        return client

    def create(options, client=None):
        calls["create"] += 1
        held_during_create.append(_lock_held(lock_path))
        if where == "create" and calls["create"] == 1:
            raise mock_sdk.CursorAgentError(message)

        def on_send():
            free_during_send.append(not _lock_held(lock_path))

        return _agent(mock_sdk, on_send=on_send)

    mock_sdk.Client.launch_bridge.side_effect = launch_bridge
    mock_sdk.Agent.create.side_effect = create
    agent_module.main()
    assert calls["launch"] == 2
    assert module.exit_json.called
    assert module.fail_json.called is False
    assert held_during_create == [True] or held_during_create == [True, True]
    assert free_during_send == [True]
    if where == "create":
        assert closed, "the client from the failed start was not closed"


def test_unrelated_start_error_fails_on_the_first_attempt(monkeypatch):
    agent_module, tls, mock_sdk = _install(monkeypatch)
    module = _bind_module(tls, "/tmp/review-other")
    sleeps = []
    if hasattr(agent_module, "time"):
        monkeypatch.setattr(agent_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    calls = {"launch": 0}

    def launch_bridge(**kwargs):
        calls["launch"] += 1
        return MagicMock()

    def create(options, client=None):
        raise mock_sdk.CursorAgentError("model is not available")

    mock_sdk.Client.launch_bridge.side_effect = launch_bridge
    mock_sdk.Agent.create.side_effect = create
    agent_module.main()
    assert calls["launch"] == 1
    assert sleeps == []
    module.exit_json.assert_not_called()
    module.fail_json.assert_called_once()
    assert module.fail_json.call_args.kwargs["msg"] == "Cursor agent failed to start: model is not available"


def test_retry_gives_up_after_the_time_budget_with_the_original_message(monkeypatch):
    agent_module, tls, mock_sdk = _install(monkeypatch)
    module = _bind_module(tls, "/tmp/review-budget")
    clock = {"t": 1_000.0, "sleeps": []}
    if hasattr(agent_module, "time"):
        monkeypatch.setattr(agent_module.time, "monotonic", lambda: clock["t"])

        def sleep(seconds):
            clock["sleeps"].append(seconds)
            clock["t"] += seconds

        monkeypatch.setattr(agent_module.time, "sleep", sleep)
    if hasattr(agent_module, "random"):
        monkeypatch.setattr(agent_module.random, "random", lambda: 0.0)
    calls = {"launch": 0}

    def launch_bridge(**kwargs):
        calls["launch"] += 1
        raise mock_sdk.CursorAgentError("internal: database is locked")

    mock_sdk.Client.launch_bridge.side_effect = launch_bridge
    mock_sdk.Agent.create.side_effect = lambda options, client=None: _agent(mock_sdk)
    agent_module.main()
    module.exit_json.assert_not_called()
    module.fail_json.assert_called_once()
    assert module.fail_json.call_args.kwargs["msg"] == (
        "Cursor agent failed to start: internal: database is locked"
    )
    assert calls["launch"] >= 2
    assert clock["sleeps"]
    assert sum(clock["sleeps"]) == pytest.approx(60.0)
    assert clock["t"] == pytest.approx(1_060.0)
