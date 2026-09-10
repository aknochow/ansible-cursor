#!/usr/bin/python
# Copyright: (c) 2026, Adam Knochowski (@aknochow)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
---
module: bridge
short_description: Daemonize or reap a cursor-sdk-bridge sidecar
description:
  - C(state=present) double-forks the vendored C(cursor-sdk-bridge) with
    C(setsid) so the vendor node is not a child of ansible-playbook
    (expect ppid 1). Nested C(Client.launch_bridge) under a Cursor IDE
    agent is SIGKILL'd (137); this sidecar is the playbook-owned attach
    target for that case.
  - Waits for C(cursor-sdk-bridge ready) on stderr, then writes URL,
    token, and pid under O(rundir) (mode 0600 files, 0700 directory).
  - C(state=absent) kills the pid from the pidfile and unlinks the token
    file. Idempotent if already gone.
  - Never returns the URL or token. Never use C(nohup) or Ansible
    C(async)/C(poll=0) for this process; those stay in the agent tree.
  - After C(present), point C(aknochow.cursor.agent) at the sidecar via
    E(CURSOR_SDK_BRIDGE_URL) / E(CURSOR_SDK_BRIDGE_TOKEN) or the file-path
    variants E(CURSOR_SDK_BRIDGE_URL_FILE) / E(CURSOR_SDK_BRIDGE_TOKEN_FILE)
    (paths only; the agent reads the files). C(aknochow.cursor.agent) still
    passes its own C(cwd) as C(LocalAgentOptions); the sidecar workspace
    is a dedicated directory under O(rundir) unless O(workspace) is set.
version_added: "0.1.0"
author:
  - Adam Knochowski (@aknochow)
options:
  state:
    description:
      - C(present) starts (or reuses) the sidecar. C(absent) reaps it.
    type: str
    choices: [present, absent]
    default: present
  rundir:
    description:
      - Directory for pid, URL, and token files. Created mode 0700.
      - Default C(~/.cache/ansible-cursor-sidecar/).
    type: path
  workspace:
    description:
      - C(--workspace) passed to the sidecar. Default is a dedicated
        directory under O(rundir). Not a substitute for
        C(aknochow.cursor.agent)'s C(cwd).
    type: path
  timeout:
    description:
      - Seconds to wait for C(cursor-sdk-bridge ready). Discovery only,
        not a generation budget.
    type: float
    default: 120
  command:
    description:
      - Absolute path to a bridge launcher. Default is the SDK-vendored
        binary (or E(CURSOR_SDK_BRIDGE_BIN)). Intended for tests.
    type: path
"""

EXAMPLES = r"""
- name: Start a playbook-owned sidecar (not a child of ansible-playbook)
  aknochow.cursor.bridge:
    state: present
  register: sidecar

- name: Attach later agent tasks via file paths (never set_fact the token)
  ansible.builtin.debug:
    msg: "sidecar pid {{ sidecar.pid }}"

- name: Reap the sidecar
  aknochow.cursor.bridge:
    state: absent
"""

RETURN = r"""
state:
  description: C(present) or C(absent) after the call.
  type: str
  returned: always
pid:
  description: Sidecar process id from the pidfile.
  type: int
  returned: when state is present
ppid:
  description: Sidecar parent pid (1 after a successful detach).
  type: int
  returned: when state is present
rundir:
  description: Directory holding pid/url/token files.
  type: str
  returned: when state is present
url_file:
  description: Path to the URL file. Contents are never returned.
  type: str
  returned: when state is present
token_file:
  description: Path to the token file. Contents are never returned.
  type: str
  returned: when state is present
workspace:
  description: Workspace directory passed to the sidecar.
  type: str
  returned: when state is present
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.aknochow.cursor.plugins.module_utils.bridge_sidecar import (
    SidecarError,
    default_rundir,
    start_sidecar,
    stop_sidecar,
)
from ansible_collections.aknochow.cursor.plugins.module_utils.cursor_client import (
    DEFAULT_BRIDGE_TIMEOUT,
)


def _public_result(result):
    """Drop anything that could be a secret if a helper regresses."""
    allowed = {
        "changed",
        "state",
        "pid",
        "ppid",
        "rundir",
        "url_file",
        "token_file",
        "workspace",
    }
    return {key: value for key, value in result.items() if key in allowed}


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type="str", choices=["present", "absent"], default="present"),
            rundir=dict(type="path"),
            workspace=dict(type="path"),
            timeout=dict(type="float", default=DEFAULT_BRIDGE_TIMEOUT),
            command=dict(type="path"),
        ),
        supports_check_mode=False,
    )
    rundir = module.params.get("rundir") or str(default_rundir())
    try:
        if module.params["state"] == "absent":
            result = stop_sidecar(rundir=rundir)
        else:
            result = start_sidecar(
                rundir=rundir,
                workspace=module.params.get("workspace"),
                timeout=module.params.get("timeout") or DEFAULT_BRIDGE_TIMEOUT,
                command=module.params.get("command"),
            )
    except SidecarError as err:
        module.fail_json(msg=str(err))
        return
    except Exception:  # noqa: BLE001 — surface unexpected errors without payload dumps
        module.fail_json(msg="cursor-sdk-bridge sidecar failed")
        return

    module.exit_json(**_public_result(result))


if __name__ == "__main__":
    main()
