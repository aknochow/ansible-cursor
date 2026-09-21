# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ansible.module_utils.basic import env_fallback

# cursor-sdk Run.status values that mean the Send stream is done. wait()
# after a full events() drain must not WaitLiveRun these: that RPC on an
# already-finished run is the status=error flake.
_TERMINAL_RUN_STATUSES = frozenset({"finished", "error", "cancelled", "expired"})

# SDK Client._default_client() attach env. Token values must never be logged.
BRIDGE_URL_ENV = "CURSOR_SDK_BRIDGE_URL"
BRIDGE_TOKEN_ENVS = ("CURSOR_SDK_BRIDGE_TOKEN", "CURSOR_SDK_BRIDGE_AUTH_TOKEN")
# Path-only variants so a playbook can attach without set_fact of the token.
BRIDGE_URL_FILE_ENV = "CURSOR_SDK_BRIDGE_URL_FILE"
BRIDGE_TOKEN_FILE_ENV = "CURSOR_SDK_BRIDGE_TOKEN_FILE"

# SDK Bridge.launch default is 30s. Nested Cursor-agent sessions have
# SIGKILL'd the vendor node and left wedged bridges; 120s is bring-up
# only, not a generation budget.
DEFAULT_BRIDGE_TIMEOUT = 120.0


class AttachedBridgeIncomplete(ValueError):
    """URL or token set without the other. The message must not include values."""


def _read_secret_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def resolve_attached_bridge() -> tuple[str, str] | None:
    """Return (url, token) when a sidecar bridge is configured.

    Matches cursor_sdk.Client._default_client(): both URL and token required.
    File-path env vars are also accepted so playbooks never set_fact the token.
    Incomplete pairs raise AttachedBridgeIncomplete (no secret in the message).
    """
    url = (os.environ.get(BRIDGE_URL_ENV) or "").strip()
    if not url:
        url_file = (os.environ.get(BRIDGE_URL_FILE_ENV) or "").strip()
        if url_file:
            url = _read_secret_file(url_file)

    token = ""
    for key in BRIDGE_TOKEN_ENVS:
        token = (os.environ.get(key) or "").strip()
        if token:
            break
    if not token:
        token_file = (os.environ.get(BRIDGE_TOKEN_FILE_ENV) or "").strip()
        if token_file:
            token = _read_secret_file(token_file)

    if url and token:
        return url, token
    if url or token:
        raise AttachedBridgeIncomplete(
            "CURSOR_SDK_BRIDGE_URL and CURSOR_SDK_BRIDGE_TOKEN "
            "(or CURSOR_SDK_BRIDGE_AUTH_TOKEN) must be set together"
        )
    return None


PROVIDER_ARGSPEC = dict(
    api_key=dict(
        type="str",
        no_log=True,
        fallback=(env_fallback, ["CURSOR_API_KEY"]),
    ),
    cwd=dict(type="path", required=True),
)


def normalize_usage(usage) -> dict[str, int]:
    """Map cursor-sdk TokenUsage onto plaibook's usage_normalized keys.

    Missing values default to 0 so consumers can rely on every key existing.
    reasoning_tokens maps to thinking_tokens.
    """
    if usage is None:
        return dict(
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            thinking_tokens=0,
            total_tokens=0,
        )

    def _get(name: str) -> int:
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        return int(value or 0)

    input_tokens = _get("input_tokens")
    output_tokens = _get("output_tokens")
    return dict(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=_get("cache_read_tokens"),
        cache_write_tokens=_get("cache_write_tokens"),
        thinking_tokens=_get("reasoning_tokens"),
        total_tokens=_get("total_tokens") or (input_tokens + output_tokens),
    )


def _status_leaf(status) -> str:
    if status is None:
        return ""
    text = status if isinstance(status, str) else str(status)
    return text.split(".")[-1]


def is_terminal_run_status(status) -> bool:
    return _status_leaf(status) in _TERMINAL_RUN_STATUSES


def parent_stream_tool_call_ids(run, parent_agent_id: str | None = None) -> set[str]:
    """Collect parent-agent tool_call.call_id values from the run event stream.

    ``run.events()`` is consumable once (cursor-sdk 1.0.31). Callers that
    still need ``wait()`` must use ``result_after_parent_stream`` so a full
    drain does not WaitLiveRun an already-finished run.

    Nested-subagent custom-tool calls usually stay off this stream. When they
    leak onto it, they carry the child ``agent_id`` — those ids must not be
    treated as parent, or a real nested execute is classified parent and the
    named lens does not bind. CallCustomTool.agent_id on the HTTP callback is
    the tool *owner* (parent), not the caller; the stream event's agent_id is
    the caller.
    """
    ids: set[str] = set()
    if run is None or not hasattr(run, "events"):
        return ids
    parent = parent_agent_id or getattr(run, "agent_id", None) or ""
    for event in run.events():
        msg = getattr(event, "sdk_message", None)
        if getattr(msg, "type", None) != "tool_call":
            continue
        call_id = getattr(msg, "call_id", None)
        if not call_id:
            continue
        msg_agent = getattr(msg, "agent_id", None) or ""
        if parent and msg_agent and msg_agent != parent:
            continue
        ids.add(call_id)
    return ids


def result_after_parent_stream(run):
    """Terminal result after a full ``events()`` drain. Never WaitLiveRun.

    cursor-sdk ``Run.wait()`` drains leftover events, then returns
    ``_terminal_result`` only when the result envelope's inner ``result``
    field was a mapping. The usual wire shape has that field as the
    assistant *string*, so a completed drain leaves ``_terminal_result``
    unset and ``wait()`` calls WaitLiveRun on a run that already finished.
    That is the ``status=error`` flake (and the hang in
    https://forum.cursor.com/t/161858 when the drain was only partial).

    After ``events()`` is exhausted the handle already holds status / text /
    usage. Use those. Fall back to ``wait()`` only when the stream did not
    reach a terminal status (still running, or the object is a test double).
    """
    terminal = getattr(run, "_terminal_result", None)
    if terminal is not None:
        return run.wait()
    stream = getattr(run, "_event_stream", "unset")
    buffer = getattr(run, "_buffer", None)
    stream_exhausted = stream is None and not buffer
    if stream_exhausted and is_terminal_run_status(getattr(run, "status", None)):
        return SimpleNamespace(
            result=getattr(run, "result", None) or "",
            status=_status_leaf(getattr(run, "status", None)),
            model=getattr(run, "model", None),
            agent_id=getattr(run, "agent_id", None),
            id=getattr(run, "id", None),
            duration_ms=getattr(run, "duration_ms", None),
            usage=getattr(run, "usage", None),
        )
    return run.wait()


def tool_callback_server_of(client):
    """Return the in-process ToolCallbackServer for this Client, if any."""
    owned = getattr(client, "_owned_bridge", None)
    if owned is not None:
        server = getattr(owned, "_tool_callback_server", None)
        if server is not None:
            return server
    owner = getattr(client, "_connect_tool_callback_owner", None) or client
    return getattr(owner, "_connect_tool_callback_server", None)


def reregister_live_agent_custom_tools(client, agent_id, custom_tools) -> None:
    """Register host tools under the live agent id CreateAgent returned.

    prepare_agent_options_custom_tools mints a UUID onto the CreateAgent
    request. The server may return a different agentId. CallCustomTool then
    looks up the live id and misses — structured_tool never fires, the named
    lens never binds. Registering both ids is the fix; unknown child ids are
    handled by install_subagent_custom_tool_fallback.
    """
    server = tool_callback_server_of(client)
    if server is None or not custom_tools or not agent_id:
        return
    register = getattr(server, "register_agent", None)
    if callable(register):
        register(agent_id, custom_tools)


def install_subagent_custom_tool_fallback(client) -> None:
    """Resolve CallCustomTool for subagent ids against the parent's tools.

    Host execute handlers are registered per parent agent_id. The vendor
    node is documented to send the tool *owner* id, but nested Task
    subagents sometimes send the child id. Lookup misses, the lens cannot
    execute report_findings, and the run finishes unbound. One registered
    parent mapping is enough: fall back to it when the asked id is unknown.
    """
    server = tool_callback_server_of(client)
    if server is None or getattr(server, "_aknochow_subagent_fallback", False):
        return
    original = server._get_tools

    def _get_tools(agent_id: str):
        tools = original(agent_id)
        if tools is not None:
            return tools
        lock = getattr(server, "_lock", None)
        agents = getattr(server, "_agents", None)
        if not isinstance(agents, dict) or not agents:
            return None

        def _fallback():
            if agent_id in agents:
                return None
            return next(iter(agents.values()))

        if lock is None:
            return _fallback()
        with lock:
            return _fallback()

    server._get_tools = _get_tools
    server._aknochow_subagent_fallback = True


def annotate_structured_calls(
    captured,
    *,
    tool_name: str,
    parent_agent_id: str | None,
    parent_stream_call_ids: set[str],
) -> list[dict[str, Any]]:
    """Return every structured_tool execute, classified parent vs nested.

    Last-wins is a lie when a parent and a subagent both call the tool.
    Each record is {name, args, tool_call_id, agent_id, caller}.
    caller is ``parent`` when tool_call_id is on the parent stream;
    otherwise ``nested``. Nested agent_id is null: the SDK does not name
    the child on execute context or CallCustomTool.
    """
    calls: list[dict[str, Any]] = []
    for rec in captured or ():
        if isinstance(rec, dict) and "args" in rec:
            args = rec.get("args")
            tool_call_id = rec.get("tool_call_id")
        elif isinstance(rec, dict):
            args = dict(rec)
            tool_call_id = None
        else:
            continue
        on_parent = bool(tool_call_id) and tool_call_id in parent_stream_call_ids
        calls.append(
            {
                "name": tool_name,
                "args": args,
                "tool_call_id": tool_call_id,
                "agent_id": parent_agent_id if on_parent else None,
                "caller": "parent" if on_parent else "nested",
            }
        )
    return calls


def flatten_run(result, *, structured=None, structured_tool_calls=None) -> dict[str, Any]:
    """Flatten a cursor-sdk RunResult into this collection's return shape."""
    model = getattr(result, "model", None)
    resolved_model = None
    if model is not None:
        resolved_model = getattr(model, "id", None) or str(model)

    status = getattr(result, "status", None)
    if status is not None and not isinstance(status, str):
        status = str(status)

    out = dict(
        text=getattr(result, "result", None) or "",
        status=status,
        resolved_model=resolved_model,
        agent_id=getattr(result, "agent_id", None),
        run_id=getattr(result, "id", None),
        duration_ms=getattr(result, "duration_ms", None),
        usage_normalized=normalize_usage(getattr(result, "usage", None)),
    )
    if structured is not None:
        out["structured"] = structured
    if structured_tool_calls is not None:
        out["structured_tool_calls"] = structured_tool_calls
    return out


def resolve_tools(tools, structured_tool) -> list[str] | None:
    """Choose the SDK tools allowlist.

    Live spike 2026-09-06: tools=[] hides CustomTool (mcp is stripped).
    A structured_tool therefore requires mcp in the allowlist. When the
    caller omits tools and sets structured_tool, default to ["mcp"].
    An explicit list that omits mcp (empty or not) is an error — otherwise
    the custom tool is silently not offered and RV(structured) never appears.
    """
    if tools is None and structured_tool:
        return ["mcp"]
    if structured_tool and tools is not None and "mcp" not in tools:
        raise ValueError(
            "structured_tool requires the mcp tool to be offered; an explicit "
            "tools list without mcp hides custom tools. Omit tools (defaults "
            "to [mcp]) or include mcp in the list."
        )
    return tools
