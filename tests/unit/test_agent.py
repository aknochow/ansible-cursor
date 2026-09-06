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

    def test_explicit_tools_kept(self):
        assert resolve_tools(["read", "mcp"], {"name": "report"}) == ["read", "mcp"]


class TestMain:
    def _install(self, monkeypatch, params, prompt_return, *, sdk_error=None, missing_sdk=False):
        from ansible_collections.aknochow.cursor.plugins.modules import agent as agent_module

        fake_module = MagicMock()
        fake_module.params = params
        monkeypatch.setattr(agent_module, "AnsibleModule", lambda **kwargs: fake_module)

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
        mock_sdk.AgentOptions = lambda **kwargs: SimpleNamespace(**kwargs)
        mock_sdk.LocalAgentOptions = lambda **kwargs: SimpleNamespace(**kwargs)
        mock_sdk.ModelSelection = lambda **kwargs: SimpleNamespace(**kwargs)
        mock_sdk.ModelParameterValue = lambda **kwargs: SimpleNamespace(**kwargs)
        mock_sdk.AgentDefinition = lambda **kwargs: SimpleNamespace(**kwargs)

        def fake_prompt(prompt, options):
            if sdk_error:
                raise sdk_error
            structured = params.get("structured_tool")
            if structured and getattr(options, "local", None) and getattr(options.local, "custom_tools", None):
                tool = next(iter(options.local.custom_tools.values()))
                tool.execute({"animal": "cat", "legs": 4}, SimpleNamespace(tool_call_id="t1"))
            return prompt_return

        mock_sdk.Agent.prompt = fake_prompt

        import sys

        monkeypatch.setitem(sys.modules, "cursor_sdk", mock_sdk)
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
