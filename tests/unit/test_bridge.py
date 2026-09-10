# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from unittest.mock import MagicMock

from ansible_collections.aknochow.cursor.plugins.modules import bridge as bridge_module


class TestBridgeModule:
    def _install(self, monkeypatch, params, sidecar_result=None, sidecar_error=None):
        fake_module = MagicMock()
        fake_module.params = params
        monkeypatch.setattr(bridge_module, "AnsibleModule", lambda **kwargs: fake_module)

        if sidecar_error is not None:

            def _raise_sidecar_error(**kwargs):
                raise sidecar_error

            monkeypatch.setattr(bridge_module, "start_sidecar", _raise_sidecar_error)
            monkeypatch.setattr(bridge_module, "stop_sidecar", _raise_sidecar_error)
        else:
            monkeypatch.setattr(bridge_module, "start_sidecar", lambda **kwargs: sidecar_result)
            monkeypatch.setattr(bridge_module, "stop_sidecar", lambda **kwargs: sidecar_result)
        return fake_module

    def test_present_strips_secrets_from_exit_json(self, monkeypatch):
        params = dict(state="present", rundir="/tmp/rundir", workspace=None, timeout=120, command=None)
        fake_module = self._install(
            monkeypatch,
            params,
            sidecar_result={
                "changed": True,
                "state": "present",
                "pid": 42,
                "ppid": 1,
                "rundir": "/tmp/rundir",
                "url_file": "/tmp/rundir/url",
                "token_file": "/tmp/rundir/token",
                "workspace": "/tmp/rundir/workspace",
                "url": "http://127.0.0.1:9",
                "auth_token": "super-secret-bridge-token",
            },
        )
        bridge_module.main()
        fake_module.exit_json.assert_called_once()
        kwargs = fake_module.exit_json.call_args.kwargs
        assert kwargs["pid"] == 42
        assert "url" not in kwargs
        assert "auth_token" not in kwargs
        assert "super-secret-bridge-token" not in str(kwargs)
        assert "127.0.0.1" not in str(kwargs)

    def test_absent_idempotent_result(self, monkeypatch):
        params = dict(state="absent", rundir="/tmp/rundir", workspace=None, timeout=120, command=None)
        fake_module = self._install(
            monkeypatch,
            params,
            sidecar_result={"changed": False, "state": "absent"},
        )
        bridge_module.main()
        fake_module.exit_json.assert_called_once()
        assert fake_module.exit_json.call_args.kwargs["state"] == "absent"
        assert fake_module.exit_json.call_args.kwargs["changed"] is False

    def test_fail_json_has_no_secrets(self, monkeypatch):
        from ansible_collections.aknochow.cursor.plugins.module_utils.bridge_sidecar import SidecarError

        params = dict(state="present", rundir="/tmp/rundir", workspace=None, timeout=120, command=None)
        fake_module = self._install(
            monkeypatch,
            params,
            sidecar_error=SidecarError("Bridge emitted invalid discovery JSON"),
        )
        bridge_module.main()
        fake_module.fail_json.assert_called_once()
        msg = fake_module.fail_json.call_args.kwargs["msg"]
        assert "invalid discovery JSON" in msg
        assert "super-secret" not in msg
