# Copyright: (c) 2026, Adam Knochowski (@aknochow)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Controller-side wiring for aknochow.cursor.bridge.

The module daemonizes on localhost. This action plugin then points the
controller process at the sidecar via env vars #7 already honors, using
file paths so a later Ansible fork can re-read the token without it ever
landing in a fact or fail_json.
"""

from __future__ import annotations

import os
from pathlib import Path

from ansible.plugins.action import ActionBase
from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
    BRIDGE_TOKEN_ENVS,
    BRIDGE_TOKEN_FILE_ENV,
    BRIDGE_URL_ENV,
    BRIDGE_URL_FILE_ENV,
)


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = {}
        result = super().run(tmp, task_vars)
        module_result = self._execute_module(
            module_args=dict(self._task.args),
            task_vars=task_vars,
            tmp=tmp,
        )
        result.update(module_result)
        if not module_result.get("failed"):
            self._wire_controller_env(module_result)
        return result

    def _wire_controller_env(self, module_result):
        state = module_result.get("state") or self._task.args.get("state") or "present"
        if state == "absent":
            os.environ.pop(BRIDGE_URL_ENV, None)
            for key in BRIDGE_TOKEN_ENVS:
                os.environ.pop(key, None)
            os.environ.pop(BRIDGE_URL_FILE_ENV, None)
            os.environ.pop(BRIDGE_TOKEN_FILE_ENV, None)
            return
        url_file = module_result.get("url_file")
        token_file = module_result.get("token_file")
        if not url_file or not token_file:
            return
        try:
            url = Path(url_file).read_text(encoding="utf-8").strip()
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return
        if not url or not token:
            return
        os.environ[BRIDGE_URL_ENV] = url
        os.environ[BRIDGE_TOKEN_ENVS[0]] = token
        os.environ[BRIDGE_URL_FILE_ENV] = str(url_file)
        os.environ[BRIDGE_TOKEN_FILE_ENV] = str(token_file)
