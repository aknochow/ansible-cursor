# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
    PROVIDER_ARGSPEC,
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
