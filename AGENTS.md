# ansible-cursor: Project Context

Ansible collection wrapping the official Cursor Python SDK (`cursor-sdk`).
Two modules: `aknochow.cursor.agent` → `Agent.prompt` (local), and
`aknochow.cursor.bridge` → playbook-owned daemonized `cursor-sdk-bridge`
sidecar (`state: present` / `absent`).

## Do not

- Point this at OpenAI `chat.completions` or reuse `aknochow.openai`.
- Default a model id in `defaults/` or the module. Callers pass `model`.
- Print `CURSOR_API_KEY` or pass it on the CLI in a way that lands in logs
  (`api_key` is `no_log`). Never print a bridge auth token; never `set_fact`
  it; never `pgrep -lf cursor-sdk-bridge` (argv can contain the token).
  Reap via the sidecar pidfile. Test presence/length of secrets, not contents.
- Treat `structured` as generation-constrained JSON Schema. It is the last
  custom-tool argument blob, or it is absent.
- Call `Agent.prompt` on the SDK default client. Always pass an explicit
  `Client`: attach with `CURSOR_SDK_BRIDGE_URL` + token (or the `*_FILE`
  path variants) when a sidecar is already running, otherwise
  `Client.launch_bridge(workspace=cwd)` and `client.close()` in `finally`.
  Nested `launch_bridge` under `cursor-agent` is SIGKILL'd (`137`).
  `aknochow.cursor.bridge` double-forks + `setsid` so the vendor node is
  not a child of ansible-playbook. Do not use `nohup &` or Ansible
  `async` + `poll: 0`. `Client.connect()` does not pass
  `allow_api_key_env_fallback`; construct `Client(...)` with that kwarg.
  `bridge_timeout` is spawn discovery only.
- Let `aknochow.cursor.agent` decide the sidecar workspace for the review
  repo: the agent still passes `cwd` as `LocalAgentOptions`. The sidecar
  `--workspace` is a dedicated rundir (or caller override).

## Effort vs catalog params

`aknochow.cursor.agent`'s `effort` option is capability metadata. Resolve
it through `plugins/module_utils/model_params.py` — do not hardcode
`ModelParameterValue(id="effort")`. Do not send `enable_thinking` (that is
a local/Qwen Chat Completions field, not Cursor). Do not fold output-token
or tool-turn budgets into this module.

## Tests

```bash
uv run pytest
uv run ruff check plugins tests
```

No live key in CI. Mock `cursor_sdk` for agent tests. Sidecar unit tests
use a fake launcher, not a live `CURSOR_API_KEY`.
