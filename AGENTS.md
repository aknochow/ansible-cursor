# ansible-cursor: Project Context

Ansible collection wrapping the official Cursor Python SDK (`cursor-sdk`).
One module today: `aknochow.cursor.agent` → `Agent.prompt` (local).

## Do not

- Point this at OpenAI `chat.completions` or reuse `aknochow.openai`.
- Default a model id in `defaults/` or the module. Callers pass `model`.
- Print `CURSOR_API_KEY` or pass it on the CLI in a way that lands in logs
  (`api_key` is `no_log`).
- Treat `structured` as generation-constrained JSON Schema. It is the last
  custom-tool argument blob, or it is absent.

## Tests

```bash
uv run pytest
```

No live key in CI. Mock `cursor_sdk`.
