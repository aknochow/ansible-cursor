# SPDX-License-Identifier: Apache-2.0
"""Map the operator `effort` knob onto Cursor catalog params.

Reasoning is optional capability metadata. Send `effort`, `reasoning`, or
`reasoning_effort` only when that model exposes it, and only when the value
is in the catalog allow-list. Never send `thinking`, `fast`, `context`, or
`enable_thinking` from this option — those are separate settings (and
`enable_thinking` belongs to local/Qwen adapters, not Cursor).

Catalog snapshot: Cursor.models.list() on 2026-09-09 for a Cursor Pro key.
Exact ids win. Prefix fallbacks cover newer grok-*/gpt-*/gemini-3.8-* ids
without guessing Claude (some Claude ids have no effort param).
"""

from __future__ import annotations

from typing import NamedTuple

PARAM_EFFORT = "effort"
PARAM_REASONING = "reasoning"
PARAM_REASONING_EFFORT = "reasoning_effort"

_EFFORT_LIKE = frozenset({PARAM_EFFORT, PARAM_REASONING, PARAM_REASONING_EFFORT})

# Operator values the module argument_spec accepts. Per-model subsets are
# narrower; resolve_effort_param enforces those.
OPERATOR_EFFORT_VALUES = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "extra-high",
    "max",
)

_VALUE_ALIASES = {
    "xhigh": "extra-high",
    "extra-high": "xhigh",
}


class EffortCapability(NamedTuple):
    param_id: str
    values: frozenset[str]


def _cap(param_id: str, *values: str) -> EffortCapability:
    return EffortCapability(param_id, frozenset(values))


# Exact ids from the 2026-09-09 catalog that expose an effort-like param.
CAPABILITIES: dict[str, EffortCapability] = {
    "grok-4.6": _cap(PARAM_EFFORT, "low", "medium", "high", "xhigh"),
    "grok-4.5": _cap(PARAM_EFFORT, "low", "medium", "high"),
    "claude-opus-5": _cap(PARAM_EFFORT, "low", "medium", "high", "xhigh", "max"),
    "claude-opus-4-8": _cap(PARAM_EFFORT, "low", "medium", "high", "xhigh", "max"),
    "claude-opus-4-7": _cap(PARAM_EFFORT, "low", "medium", "high", "xhigh", "max"),
    "claude-opus-4-6": _cap(PARAM_EFFORT, "low", "medium", "high", "max"),
    "claude-sonnet-5": _cap(PARAM_EFFORT, "low", "medium", "high", "xhigh", "max"),
    "claude-sonnet-4-6": _cap(PARAM_EFFORT, "low", "medium", "high", "max"),
    "claude-fable-5-1": _cap(PARAM_EFFORT, "low", "medium", "high", "xhigh", "max"),
    "claude-fable-5": _cap(PARAM_EFFORT, "low", "medium", "high", "xhigh", "max"),
    "gemini-3.7-flash": _cap(PARAM_EFFORT, "low", "medium", "high"),
    "gemini-3.6-flash": _cap(PARAM_EFFORT, "minimal", "low", "medium", "high"),
    "muse-spark-1.3": _cap(PARAM_EFFORT, "minimal", "low", "medium", "high", "xhigh", "max"),
    "gpt-5.6-luna": _cap(PARAM_REASONING, "none", "low", "medium", "high", "xhigh", "max"),
    "gpt-5.6-terra": _cap(PARAM_REASONING, "none", "low", "medium", "high", "xhigh", "max"),
    "gpt-5.6-sol": _cap(PARAM_REASONING, "none", "low", "medium", "high", "xhigh", "max"),
    "gpt-5.5": _cap(PARAM_REASONING, "none", "low", "medium", "high", "extra-high"),
    "gpt-5.4": _cap(PARAM_REASONING, "none", "low", "medium", "high", "extra-high"),
    "gpt-5.4-mini": _cap(PARAM_REASONING, "none", "low", "medium", "high", "xhigh"),
    "gpt-5.4-nano": _cap(PARAM_REASONING, "none", "low", "medium", "high", "xhigh"),
    "gpt-5.3-codex": _cap(PARAM_REASONING, "low", "medium", "high", "extra-high"),
    "gpt-5.2": _cap(PARAM_REASONING, "low", "medium", "high", "extra-high"),
    "gpt-5.1": _cap(PARAM_REASONING, "low", "medium", "high"),
    "gemini-3.8-flash": _cap(PARAM_REASONING_EFFORT, "low", "medium", "high"),
    "kimi-k3": _cap(PARAM_REASONING, "low", "high", "max"),
    "glm-5.2": _cap(PARAM_REASONING, "high", "max"),
}

# Catalog ids with no effort-like param (thinking/fast/context-only or empty).
NO_EFFORT_PARAM: frozenset[str] = frozenset(
    {
        "default",
        "composer-2.5",
        "composer-2",
        "claude-opus-4-5",
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4",
        "gemini-3.1-pro",
        "gemini-3-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gpt-5-mini",
        "kimi-k2.7-code",
    }
)


class UnsupportedEffortValue(ValueError):
    """Caller asked for a value this model does not list."""


def _canonicalize(value: str, allowed: frozenset[str]) -> str | None:
    if value in allowed:
        return value
    alias = _VALUE_ALIASES.get(value)
    if alias is not None and alias in allowed:
        return alias
    return None


def _prefix_capability(model_id: str) -> EffortCapability | None:
    """Conservative fallback for ids newer than the snapshot.

    Claude is omitted on purpose: several Claude ids have no effort param.
    """
    if model_id.startswith("grok-"):
        return _cap(PARAM_EFFORT, "low", "medium", "high")
    if model_id.startswith("gpt-"):
        return _cap(PARAM_REASONING, "low", "medium", "high")
    if model_id.startswith("gemini-3.8-"):
        return _cap(PARAM_REASONING_EFFORT, "low", "medium", "high")
    return None


def capability_for(model_id: str) -> EffortCapability | None:
    """Return the effort-like catalog param, or None when it must not be sent."""
    if model_id in NO_EFFORT_PARAM:
        return None
    found = CAPABILITIES.get(model_id)
    if found is not None:
        return found
    return _prefix_capability(model_id)


def resolve_effort_param(model_id: str, effort: str | None) -> tuple[str, str] | None:
    """Map operator effort onto a single catalog param.

    Returns (param_id, value) to put on ModelSelection.params, or None when
    the param must be omitted (unset effort, or model has no effort-like
    capability). Raises UnsupportedEffortValue when the model supports the
    param but not this value.
    """
    if effort is None or effort == "":
        return None

    cap = capability_for(model_id)
    if cap is None:
        return None
    if cap.param_id not in _EFFORT_LIKE:
        return None

    canonical = _canonicalize(effort, cap.values)
    if canonical is None:
        allowed = ", ".join(sorted(cap.values))
        raise UnsupportedEffortValue(
            f"model {model_id} rejects {cap.param_id}={effort!r}; allowed: {allowed}"
        )
    return cap.param_id, canonical
