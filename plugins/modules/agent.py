#!/usr/bin/python
# Copyright: (c) 2026, Adam Knochowski (@aknochow)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
---
module: agent
short_description: Run a Cursor local agent via cursor-sdk
description:
  - One-shot C(Agent.prompt) against the official Cursor Python SDK.
  - Draws on a Cursor Pro (or higher) API key. First-party ids (Grok,
    Composer) use the Cursor Models pool; third-party ids (GPT, Claude,
    Gemini, ...) use the Other Models / API pool. Not an OpenAI-compatible
    chat-completions endpoint.
  - Structured results are optional custom-tool arguments, not generation-time
    JSON Schema. The model can skip the tool; callers must assert on RV(structured).
  - Cloud agents are not implemented in this version.
version_added: "0.1.0"
author:
  - Adam Knochowski (@aknochow)
options:
  prompt:
    description:
      - User message sent to the agent.
    type: str
    required: true
  model:
    description:
      - Model id as returned by C(Cursor.models.list()), for example V(grok-4.6)
        or V(composer-2.5). There is no collection default; pick an id your
        account can actually use.
    type: str
    required: true
  effort:
    description:
      - Operator reasoning/effort knob. Mapped onto the catalog param that
        model actually exposes (C(effort), C(reasoning), or
        C(reasoning_effort)).
      - Omitted entirely when the model has no effort-like param (Composer,
        some Claude/Gemini/GPT ids) or when this option is unset. Never sent
        as C(thinking), C(fast), C(context), or C(enable_thinking).
      - Values are model-specific. C(xhigh) aliases to C(extra-high) on GPT
        ids that only list that name. An unsupported value fails the module
        rather than being forwarded for the API to reject.
    type: str
    choices: [none, minimal, low, medium, high, xhigh, extra-high, max]
  tools:
    description:
      - Built-in tools to offer. An empty list offers none.
      - Omitted with O(structured_tool) set defaults to V([mcp]), because custom
        tools are not offered when mcp is absent (measured 2026-09-06).
      - An explicit list that omits V(mcp) with O(structured_tool) set fails
        rather than running without the custom tool.
    type: list
    elements: str
  disallowed_tools:
    description:
      - Built-in tools to remove from the default set. Deny wins.
    type: list
    elements: str
  structured_tool:
    description:
      - Optional custom tool whose arguments are returned as RV(structured).
      - Requires mcp to be offered (see O(tools)). Not generation-constrained;
        the model may finish without calling it.
    type: dict
    suboptions:
      name:
        description: Tool name the model should call.
        type: str
        required: true
      description:
        description: Tool description shown to the model.
        type: str
        required: true
      input_schema:
        description: JSON Schema object for the tool arguments.
        type: dict
        required: true
  agents:
    description:
      - Named subagent definitions. Each value needs C(description) and C(prompt)
        (instructions for that subagent). Used when you need a trusted instruction
        channel; the parent agent has no equivalent field.
    type: dict
  setting_sources:
    description:
      - Ambient Cursor settings layers to load. Empty list means inline config
        only, which is the safe default for review integrity.
    type: list
    elements: str
    default: []
  mode:
    description:
      - Initial conversation mode.
    type: str
    choices: [agent, plan]
  bridge_timeout:
    description:
      - Seconds to wait for C(cursor-sdk-bridge ready) on stderr. The SDK
        default is 30; this module waits 120 because a nested Cursor-agent
        session can SIGKILL the vendor node or leave a wedged bridge that
        then misses a short discovery window. Not a generation or tool-turn
        budget.
    type: float
    default: 120
extends_documentation_fragment:
  - aknochow.cursor.auth
"""

EXAMPLES = r"""
- name: One-shot local ping
  aknochow.cursor.agent:
    prompt: Reply with the single word pong.
    model: grok-4.6
    effort: high
    cwd: /tmp
    tools: []
  register: ping

- name: Other Models pool (GPT-5.6 Luna) with high reasoning
  aknochow.cursor.agent:
    prompt: Reply with the single word pong.
    model: gpt-5.6-luna
    effort: high
    cwd: /tmp
    tools: []

- name: Structured extraction via custom tool
  aknochow.cursor.agent:
    prompt: A domestic housecat. Call report_animal with the animal and leg count.
    model: grok-4.6
    effort: high
    cwd: /tmp
    structured_tool:
      name: report_animal
      description: Submit the classified animal and leg count.
      input_schema:
        type: object
        properties:
          animal:
            type: string
          legs:
            type: integer
        required: [animal, legs]
  register: classified
"""

RETURN = r"""
text:
  description: Final assistant text from the run.
  type: str
  returned: always
status:
  description: Terminal run status (for example C(finished) or C(error)).
  type: str
  returned: always
resolved_model:
  description: Model id reported on the run.
  type: str
  returned: when the SDK reports one
agent_id:
  description: Durable local agent id.
  type: str
  returned: always
run_id:
  description: Run id for this prompt.
  type: str
  returned: always
duration_ms:
  description: Wall-clock duration of the run in milliseconds.
  type: int
  returned: when reported
usage_normalized:
  description: Token usage in the family-fixed shape.
  type: dict
  returned: always
  contains:
    input_tokens:
      description: Prompt tokens consumed by the run.
      type: int
    output_tokens:
      description: Completion tokens produced by the run.
      type: int
    cache_read_tokens:
      description: Tokens read from cache.
      type: int
    cache_write_tokens:
      description: Tokens written to cache.
      type: int
    thinking_tokens:
      description: Reasoning tokens, mapped from the SDK reasoning_tokens field.
      type: int
    total_tokens:
      description: Total tokens for the run, or input plus output when omitted.
      type: int
structured:
  description: Arguments of the last O(structured_tool) call, when one happened.
  type: dict
  returned: when structured_tool was set and the model called it
effort_param:
  description: Catalog param actually sent for O(effort), when one was sent.
  type: dict
  returned: when O(effort) mapped onto a catalog param
  contains:
    id:
      description: Catalog parameter id (C(effort), C(reasoning), or C(reasoning_effort)).
      type: str
    value:
      description: Canonical value sent after aliasing.
      type: str
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
    DEFAULT_BRIDGE_TIMEOUT,
    PROVIDER_ARGSPEC,
    flatten_run,
    resolve_tools,
)
from ansible_collections.aknochow.cursor.plugins.module_utils.model_params import (
    OPERATOR_EFFORT_VALUES,
    UnsupportedEffortValue,
    resolve_effort_param,
)

_STRUCTURED_TOOL_KEYS = ("name", "description", "input_schema")


def _structured_capture(structured_tool):
    """Build a CustomTool whose execute records arguments for RV(structured)."""
    from cursor_sdk import CustomTool

    if not isinstance(structured_tool, dict):
        raise ValueError(
            "structured_tool requires name, description, and input_schema"
        )
    missing = [key for key in _STRUCTURED_TOOL_KEYS if structured_tool.get(key) is None]
    if missing:
        raise ValueError(
            "structured_tool requires name, description, and input_schema "
            f"(missing: {', '.join(missing)})"
        )

    captured = []
    spec = structured_tool

    def execute(args, context):  # noqa: ARG001
        captured.append(dict(args))
        return "recorded"

    tool = CustomTool(
        execute=execute,
        description=spec["description"],
        input_schema=spec["input_schema"],
    )
    return spec["name"], tool, captured


def _build_options(params, AgentOptions, LocalAgentOptions, ModelSelection, ModelParameterValue, AgentDefinition):
    model_id = params["model"]
    try:
        effort_param = resolve_effort_param(model_id, params.get("effort"))
    except UnsupportedEffortValue as exc:
        return None, str(exc), None
    if effort_param:
        param_id, value = effort_param
        model = ModelSelection(id=model_id, params=(ModelParameterValue(id=param_id, value=value),))
    else:
        model = model_id

    structured_tool = params.get("structured_tool")
    custom_tools = None
    captured = []
    try:
        tools = resolve_tools(params.get("tools"), structured_tool)
        if structured_tool is not None:
            name, tool, captured = _structured_capture(structured_tool)
            custom_tools = {name: tool}
    except ValueError as exc:
        return None, str(exc), None

    agents = None
    raw_agents = params.get("agents") or None
    if raw_agents:
        agents = {}
        for key, spec in raw_agents.items():
            if not isinstance(spec, dict) or "description" not in spec or "prompt" not in spec:
                return None, f"agents.{key} needs description and prompt", None
            agents[key] = AgentDefinition(
                description=spec["description"],
                prompt=spec["prompt"],
                model=spec.get("model"),
            )

    kwargs = dict(
        api_key=params.get("api_key") or None,
        model=model,
        local=LocalAgentOptions(
            cwd=params["cwd"],
            setting_sources=params.get("setting_sources") or [],
            custom_tools=custom_tools,
        ),
    )
    if tools is not None:
        kwargs["tools"] = tools
    if params.get("disallowed_tools"):
        kwargs["disallowed_tools"] = params["disallowed_tools"]
    if agents:
        kwargs["agents"] = agents
    if params.get("mode"):
        kwargs["mode"] = params["mode"]

    return AgentOptions(**kwargs), captured, effort_param


def _effort_return(effort_param):
    if not effort_param:
        return {}
    return {"effort_param": {"id": effort_param[0], "value": effort_param[1]}}


def main():
    argument_spec = dict(
        prompt=dict(type="str", required=True),
        model=dict(type="str", required=True),
        effort=dict(type="str", choices=list(OPERATOR_EFFORT_VALUES)),
        tools=dict(type="list", elements="str"),
        disallowed_tools=dict(type="list", elements="str"),
        structured_tool=dict(
            type="dict",
            options=dict(
                name=dict(type="str", required=True),
                description=dict(type="str", required=True),
                input_schema=dict(type="dict", required=True),
            ),
        ),
        agents=dict(type="dict"),
        setting_sources=dict(type="list", elements="str", default=[]),
        mode=dict(type="str", choices=["agent", "plan"]),
        bridge_timeout=dict(type="float", default=DEFAULT_BRIDGE_TIMEOUT),
    )
    argument_spec.update(PROVIDER_ARGSPEC)

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=False,
    )

    try:
        from cursor_sdk import (
            Agent,
            AgentDefinition,
            AgentOptions,
            Client,
            CursorAgentError,
            LocalAgentOptions,
            ModelParameterValue,
            ModelSelection,
        )
    except ImportError:
        module.fail_json(msg="The cursor-sdk Python package is required. Install it with: pip install 'cursor-sdk>=1.0.31'")
        return

    options, captured_or_err, effort_param = _build_options(
        module.params,
        AgentOptions,
        LocalAgentOptions,
        ModelSelection,
        ModelParameterValue,
        AgentDefinition,
    )
    if options is None:
        module.fail_json(msg=captured_or_err)
        return

    captured = captured_or_err
    client = None
    try:
        # Own the bridge: workspace is the caller cwd (the repo under
        # review), not ansible-playbook's process cwd. close() reaps the
        # vendor node on both success and start failure.
        client = Client.launch_bridge(
            workspace=module.params["cwd"],
            timeout=module.params.get("bridge_timeout") or DEFAULT_BRIDGE_TIMEOUT,
            allow_api_key_env_fallback=True,
        )
        result = Agent.prompt(module.params["prompt"], options, client=client)
    except CursorAgentError as err:
        module.fail_json(msg=f"Cursor agent failed to start: {err}")
        return
    except Exception as err:  # noqa: BLE001 — surface unexpected SDK errors to Ansible
        module.fail_json(msg=f"Cursor agent raised: {err}")
        return
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 — never mask the run result
                pass

    status = getattr(result, "status", None)
    status_s = status if isinstance(status, str) else str(status)
    if status_s.split(".")[-1] == "error" or status_s == "error":
        module.fail_json(
            msg=f"Cursor run finished with status error (run_id={getattr(result, 'id', None)})",
            **flatten_run(result, structured=(captured[-1] if captured else None)),
            **_effort_return(effort_param),
        )
        return

    structured = captured[-1] if captured else None
    module.exit_json(
        changed=False,
        **flatten_run(result, structured=structured),
        **_effort_return(effort_param),
    )


if __name__ == "__main__":
    main()
