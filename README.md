# aknochow.cursor

Ansible collection for running [Cursor](https://cursor.com) agents via the
official [cursor-sdk](https://pypi.org/project/cursor-sdk/) Python package.
Same shape as the sibling collections (`aknochow.claude`, `aknochow.gemini`,
`aknochow.openai`): deterministic modules for `register` / `set_fact` /
`when` / loops.

This is **not** an OpenAI-compatible chat-completions client. Cursor Pro
includes API access (`CURSOR_API_KEY`) for the Agent SDK, the `agent` CLI,
and Cloud Agents. Pointing `aknochow.openai.chat` at `api.cursor.com` does
not work. First-party ids (Grok, Composer) draw the Cursor Models pool;
third-party ids (GPT, Claude, Gemini, …) draw Other Models (the dashboard
**API** line).

## Modules

| Module | Purpose |
|---|---|
| `agent` | One-shot `Agent.prompt` (local runtime). Optional `structured_tool` captures custom-tool arguments as `structured`. |

Cloud agents and a CLI (`agent -p`) wrapper are deliberately not in 0.1.0.

## Requirements

```
pip install 'cursor-sdk>=1.0.31'
export CURSOR_API_KEY=...   # Dashboard → Integrations; never print this
```

## Known limits (measured 2026-09-06)

Measured against a private 2026-09-06 capability spike; notes are not in this repository.

- **No generation-time JSON Schema.** `structured_tool` is a custom tool the
  model *may* call. Assert on `structured` in the playbook, the same way
  `aknochow.claude.agent` asserts when structured output is declined.
- **A tools list without `mcp` hides custom tools.** `structured_tool`
  therefore defaults `tools` to `[mcp]`. Passing `tools: []` or
  `tools: [read]` (any explicit list that omits `mcp`) with
  `structured_tool` fails loudly.
- **No parent-level trusted-instruction field.** Subagent `agents.*.prompt`
  is the documented channel for that. The parent user message is not a
  substitute.
- **Harness tax.** A one-word ping was ~3.3k input tokens with `tools=[]`,
  ~12k with default tools, ~20k via `agent -p`. Not a cheap completion.
- **Local bridge bring-up.** By default the module launches
  `cursor-sdk-bridge` (`Client.launch_bridge(workspace=cwd)`, default
  `bridge_timeout` 120s) and closes it after the run. Nested Cursor-agent
  sessions SIGKILL that vendor `node` (`137`). The SDK attach path is
  `CURSOR_SDK_BRIDGE_URL` plus `CURSOR_SDK_BRIDGE_TOKEN` (or
  `CURSOR_SDK_BRIDGE_AUTH_TOKEN`): start one sidecar *outside* the IDE
  agent (tmux, launchd, AAP EE), then the module uses `Client(...)` and
  does not spawn. Never print the token. If spawn discovery times out,
  reap leftover `cursor-sdk-bridge` processes before retrying.

## Examples

Grok 4.6 draws the Cursor Models pool (dashboard **Auto** / Included). Third-party ids such as GPT draw Other Models (dashboard **API**). `effort` is the same operator knob either way; the module maps it onto the catalog param that id actually exposes.

```yaml
- name: Structured classify (Cursor Models — Grok)
  aknochow.cursor.agent:
    prompt: A domestic housecat. Call report_animal.
    model: grok-4.6
    effort: high
    cwd: "{{ playbook_dir }}"
    structured_tool:
      name: report_animal
      description: Submit animal and leg count.
      input_schema:
        type: object
        properties:
          animal: {type: string}
          legs: {type: integer}
        required: [animal, legs]
  register: result

- name: Require the tool call
  ansible.builtin.assert:
    that:
      - result.structured is defined
      - result.structured.legs == 4
```

```yaml
- name: One-shot ping (Other Models — GPT-5.6 Luna)
  aknochow.cursor.agent:
    prompt: Reply with the single word pong.
    model: gpt-5.6-luna
    effort: high
    cwd: "{{ playbook_dir }}"
    tools: []
  register: ping

- name: Confirm high reasoning was sent
  ansible.builtin.assert:
    that:
      - ping.text is search("pong", ignorecase=true)
      - ping.effort_param.id == "reasoning"
      - ping.effort_param.value == "high"
```

`api_key` may be omitted when `CURSOR_API_KEY` is in the process environment. There is no collection default model; pass an id from `Cursor.models.list()` for the key in use.

`effort` is an operator knob, not a raw SDK field. The module maps it onto
the catalog param that model exposes (`effort`, `reasoning`, or
`reasoning_effort`) and **omits it** when the model has no such param.
Unsupported values fail the task instead of being forwarded. It never
sends `thinking`, `fast`, `context`, or `enable_thinking`.

| Example id | `effort: high` becomes |
|---|---|
| `grok-4.6` | `effort=high` (also allows `xhigh`) |
| `grok-4.5` | `effort=high` (`xhigh` is rejected) |
| `gpt-5.6-luna` | `reasoning=high` |
| `gemini-3.8-flash` | `reasoning_effort=high` |
| `composer-2.5` | omitted |

The matrix lives in `plugins/module_utils/model_params.py` (snapshot of
`Cursor.models.list()` on 2026-09-09). Token, timeout, and retry budgets
stay out of this module; plaibook owns those per pass.
