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
  - One-shot local run (C(Agent.create) + C(send) + event drain + terminal
    result from the handle). Not C(Agent.prompt), which discards the parent
    event stream needed to classify who invoked a custom tool. After a full
    drain, C(wait) is not used when the handle is already terminal —
    WaitLiveRun on a finished run is the C(status=error) flake.
  - Draws on a Cursor Pro (or higher) API key. First-party ids (Grok,
    Composer) use the Cursor Models pool; third-party ids (GPT, Claude,
    Gemini, ...) use the Other Models / API pool. Not an OpenAI-compatible
    chat-completions endpoint.
  - Structured results are optional custom-tool arguments, not generation-time
    JSON Schema. The model can skip the tool. RV(structured) is the last
    execute (back-compat; last-call is not "the named subagent").
    RV(structured_tool_calls) is every execute, classified C(parent) vs
    C(nested) by joining C(tool_call_id) to the parent run's stream
    C(tool_call.call_id) values whose C(agent_id) is the parent. Nested
    custom-tool calls usually stay off that stream; when they leak, they
    carry the child agent id and stay C(nested). Callers that need the
    named subagent's payload must select C(caller=nested), not last-wins.
    Host custom tools are re-registered under the live C(agent_id) and
    unknown child ids fall back to the parent's tools so a Task subagent
    can actually execute the tool.
  - Cloud agents are not implemented in this version.
  - When E(CURSOR_SDK_BRIDGE_URL) and E(CURSOR_SDK_BRIDGE_TOKEN) (or
    E(CURSOR_SDK_BRIDGE_AUTH_TOKEN)) are both set, the module attaches to
    that sidecar and does not spawn the vendor node. Path-only variants
    E(CURSOR_SDK_BRIDGE_URL_FILE) / E(CURSOR_SDK_BRIDGE_TOKEN_FILE) are
    also accepted so a playbook can attach without C(set_fact) of the token.
    Use C(aknochow.cursor.bridge) to daemonize a sidecar from the playbook
    itself; nested C(launch_bridge) under a Cursor IDE agent is SIGKILL'd.
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
      - Optional custom tool. Every execute is returned in
        RV(structured_tool_calls); RV(structured) remains the last execute.
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
      - Seconds to wait for C(cursor-sdk-bridge ready) on stderr when this
        module spawns the vendor node. Ignored when attaching to
        E(CURSOR_SDK_BRIDGE_URL). The SDK default is 30; this module waits
        120 because a nested Cursor-agent session can SIGKILL the child.
        Not a generation or tool-turn budget.
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
  description: >-
    Arguments of the last O(structured_tool) execute (back-compat). This is
    last-call, not the named subagent. Prefer RV(structured_tool_calls).
  type: dict
  returned: when structured_tool was set and the model called it
structured_tool_calls:
  description: >-
    Every O(structured_tool) execute in order. caller is parent when the
    execute tool_call_id appears on the parent run event stream as a
    parent-agent mcp tool_call, otherwise nested. Nested agent_id is
    null on the execute record; CallCustomTool.agent_id on the wire is
    the tool owner, not the caller. Stream events that leak a nested mcp
    call carry the child agent id and stay nested. args is the tool
    argument object. Do not treat a field inside args as caller identity.
  type: list
  returned: when structured_tool was set
  elements: dict
  contains:
    name:
      description: Custom tool name.
      type: str
    args:
      description: Tool arguments for this execute.
      type: dict
    tool_call_id:
      description: Host callback toolCallId, used to join the parent stream.
      type: str
    agent_id:
      description: Parent agent id when caller is parent; null when nested.
      type: str
    caller:
      description: parent or nested.
      type: str
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

from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
    DEFAULT_BRIDGE_TIMEOUT,
    PROVIDER_ARGSPEC,
    AttachedBridgeIncomplete,
    annotate_structured_calls,
    flatten_run,
    install_subagent_custom_tool_fallback,
    parent_stream_tool_call_ids,
    reregister_live_agent_custom_tools,
    resolve_attached_bridge,
    resolve_tools,
    result_after_parent_stream,
)
from ansible_collections.aknochow.cursor.plugins.module_utils.model_params import (
    OPERATOR_EFFORT_VALUES,
    UnsupportedEffortValue,
    resolve_effort_param,
)


def _structured_capture(structured_tool):
    """Build a CustomTool whose execute records arguments for RV(structured).

    DOCUMENTATION already marks name/description/input_schema required.
    argument_spec repeats that for live AnsibleModule validation; this
    helper still fail_jsons (via ValueError) because unit tests mock
    AnsibleModule and skip spec checks. Never KeyError on a partial dict.
    """
    from cursor_sdk import CustomTool

    if not isinstance(structured_tool, dict):
        raise ValueError("structured_tool must be a dict with name, description, and input_schema")

    missing = []
    name = structured_tool.get("name")
    description = structured_tool.get("description")
    input_schema = structured_tool.get("input_schema")
    if not isinstance(name, str) or not name.strip():
        missing.append("name")
    if not isinstance(description, str) or not description.strip():
        missing.append("description")
    if not isinstance(input_schema, dict):
        missing.append("input_schema")
    if missing:
        raise ValueError(
            "structured_tool is missing required option(s): " + ", ".join(missing)
        )

    captured = []

    def execute(args, context):
        captured.append(
            {
                "args": dict(args),
                "tool_call_id": getattr(context, "tool_call_id", None),
            }
        )
        return "recorded"

    tool = CustomTool(
        execute=execute,
        description=description,
        input_schema=input_schema,
    )
    return name, tool, captured


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
        if structured_tool is not None:
            name, tool, captured = _structured_capture(structured_tool)
            custom_tools = {name: tool}
        tools = resolve_tools(params.get("tools"), structured_tool)
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


def _run_agent(
    Agent: Any,
    options: Any,
    prompt: str,
    client: Any,
    module: AnsibleModule,
) -> tuple[Any, set[str], str | None]:
    """create + send + drain parent events + terminal result. Never Agent.prompt."""
    agent = Agent.create(options, client=client)
    live_id = getattr(agent, "agent_id", None)
    local = getattr(options, "local", None)
    custom_tools = getattr(local, "custom_tools", None) if local is not None else None
    reregister_live_agent_custom_tools(client, live_id, custom_tools)
    install_subagent_custom_tool_fallback(client)
    try:
        run = agent.send(prompt)
        parent_ids = parent_stream_tool_call_ids(run, parent_agent_id=live_id)
        result = result_after_parent_stream(run)
        return result, parent_ids, live_id
    finally:
        closer = getattr(agent, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception as close_err:  # noqa: BLE001 — never mask the run result
                module.warn(
                    f"Cursor agent.close() failed (agent_id={getattr(agent, 'agent_id', None)}): {close_err}"
                )


def _structured_return(captured, tool_name, parent_agent_id, parent_stream_ids):
    calls = annotate_structured_calls(
        captured,
        tool_name=tool_name,
        parent_agent_id=parent_agent_id,
        parent_stream_call_ids=parent_stream_ids,
    )
    last = captured[-1]["args"] if captured else None
    return last, calls


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
    try:
        attached = resolve_attached_bridge()
    except AttachedBridgeIncomplete as exc:
        module.fail_json(msg=str(exc))
        return

    client = None
    try:
        if attached:
            # SDK attach path: sidecar started outside cursor-agent.
            # Client.connect() does not pass allow_api_key_env_fallback.
            url, token = attached
            client = Client(
                base_url=url,
                auth_token=token,
                allow_api_key_env_fallback=True,
            )
        else:
            # Own the bridge: workspace is the caller cwd, not
            # ansible-playbook's process cwd. close() reaps the vendor
            # node on both success and start failure.
            client = Client.launch_bridge(
                workspace=module.params["cwd"],
                timeout=module.params.get("bridge_timeout") or DEFAULT_BRIDGE_TIMEOUT,
                allow_api_key_env_fallback=True,
            )
        result, parent_stream_ids, created_agent_id = _run_agent(
            Agent, options, module.params["prompt"], client, module
        )
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

    tool_name = None
    st = module.params.get("structured_tool")
    if isinstance(st, dict):
        tool_name = st.get("name")
    parent_agent_id = created_agent_id or getattr(result, "agent_id", None)
    structured, structured_calls = _structured_return(
        captured, tool_name or "structured_tool", parent_agent_id, parent_stream_ids
    )
    extra = {}
    if tool_name:
        extra["structured_tool_calls"] = structured_calls

    status = getattr(result, "status", None)
    status_s = status if isinstance(status, str) else str(status)
    nested_calls = [
        call
        for call in structured_calls
        if isinstance(call, dict) and call.get("caller") == "nested"
    ]
    if status_s.split(".")[-1] == "error":
        # Nested execute already happened. Parent status=error after that is
        # the WaitLiveRun-after-drain flake, not a missing lens. Returning
        # the payload lets the caller bind; fail_json here used to throw it
        # away (playbook rescue saw only the msg).
        if nested_calls:
            module.exit_json(
                changed=False,
                **flatten_run(
                    result,
                    structured=structured,
                    structured_tool_calls=extra.get("structured_tool_calls"),
                ),
                **_effort_return(effort_param),
            )
            return
        module.fail_json(
            msg=f"Cursor run finished with status error (run_id={getattr(result, 'id', None)})",
            **flatten_run(
                result, structured=structured, structured_tool_calls=extra.get("structured_tool_calls")
            ),
            **_effort_return(effort_param),
        )
        return

    module.exit_json(
        changed=False,
        **flatten_run(
            result, structured=structured, structured_tool_calls=extra.get("structured_tool_calls")
        ),
        **_effort_return(effort_param),
    )


if __name__ == "__main__":
    main()
