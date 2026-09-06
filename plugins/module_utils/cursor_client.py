# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

PROVIDER_ARGSPEC = dict(
    api_key=dict(type="str", no_log=True),
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


def flatten_run(result, *, structured=None) -> dict[str, Any]:
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
    return out


def resolve_tools(tools, structured_tool) -> list[str] | None:
    """Choose the SDK tools allowlist.

    Live spike 2026-09-06: tools=[] hides CustomTool (mcp is stripped).
    A structured_tool therefore requires mcp in the allowlist. When the
    caller omits tools and sets structured_tool, default to ["mcp"].
    When they pass tools=[] with structured_tool, that is an error.
    """
    if structured_tool and tools == []:
        raise ValueError(
            "structured_tool requires the mcp tool to be offered; tools=[] hides custom tools. "
            "Omit tools (defaults to [mcp]) or include mcp in the list."
        )
    if tools is None and structured_tool:
        return ["mcp"]
    return tools
