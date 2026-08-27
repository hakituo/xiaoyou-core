from core.services.aveline_life.service import AvelineLifeRhythmService


def test_build_profile_contains_required_delay_fields():
    service = AvelineLifeRhythmService()
    profile = service._build_profile(
        date_key="2026-03-07",
        session_id="default_user",
        daily_record={
            "mood": {"mood": "tired"},
            "study": {"sessions": [{"topic": "英语"}, {"topic": "数学"}]},
            "activities": [{"content": "散步"}],
        },
        diary_summary={"summary": "今天有点累，但完成了学习计划。"},
        persona_scope="aveline",
    )
    delay = profile.get("delay") or {}
    assert "base_multiplier" in delay
    assert "surprise_probability_multiplier" in delay
    assert "surprise_min_seconds" in delay
    assert "surprise_max_seconds" in delay
    assert "recommended_comma_split_probability" in delay
    assert float(delay["surprise_max_seconds"]) >= float(delay["surprise_min_seconds"])


def test_profile_path_should_be_under_companion_data():
    service = AvelineLifeRhythmService()
    path = service._profile_path("2026-03-07")
    path_str = str(path)
    assert "companion_data" in path_str
    assert "aveline_life" in path_str
    assert path.name == "bionic_delay_profile.json"


def test_profile_path_should_support_ling_scope():
    service = AvelineLifeRhythmService()
    path = service._profile_path("2026-03-07", scope="ling")
    path_str = str(path)
    assert "companion_data" in path_str
    assert "ling_life" in path_str
    assert path.name == "bionic_delay_profile.json"
