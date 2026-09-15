# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
    PROVIDER_ARGSPEC,
    AttachedBridgeIncomplete,
    resolve_attached_bridge,
)


class TestProviderArgspec:
    def test_api_key_is_no_log(self):
        assert PROVIDER_ARGSPEC["api_key"]["no_log"] is True

    def test_api_key_falls_back_to_env_var_name(self):
        _fn, names = PROVIDER_ARGSPEC["api_key"]["fallback"]
        assert names == ["CURSOR_API_KEY"]

    def test_cwd_is_required(self):
        assert PROVIDER_ARGSPEC["cwd"]["required"] is True
        assert PROVIDER_ARGSPEC["cwd"]["type"] == "path"


class TestResolveAttachedBridge:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_URL", raising=False)
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_TOKEN", raising=False)
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_AUTH_TOKEN", raising=False)
        assert resolve_attached_bridge() is None

    def test_both_set(self, monkeypatch):
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL", "http://127.0.0.1:9")
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_TOKEN", "sidecar-token")
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_AUTH_TOKEN", raising=False)
        assert resolve_attached_bridge() == ("http://127.0.0.1:9", "sidecar-token")

    def test_auth_token_alias(self, monkeypatch):
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL", "http://127.0.0.1:9")
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_TOKEN", raising=False)
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_AUTH_TOKEN", "alias-token")
        assert resolve_attached_bridge() == ("http://127.0.0.1:9", "alias-token")

    def test_url_without_token_raises_without_values(self, monkeypatch):
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL", "http://127.0.0.1:9")
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_TOKEN", raising=False)
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_AUTH_TOKEN", raising=False)
        with pytest.raises(AttachedBridgeIncomplete, match="must be set together") as exc:
            resolve_attached_bridge()
        assert "127.0.0.1" not in str(exc.value)

    def test_token_without_url_raises(self, monkeypatch):
        monkeypatch.delenv("CURSOR_SDK_BRIDGE_URL", raising=False)
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_TOKEN", "sidecar-token")
        with pytest.raises(AttachedBridgeIncomplete, match="must be set together"):
            resolve_attached_bridge()

    def test_file_paths(self, monkeypatch, tmp_path):
        url_file = tmp_path / "url"
        token_file = tmp_path / "token"
        url_file.write_text("http://127.0.0.1:9\n")
        token_file.write_text("file-token\n")
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL_FILE", str(url_file))
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_TOKEN_FILE", str(token_file))
        assert resolve_attached_bridge() == ("http://127.0.0.1:9", "file-token")

    def test_file_url_without_token_raises_without_values(self, monkeypatch, tmp_path):
        url_file = tmp_path / "url"
        url_file.write_text("http://127.0.0.1:9\n")
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_URL_FILE", str(url_file))
        with pytest.raises(AttachedBridgeIncomplete, match="must be set together") as exc:
            resolve_attached_bridge()
        assert "127.0.0.1" not in str(exc.value)
        assert "file-token" not in str(exc.value)


class TestAnnotateStructuredCalls:
    def test_parent_then_nested_keeps_both(self):
        from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
            annotate_structured_calls,
        )

        captured = [
            {"args": {"from": "parent"}, "tool_call_id": "parent-call"},
            {"args": {"from": "lens"}, "tool_call_id": "nested-call"},
        ]
        calls = annotate_structured_calls(
            captured,
            tool_name="report_findings",
            parent_agent_id="parent-1",
            parent_stream_call_ids={"parent-call", "task-1"},
        )
        assert [c["caller"] for c in calls] == ["parent", "nested"]
        assert calls[0]["agent_id"] == "parent-1"
        assert calls[1]["agent_id"] is None
        assert calls[0]["args"]["from"] == "parent"
        assert calls[1]["args"]["from"] == "lens"

    def test_parent_stream_ids_from_events(self):
        from types import SimpleNamespace

        from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
            parent_stream_tool_call_ids,
        )

        class FakeRun:
            def events(self):
                yield SimpleNamespace(
                    sdk_message=SimpleNamespace(type="tool_call", call_id="a", name="mcp")
                )
                yield SimpleNamespace(
                    sdk_message=SimpleNamespace(type="tool_call", call_id="a", name="mcp")
                )
                yield SimpleNamespace(
                    sdk_message=SimpleNamespace(type="assistant", call_id=None)
                )
                yield SimpleNamespace(kind="done", sdk_message=None)

        assert parent_stream_tool_call_ids(FakeRun()) == {"a"}
