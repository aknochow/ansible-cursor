# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from ansible_collections.aknochow.cursor.plugins.module_utils.model_params import (
    PARAM_EFFORT,
    PARAM_REASONING,
    PARAM_REASONING_EFFORT,
    UnsupportedEffortValue,
    capability_for,
    resolve_effort_param,
)


class TestResolveEffortParam:
    def test_unset_omits(self):
        assert resolve_effort_param("grok-4.6", None) is None
        assert resolve_effort_param("grok-4.6", "") is None

    def test_grok_46_sends_effort(self):
        assert resolve_effort_param("grok-4.6", "high") == (PARAM_EFFORT, "high")
        assert resolve_effort_param("grok-4.6", "xhigh") == (PARAM_EFFORT, "xhigh")

    def test_grok_45_rejects_xhigh(self):
        with pytest.raises(UnsupportedEffortValue, match="grok-4.5"):
            resolve_effort_param("grok-4.5", "xhigh")

    def test_grok_cannot_disable_reasoning(self):
        with pytest.raises(UnsupportedEffortValue, match="none"):
            resolve_effort_param("grok-4.6", "none")

    def test_luna_maps_to_reasoning(self):
        assert resolve_effort_param("gpt-5.6-luna", "high") == (PARAM_REASONING, "high")
        assert resolve_effort_param("gpt-5.6-luna", "none") == (PARAM_REASONING, "none")

    def test_gpt55_aliases_xhigh_to_extra_high(self):
        assert resolve_effort_param("gpt-5.5", "xhigh") == (PARAM_REASONING, "extra-high")

    def test_gemini_38_maps_to_reasoning_effort(self):
        assert resolve_effort_param("gemini-3.8-flash", "high") == (
            PARAM_REASONING_EFFORT,
            "high",
        )

    def test_gemini_38_rejects_xhigh(self):
        with pytest.raises(UnsupportedEffortValue, match="reasoning_effort"):
            resolve_effort_param("gemini-3.8-flash", "xhigh")

    @pytest.mark.parametrize(
        "model_id",
        [
            "composer-2.5",
            "composer-2",
            "default",
            "claude-haiku-4-5",
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "gpt-5-mini",
            "gemini-3.1-pro",
            "kimi-k2.7-code",
        ],
    )
    def test_known_models_without_effort_param_omit(self, model_id):
        assert capability_for(model_id) is None
        assert resolve_effort_param(model_id, "high") is None

    def test_kimi_k3_rejects_medium(self):
        with pytest.raises(UnsupportedEffortValue, match="kimi-k3"):
            resolve_effort_param("kimi-k3", "medium")

    def test_glm_52_sends_reasoning(self):
        assert resolve_effort_param("glm-5.2", "high") == (PARAM_REASONING, "high")

    def test_unknown_claude_omits_rather_than_guessing(self):
        assert resolve_effort_param("claude-opus-9", "high") is None

    def test_unknown_gpt_uses_reasoning_intersection(self):
        assert resolve_effort_param("gpt-5.7-preview", "high") == (PARAM_REASONING, "high")

    def test_unknown_grok_uses_effort_intersection(self):
        assert resolve_effort_param("grok-4.7", "high") == (PARAM_EFFORT, "high")
        with pytest.raises(UnsupportedEffortValue):
            resolve_effort_param("grok-4.7", "xhigh")

    def test_never_uses_thinking_or_enable_thinking(self):
        for model_id in ("grok-4.6", "gpt-5.6-luna", "gemini-3.8-flash", "claude-haiku-4-5"):
            cap = capability_for(model_id)
            if cap is None:
                continue
            assert cap.param_id in {PARAM_EFFORT, PARAM_REASONING, PARAM_REASONING_EFFORT}
            assert cap.param_id not in {"thinking", "enable_thinking", "fast", "context"}
