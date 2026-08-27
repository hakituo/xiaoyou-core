"""验证 character_daily 模型选择只认 model_routing。"""

from unittest.mock import patch

from config.character_daily_config import load_character_daily_config


def test_character_daily_models_only_follow_model_routing():
    app_config = {
        "character_daily": {
            "llm_plan": {
                "enabled": True,
                "model": "should_not_be_used",
                "fallback_to_template": True,
            },
            "sleep_runtime": {
                "enabled": True,
                "poll_seconds": 30,
                "decision_model": "should_not_be_used_either",
            },
        }
    }

    with patch(
        "config.model_config.get_character_daily_plan_model",
        return_value="cloud:test:plan-model",
    ), patch(
        "config.model_config.get_character_daily_sleep_decision_model",
        return_value="cloud:test:sleep-model",
    ):
        config = load_character_daily_config(app_config)

    assert config.llm_plan.model == "cloud:test:plan-model"
    assert config.sleep_runtime_decision_model == "cloud:test:sleep-model"
