from __future__ import annotations

from core.services.study.persona.study_persona_profile import StudyPersonaProfile


def test_default_study_persona_path_points_to_config_subdir() -> None:
    profile = StudyPersonaProfile()
    assert profile.persona_filename == "study/Aveline_Study.json"


def test_v2_selected_overlay_drives_study_instruction(monkeypatch) -> None:
    profile = StudyPersonaProfile()
    persona_data = {
        "meta": {
            "context_profile": {
                "root": "aveline",
                "selected_overlay": "overlays/study_aveline.json",
            }
        }
    }
    overlay = {
        "mode": {"role": "严厉但以学习效果为目标的高考导师"},
        "teaching_policy": {
            "on_study": ["先判断卡点", "最多问一个必要问题"],
            "on_error": "只批评方法，不攻击人格",
            "on_distraction": "把注意力拉回当前学习任务",
            "on_fatigue": "允许短暂恢复",
            "on_uncertainty": "不确定时直接说明需要确认",
        },
        "response_style": ["需要多少讲多少", "简单确认仍然短"],
    }

    monkeypatch.setattr(profile, "_load_persona_data", lambda: persona_data)
    monkeypatch.setattr(profile, "_load_selected_overlay", lambda data: overlay)

    text = profile.build_mode_instruction()
    assert "严厉但以学习效果为目标的高考导师" in text
    assert "先判断卡点；最多问一个必要问题" in text
    assert "只批评方法，不攻击人格" in text
    assert "不确定时直接说明需要确认" in text
    assert "需要多少讲多少；简单确认仍然短" in text


def test_legacy_study_structure_still_has_fallback(monkeypatch) -> None:
    profile = StudyPersonaProfile("study/Legacy_Study.json")
    legacy = {
        "identity": {"roles": ["Strict Tutor", "Time Manager"]},
        "interaction_logic": {
            "interaction_rules": {
                "on_study": "先引导定位卡点",
                "on_distraction": "拉回学习任务",
                "on_fatigue": "允许短暂休息",
            },
            "constraints": {
                "max_length": "按题目需要展开",
                "splitting_behavior": "逻辑分段",
            },
        },
    }

    monkeypatch.setattr(profile, "_load_persona_data", lambda: legacy)
    monkeypatch.setattr(profile, "_load_selected_overlay", lambda data: {})

    text = profile.build_mode_instruction()
    assert "Strict Tutor / Time Manager" in text
    assert "先引导定位卡点" in text
    assert "拉回学习任务" in text
    assert "按题目需要展开" in text
    assert "逻辑分段" in text
