# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
    flatten_run,
    normalize_usage,
    resolve_tools,
)


class TestNormalizeUsage:
    def test_none_is_zeros(self):
        assert normalize_usage(None) == dict(
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            thinking_tokens=0,
            total_tokens=0,
        )

    def test_object_fields(self):
        usage = SimpleNamespace(
            input_tokens=3348,
            output_tokens=34,
            cache_read_tokens=0,
            cache_write_tokens=0,
            total_tokens=3382,
            reasoning_tokens=12,
        )
        got = normalize_usage(usage)
        assert got["input_tokens"] == 3348
        assert got["output_tokens"] == 34
        assert got["thinking_tokens"] == 12
        assert got["total_tokens"] == 3382

    def test_dict_and_missing_total(self):
        got = normalize_usage({"input_tokens": 10, "output_tokens": 5})
        assert got["total_tokens"] == 15
        assert got["thinking_tokens"] == 0


class TestFlattenRun:
    def test_text_and_ids(self):
        result = SimpleNamespace(
            result="pong",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="agent-1",
            id="run-1",
            duration_ms=3406,
            usage=SimpleNamespace(
                input_tokens=3348,
                output_tokens=34,
                cache_read_tokens=0,
                cache_write_tokens=0,
                total_tokens=3382,
                reasoning_tokens=None,
            ),
        )
        out = flatten_run(result, structured={"animal": "cat", "legs": 4})
        assert out["text"] == "pong"
        assert out["status"] == "finished"
        assert out["resolved_model"] == "grok-4.6"
        assert out["agent_id"] == "agent-1"
        assert out["run_id"] == "run-1"
        assert out["structured"]["legs"] == 4
        assert out["usage_normalized"]["input_tokens"] == 3348

    def test_structured_omitted_when_none(self):
        result = SimpleNamespace(
            result="",
            status="finished",
            model=None,
            agent_id="a",
            id="r",
            duration_ms=1,
            usage=None,
        )
        out = flatten_run(result)
        assert "structured" not in out


class TestResolveTools:
    def test_structured_defaults_to_mcp(self):
        assert resolve_tools(None, {"name": "report"}) == ["mcp"]

    def test_empty_tools_without_structured_ok(self):
        assert resolve_tools([], None) == []

    def test_empty_tools_with_structured_errors(self):
        with pytest.raises(ValueError, match="mcp"):
            resolve_tools([], {"name": "report"})

    def test_tools_without_mcp_with_structured_errors(self):
        with pytest.raises(ValueError, match="mcp"):
            resolve_tools(["read"], {"name": "report"})

    def test_explicit_tools_kept(self):
        assert resolve_tools(["read", "mcp"], {"name": "report"}) == ["read", "mcp"]


class TestMain:
    def _install(self, monkeypatch, params, prompt_return, *, sdk_error=None, missing_sdk=False):
        from ansible_collections.aknochow.cursor.plugins.modules import agent as agent_module

        fake_module = MagicMock()
        fake_module.params = params
        monkeypatch.setattr(agent_module, "AnsibleModule", lambda **kwargs: fake_module)
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_URL", raising=False)
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_TOKEN", raising=False)
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_AUTH_TOKEN", raising=False)

        if missing_sdk:
            import sys

            monkeypatch.setitem(sys.modules, "cursor_sdk", None)
            return agent_module, fake_module

        mock_sdk = MagicMock()
        mock_sdk.CursorAgentError = type("CursorAgentError", (Exception,), {})

        class FakeCustomTool:
            def __init__(self, execute, description=None, input_schema=None):
                self.execute = execute
                self.description = description
                self.input_schema = input_schema

        mock_sdk.CustomTool = FakeCustomTool
        mock_sdk.AgentOptions = SimpleNamespace
        mock_sdk.LocalAgentOptions = SimpleNamespace
        mock_sdk.ModelSelection = SimpleNamespace
        mock_sdk.ModelParameterValue = SimpleNamespace
        mock_sdk.AgentDefinition = SimpleNamespace

        prompt_options = []

        fake_client = MagicMock()
        mock_sdk.Client.launch_bridge.return_value = fake_client
        fake_module.stream_events = []
        fake_module.execute_calls = [
            ({"animal": "cat", "legs": 4}, SimpleNamespace(tool_call_id="t1")),
        ]

        def fake_create(options, client=None):
            prompt_options.append(options)
            fake_module.prompt_client = client
            fake_agent = MagicMock()
            fake_agent.agent_id = getattr(prompt_return, "agent_id", "agent-1")
            fake_run = MagicMock()

            def events():
                return iter(list(fake_module.stream_events))

            fake_run.events.side_effect = events

            def wait():
                if sdk_error is not None:
                    raise mock_sdk.CursorAgentError(str(sdk_error))
                structured = params.get("structured_tool")
                if structured and getattr(options, "local", None) and getattr(
                    options.local, "custom_tools", None
                ):
                    tool = next(iter(options.local.custom_tools.values()))
                    for args, ctx in fake_module.execute_calls:
                        tool.execute(args, ctx)
                return prompt_return

            fake_run.wait.side_effect = wait
            fake_agent.send.return_value = fake_run
            fake_module.fake_agent = fake_agent
            return fake_agent

        mock_sdk.Agent.create = fake_create

        import sys

        monkeypatch.setitem(sys.modules, "cursor_sdk", mock_sdk)
        fake_module.prompt_options = prompt_options
        fake_module.sdk = mock_sdk
        fake_module.bridge_client = fake_client
        return agent_module, fake_module

    def test_finished_text_only(self, monkeypatch):
        result = SimpleNamespace(
            result="pong",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="agent-1",
            id="run-1",
            duration_ms=10,
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=1,
                cache_read_tokens=0,
                cache_write_tokens=0,
                total_tokens=11,
                reasoning_tokens=None,
            ),
        )
        params = dict(
            prompt="pong please",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=[],
            disallowed_tools=None,
            structured_tool=None,
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        agent_module.main()
        fake_module.exit_json.assert_called_once()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["changed"] is False
        assert kwargs["text"] == "pong"
        assert kwargs["usage_normalized"]["input_tokens"] == 10
        fake_module.fail_json.assert_not_called()
        fake_module.sdk.Client.launch_bridge.assert_called_once()
        launch_kwargs = fake_module.sdk.Client.launch_bridge.call_args.kwargs
        assert launch_kwargs["workspace"] == "/tmp"
        assert launch_kwargs["timeout"] == 120.0
        assert fake_module.prompt_client is fake_module.bridge_client
        fake_module.bridge_client.close.assert_called_once()
        fake_module.sdk.Client.assert_not_called()

    def test_attaches_when_bridge_url_and_token_set(self, monkeypatch):
        result = SimpleNamespace(
            result="pong",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="agent-1",
            id="run-1",
            duration_ms=10,
            usage=None,
        )
        params = dict(
            prompt="pong please",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=[],
            disallowed_tools=None,
            structured_tool=None,
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL", "http://127.0.0.1:9")
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_TOKEN", "sidecar-token")
        attached = MagicMock()
        fake_module.sdk.Client.return_value = attached
        agent_module.main()
        fake_module.sdk.Client.launch_bridge.assert_not_called()
        kwargs = fake_module.sdk.Client.call_args.kwargs
        assert kwargs["base_url"] == "http://127.0.0.1:9"
        assert kwargs["auth_token"] == "sidecar-token"
        assert kwargs["allow_api_key_env_fallback"] is True
        assert fake_module.prompt_client is attached
        attached.close.assert_called_once()
        fake_module.exit_json.assert_called_once()

    def test_attaches_from_token_file_env(self, monkeypatch, tmp_path):
        result = SimpleNamespace(
            result="pong",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="agent-1",
            id="run-1",
            duration_ms=10,
            usage=None,
        )
        params = dict(
            prompt="pong please",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=[],
            disallowed_tools=None,
            structured_tool=None,
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        url_file = tmp_path / "url"
        token_file = tmp_path / "token"
        url_file.write_text("http://127.0.0.1:9\n")
        token_file.write_text("file-token\n")
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL_FILE", str(url_file))
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_TOKEN_FILE", str(token_file))
        attached = MagicMock()
        fake_module.sdk.Client.return_value = attached
        agent_module.main()
        fake_module.sdk.Client.launch_bridge.assert_not_called()
        kwargs = fake_module.sdk.Client.call_args.kwargs
        assert kwargs["base_url"] == "http://127.0.0.1:9"
        assert kwargs["auth_token"] == "file-token"
        assert kwargs["allow_api_key_env_fallback"] is True

    def test_incomplete_attach_env_fails_without_spawning(self, monkeypatch):
        params = dict(
            prompt="x",
            model="grok-4.6",
            cwd="/tmp",
            api_key="k",
            effort=None,
            tools=[],
            disallowed_tools=None,
            structured_tool=None,
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, SimpleNamespace())
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL", "http://127.0.0.1:9")
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_TOKEN", raising=False)
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_AUTH_TOKEN", raising=False)
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        msg = fake_module.fail_json.call_args.kwargs["msg"]
        assert "must be set together" in msg
        assert "127.0.0.1" not in msg
        fake_module.sdk.Client.launch_bridge.assert_not_called()
        fake_module.exit_json.assert_not_called()

    def test_structured_tool_captures_args(self, monkeypatch):
        result = SimpleNamespace(
            result="ok",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="a",
            id="r",
            duration_ms=10,
            usage=None,
        )
        params = dict(
            prompt="a cat",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort="high",
            tools=None,
            disallowed_tools=None,
            structured_tool=dict(
                name="report_animal",
                description="submit",
                input_schema={"type": "object"},
            ),
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        agent_module.main()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["structured"] == {"animal": "cat", "legs": 4}
        assert kwargs["structured_tool_calls"][0]["caller"] == "nested"
        assert kwargs["structured_tool_calls"][0]["args"]["legs"] == 4

    def test_two_executes_parent_then_nested_keeps_both(self, monkeypatch):
        result = SimpleNamespace(
            result="ok",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="parent-1",
            id="r",
            duration_ms=10,
            usage=None,
        )
        params = dict(
            prompt="spawn then report",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=["mcp", "task"],
            disallowed_tools=None,
            structured_tool=dict(
                name="report_findings",
                description="submit",
                input_schema={"type": "object"},
            ),
            agents=dict(security_lens=dict(description="lens", prompt="report")),
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        fake_module.execute_calls = [
            ({"findings": [], "from": "parent"}, SimpleNamespace(tool_call_id="parent-call")),
            ({"findings": [{"file": "x"}], "from": "lens"}, SimpleNamespace(tool_call_id="nested-call")),
        ]
        fake_module.stream_events = [
            SimpleNamespace(
                sdk_message=SimpleNamespace(
                    type="tool_call", name="mcp", call_id="parent-call", status="completed"
                )
            ),
            SimpleNamespace(
                sdk_message=SimpleNamespace(
                    type="tool_call", name="task", call_id="task-1", status="completed"
                )
            ),
        ]
        agent_module.main()
        kwargs = fake_module.exit_json.call_args.kwargs
        calls = kwargs["structured_tool_calls"]
        assert len(calls) == 2
        assert calls[0]["caller"] == "parent"
        assert calls[0]["agent_id"] == "parent-1"
        assert calls[0]["args"]["from"] == "parent"
        assert calls[1]["caller"] == "nested"
        assert calls[1]["agent_id"] is None
        assert calls[1]["args"]["from"] == "lens"
        # last-wins structured must not hide the first execute
        assert kwargs["structured"]["from"] == "lens"
        assert calls[0]["args"]["from"] != kwargs["structured"]["from"] or len(calls) == 2

    def test_parent_only_execute_classified_parent(self, monkeypatch):
        result = SimpleNamespace(
            result="ok",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="parent-1",
            id="r",
            duration_ms=10,
            usage=None,
        )
        params = dict(
            prompt="report yourself",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=["mcp"],
            disallowed_tools=None,
            structured_tool=dict(
                name="report_findings",
                description="submit",
                input_schema={"type": "object"},
            ),
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        fake_module.execute_calls = [
            ({"findings": []}, SimpleNamespace(tool_call_id="parent-call")),
        ]
        fake_module.stream_events = [
            SimpleNamespace(
                sdk_message=SimpleNamespace(
                    type="tool_call", name="mcp", call_id="parent-call", status="completed"
                )
            ),
        ]
        agent_module.main()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["structured_tool_calls"][0]["caller"] == "parent"
        assert kwargs["structured_tool_calls"][0]["agent_id"] == "parent-1"

    def test_tools_empty_with_structured_fails(self, monkeypatch):
        params = dict(
            prompt="x",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=[],
            disallowed_tools=None,
            structured_tool=dict(name="t", description="d", input_schema={}),
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, SimpleNamespace())
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        assert "mcp" in fake_module.fail_json.call_args.kwargs["msg"]
        fake_module.exit_json.assert_not_called()

    def test_tools_read_only_with_structured_fails(self, monkeypatch):
        params = dict(
            prompt="x",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=["read"],
            disallowed_tools=None,
            structured_tool=dict(name="t", description="d", input_schema={}),
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, SimpleNamespace())
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        assert "mcp" in fake_module.fail_json.call_args.kwargs["msg"]
        fake_module.exit_json.assert_not_called()

    def test_missing_sdk(self, monkeypatch):
        params = dict(
            prompt="x",
            model="grok-4.6",
            cwd="/tmp",
            api_key="k",
            effort=None,
            tools=None,
            disallowed_tools=None,
            structured_tool=None,
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, None, missing_sdk=True)
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        assert "cursor-sdk" in fake_module.fail_json.call_args.kwargs["msg"]

    def test_run_status_error(self, monkeypatch):
        result = SimpleNamespace(
            result="",
            status="error",
            model=None,
            agent_id="a",
            id="r",
            duration_ms=1,
            usage=None,
        )
        params = dict(
            prompt="x",
            model="grok-4.6",
            cwd="/tmp",
            api_key="k",
            effort=None,
            tools=[],
            disallowed_tools=None,
            structured_tool=None,
            agents=None,
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        assert "status error" in fake_module.fail_json.call_args.kwargs["msg"]

    def test_run_status_error_with_nested_execute_returns_payload(self, monkeypatch):
        result = SimpleNamespace(
            result="",
            status="error",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="parent-1",
            id="run-err",
            duration_ms=1,
            usage=None,
        )
        params = dict(
            prompt="spawn then report",
            model="grok-4.6",
            cwd="/tmp",
            api_key="k",
            effort=None,
            tools=["mcp", "task"],
            disallowed_tools=None,
            structured_tool=dict(
                name="report_findings",
                description="submit",
                input_schema={"type": "object"},
            ),
            agents=dict(security_lens=dict(description="lens", prompt="report")),
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        fake_module.execute_calls = [
            (
                {"findings": [{"file": "x"}], "prompt_nonce": "n"},
                SimpleNamespace(tool_call_id="nested-call"),
            ),
        ]
        fake_module.stream_events = [
            SimpleNamespace(
                sdk_message=SimpleNamespace(
                    type="tool_call",
                    name="task",
                    call_id="task-1",
                    status="completed",
                    agent_id="parent-1",
                )
            ),
        ]
        agent_module.main()
        fake_module.fail_json.assert_not_called()
        fake_module.exit_json.assert_called_once()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["structured_tool_calls"][0]["caller"] == "nested"
        assert kwargs["structured"]["findings"][0]["file"] == "x"

    def test_nested_mcp_on_parent_stream_stays_nested(self, monkeypatch):
        result = SimpleNamespace(
            result="ok",
            status="finished",
            model=SimpleNamespace(id="grok-4.6"),
            agent_id="parent-1",
            id="r",
            duration_ms=10,
            usage=None,
        )
        params = dict(
            prompt="spawn then report",
            model="grok-4.6",
            cwd="/tmp",
            api_key="k",
            effort=None,
            tools=["mcp", "task"],
            disallowed_tools=None,
            structured_tool=dict(
                name="report_findings",
                description="submit",
                input_schema={"type": "object"},
            ),
            agents=dict(security_lens=dict(description="lens", prompt="report")),
            setting_sources=[],
            mode=None,
        )
        agent_module, fake_module = self._install(monkeypatch, params, result)
        fake_module.execute_calls = [
            ({"findings": [{"file": "x"}], "from": "lens"}, SimpleNamespace(tool_call_id="nested-call")),
        ]
        fake_module.stream_events = [
            SimpleNamespace(
                sdk_message=SimpleNamespace(
                    type="tool_call",
                    name="task",
                    call_id="task-1",
                    status="completed",
                    agent_id="parent-1",
                )
            ),
            SimpleNamespace(
                sdk_message=SimpleNamespace(
                    type="tool_call",
                    name="mcp",
                    call_id="nested-call",
                    status="completed",
                    agent_id="child-9",
                )
            ),
        ]
        agent_module.main()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["structured_tool_calls"][0]["caller"] == "nested"
        assert kwargs["structured_tool_calls"][0]["agent_id"] is None

    def test_empty_structured_tool_fails_without_traceback(self, monkeypatch):
        params = self._base_params(structured_tool={})
        agent_module, fake_module = self._install(monkeypatch, params, SimpleNamespace())
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        msg = fake_module.fail_json.call_args.kwargs["msg"]
        assert "structured_tool" in msg
        assert "name" in msg
        fake_module.exit_json.assert_not_called()

    def test_structured_tool_missing_description_fails_without_traceback(self, monkeypatch):
        params = self._base_params(
            structured_tool=dict(name="report_animal", input_schema={"type": "object"}),
        )
        agent_module, fake_module = self._install(monkeypatch, params, SimpleNamespace())
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        msg = fake_module.fail_json.call_args.kwargs["msg"]
        assert "structured_tool" in msg
        assert "description" in msg
        assert "KeyError" not in msg
        fake_module.exit_json.assert_not_called()

    def _base_params(self, **overrides):
        params = dict(
            prompt="x",
            model="grok-4.6",
            cwd="/tmp",
            api_key="cursor_test",
            effort=None,
            tools=[],
            disallowed_tools=None,
            structured_tool=None,
            agents=None,
            setting_sources=[],
            mode=None,
        )
        params.update(overrides)
        return params

    def _finished(self, model_id="grok-4.6"):
        return SimpleNamespace(
            result="pong",
            status="finished",
            model=SimpleNamespace(id=model_id),
            agent_id="agent-1",
            id="run-1",
            duration_ms=10,
            usage=None,
        )

    def test_luna_high_sends_reasoning(self, monkeypatch):
        params = self._base_params(model="gpt-5.6-luna", effort="high", prompt="pong please")
        agent_module, fake_module = self._install(monkeypatch, params, self._finished("gpt-5.6-luna"))
        agent_module.main()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["effort_param"] == {"id": "reasoning", "value": "high"}
        model = fake_module.prompt_options[0].model
        assert model.id == "gpt-5.6-luna"
        assert model.params[0].id == "reasoning"
        assert model.params[0].value == "high"

    def test_gemini_38_high_sends_reasoning_effort(self, monkeypatch):
        params = self._base_params(model="gemini-3.8-flash", effort="high")
        agent_module, fake_module = self._install(
            monkeypatch, params, self._finished("gemini-3.8-flash")
        )
        agent_module.main()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["effort_param"] == {"id": "reasoning_effort", "value": "high"}
        assert fake_module.prompt_options[0].model.params[0].id == "reasoning_effort"

    def test_composer_high_omits_param(self, monkeypatch):
        params = self._base_params(model="composer-2.5", effort="high")
        agent_module, fake_module = self._install(monkeypatch, params, self._finished("composer-2.5"))
        agent_module.main()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert "effort_param" not in kwargs
        assert fake_module.prompt_options[0].model == "composer-2.5"

    def test_unsupported_value_fails_before_prompt(self, monkeypatch):
        params = self._base_params(model="grok-4.5", effort="xhigh")
        agent_module, fake_module = self._install(monkeypatch, params, self._finished("grok-4.5"))
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        assert "xhigh" in fake_module.fail_json.call_args.kwargs["msg"]
        fake_module.exit_json.assert_not_called()
        assert fake_module.prompt_options == []
        fake_module.sdk.Client.launch_bridge.assert_not_called()

    def test_agent_close_failure_warns_and_still_returns(self, monkeypatch):
        params = self._base_params()
        agent_module, fake_module = self._install(monkeypatch, params, self._finished())
        original_create = fake_module.sdk.Agent.create

        def create_with_failing_close(options, client=None):
            agent = original_create(options, client=client)
            agent.close.side_effect = RuntimeError("close boom")
            return agent

        fake_module.sdk.Agent.create = create_with_failing_close
        agent_module.main()
        fake_module.exit_json.assert_called_once()
        fake_module.fail_json.assert_not_called()
        fake_module.warn.assert_called_once()
        msg = fake_module.warn.call_args.args[0]
        assert "agent.close()" in msg
        assert "agent-1" in msg
        assert "close boom" in msg

    def test_agent_close_failure_does_not_mask_run_error(self, monkeypatch):
        params = self._base_params()
        agent_module, fake_module = self._install(
            monkeypatch, params, self._finished(), sdk_error="Timed out waiting for bridge discovery"
        )
        original_create = fake_module.sdk.Agent.create

        def create_with_failing_close(options, client=None):
            agent = original_create(options, client=client)
            agent.close.side_effect = RuntimeError("close boom")
            return agent

        fake_module.sdk.Agent.create = create_with_failing_close
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        assert "failed to start" in fake_module.fail_json.call_args.kwargs["msg"]
        fake_module.warn.assert_called_once()
        fake_module.exit_json.assert_not_called()

    def test_closes_client_when_prompt_raises(self, monkeypatch):
        params = self._base_params()
        agent_module, fake_module = self._install(
            monkeypatch, params, self._finished(), sdk_error="Timed out waiting for bridge discovery"
        )
        agent_module.main()
        fake_module.fail_json.assert_called_once()
        assert "failed to start" in fake_module.fail_json.call_args.kwargs["msg"]
        fake_module.bridge_client.close.assert_called_once()

    def test_custom_bridge_timeout(self, monkeypatch):
        params = self._base_params(bridge_timeout=45.0, cwd="/var/review")
        agent_module, fake_module = self._install(monkeypatch, params, self._finished())
        agent_module.main()
        kwargs = fake_module.sdk.Client.launch_bridge.call_args.kwargs
        assert kwargs["workspace"] == "/var/review"
        assert kwargs["timeout"] == 45.0
        fake_module.bridge_client.close.assert_called_once()
