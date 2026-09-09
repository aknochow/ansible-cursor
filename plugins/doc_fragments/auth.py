# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


class ModuleDocFragment:
    DOCUMENTATION = r"""
options:
  api_key:
    description:
      - Cursor user or service-account API key.
      - If the value is not specified, the value of the E(CURSOR_API_KEY) environment variable will be used.
      - Never logged.
    type: str
  cwd:
    description:
      - Working directory for a local agent. Always set explicitly; the SDK
        otherwise silently creates a local agent against the process cwd.
    type: path
    required: true
"""
