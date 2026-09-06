# aknochow.cursor

Ansible collection for running [Cursor](https://cursor.com) agents via the
official [cursor-sdk](https://pypi.org/project/cursor-sdk/) Python package.
Same shape as the sibling collections (`aknochow.claude`, `aknochow.gemini`,
`aknochow.openai`): deterministic modules for `register` / `set_fact` /
`when` / loops.

This is **not** an OpenAI-compatible chat-completions client. Cursor Pro
includes API access (`CURSOR_API_KEY`) for the Agent SDK, the `agent` CLI,
and Cloud Agents. Pointing `aknochow.openai.chat` at `api.cursor.com` does
not work.

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

See `ansible-ai-handoffs/cursor-grok-capability-spike-2026-09-06.md`.

- **No generation-time JSON Schema.** `structured_tool` is a custom tool the
  model *may* call. Assert on `structured` in the playbook, the same way
  `aknochow.claude.agent` asserts when structured output is declined.
- **`tools=[]` hides custom tools.** `structured_tool` therefore defaults
  `tools` to `[mcp]`. Passing `tools: []` with `structured_tool` fails
  loudly.
- **No parent-level trusted-instruction field.** Subagent `agents.*.prompt`
  is the documented channel for that. The parent user message is not a
  substitute.
- **Harness tax.** A one-word ping was ~3.3k input tokens with `tools=[]`,
  ~12k with default tools, ~20k via `agent -p`. Not a cheap completion.

## Example

```yaml
- name: Structured classify
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

Model ids come from `Cursor.models.list()` for the key in use. Do not
hardcode unusual ids without checking the catalog. Grok 4.6 is `grok-4.6`
with `effort` one of `low` / `medium` / `high` / `xhigh`.
