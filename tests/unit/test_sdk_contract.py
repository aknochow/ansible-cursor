# SPDX-License-Identifier: Apache-2.0

"""Lock the cursor-sdk surface aknochow.cursor actually calls.

Imports the installed SDK. A lockfile bump that removes Agent.create,
Client.launch_bridge(workspace=...), or CustomTool fails here.
"""

from __future__ import annotations

import inspect
from importlib.metadata import version

from packaging.version import Version


def test_installed_sdk_is_the_locked_generation():
    installed = Version(version("cursor-sdk"))
    assert installed >= Version("1.0.35")
    assert installed < Version("2.0.0")


def test_agent_module_symbols_still_import():
    from cursor_sdk import (
        Agent,
        AgentDefinition,
        AgentOptions,
        Client,
        CursorAgentError,
        CustomTool,
        LocalAgentOptions,
        ModelParameterValue,
        ModelSelection,
    )
    from cursor_sdk._vendor import resolve_bridge_path

    assert callable(resolve_bridge_path)
    assert issubclass(CursorAgentError, Exception)
    assert callable(Agent.create)
    assert callable(Agent.send)
    create_params = inspect.signature(Agent.create).parameters
    assert create_params["client"].kind is inspect.Parameter.KEYWORD_ONLY
    launch_params = inspect.signature(Client.launch_bridge).parameters
    assert "workspace" in launch_params
    assert launch_params["workspace"].kind is inspect.Parameter.KEYWORD_ONLY
    tool_params = inspect.signature(CustomTool).parameters
    assert "execute" in tool_params
    assert "description" in tool_params
    assert "input_schema" in tool_params
    assert "cwd" in inspect.signature(LocalAgentOptions).parameters
    assert "id" in inspect.signature(ModelSelection).parameters
    assert "value" in inspect.signature(ModelParameterValue).parameters
    assert AgentOptions is not None
    assert AgentDefinition is not None
