from core.emotion import get_emotion_manager


def test_life_stats_low_mood_maps_to_lost():
    mgr = get_emotion_manager()
    user_id = "test_user_low_mood"
    mgr._current_states.pop(user_id, None)
    mgr._global_state = mgr.get_current_state("__reset__")
    mgr._global_influences.clear()

    state = mgr.ingest_life_stats(
        user_id,
        {"mood_score": 10, "shyness_score": 0, "immune_damage": 0, "is_sick": False, "level": 1},
        intimacy_level=0.1,
    )
    assert state.primary_emotion.value in {"lost", "sad"}
    assert "lost" in (state.sub_emotions or {})


def test_life_stats_high_mood_maps_to_happy():
    mgr = get_emotion_manager()
    user_id = "test_user_high_mood"
    mgr._current_states.pop(user_id, None)
    mgr._global_state = mgr.get_current_state("__reset__")
    mgr._global_influences.clear()

    state = mgr.ingest_life_stats(
        user_id,
        {"mood_score": 90, "shyness_score": 0, "immune_damage": 0, "is_sick": False, "level": 1},
        intimacy_level=0.1,
    )
    assert state.primary_emotion.value in {"happy", "excited"}
    assert "happy" in (state.sub_emotions or {})


def test_life_stats_shyness_maps_to_shy():
    mgr = get_emotion_manager()
    user_id = "test_user_shy"
    mgr._current_states.pop(user_id, None)
    mgr._global_state = mgr.get_current_state("__reset__")
    mgr._global_influences.clear()

    state = mgr.ingest_life_stats(
        user_id,
        {"mood_score": 60, "shyness_score": 95, "immune_damage": 0, "is_sick": False, "level": 1},
        intimacy_level=0.1,
    )
    assert state.primary_emotion.value == "shy"


def test_life_stats_immune_damage_maps_to_tired_anxious():
    mgr = get_emotion_manager()
    user_id = "test_user_immune"
    mgr._current_states.pop(user_id, None)
    mgr._global_state = mgr.get_current_state("__reset__")
    mgr._global_influences.clear()

    state = mgr.ingest_life_stats(
        user_id,
        {"mood_score": 60, "shyness_score": 0, "immune_damage": 80, "is_sick": False, "level": 1},
        intimacy_level=0.1,
    )
    assert state.primary_emotion.value in {"tired", "anxious"}
    assert "tired" in (state.sub_emotions or {})
    assert "anxious" in (state.sub_emotions or {})


def test_apply_influence_normalizes_weights():
    mgr = get_emotion_manager()
    user_id = "test_user_normalize"
    mgr._current_states.pop(user_id, None)
    mgr._global_state = mgr.get_current_state("__reset__")
    mgr._global_influences.clear()

    state = mgr.apply_influence(user_id, {"happy": 0.9, "sad": 0.9}, source="test")
    total = sum((state.sub_emotions or {}).values())
    assert 0.99 <= total <= 1.01
