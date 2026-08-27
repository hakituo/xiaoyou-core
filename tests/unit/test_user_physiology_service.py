from core.services.user_physiology.service import get_user_physiology_service


def test_user_physiology_update_and_get_latest():
    svc = get_user_physiology_service()
    rec = svc.update(
        user_id="u1",
        payload={
            "source": "manual",
            "metrics": {
                "heart_rate_bpm": 72,
                "sleep_hours_last_night": 6.5,
                "spo2_percent": 98,
                "steps_today": 1234,
                "stress_level": 0.2,
            },
        },
    )
    assert rec["user_id"] == "u1"
    assert rec["source"] == "manual"
    assert rec["metrics"]["heart_rate_bpm"] == 72.0
    assert rec["metrics"]["steps_today"] == 1234

    latest = svc.get_latest("u1", stale_after_seconds=3600)
    assert latest is not None
    assert latest["user_id"] == "u1"
    assert latest["is_stale"] is False


def test_user_physiology_flags_derive():
    svc = get_user_physiology_service()
    rec = svc.update(
        user_id="u2",
        payload={
            "source": "manual",
            "metrics": {
                "heart_rate_bpm": 130,
                "sleep_hours_last_night": 4.0,
                "spo2_percent": 90,
                "stress_level": 0.9,
            },
        },
    )
    urgent = (rec.get("flags") or {}).get("urgent_needs") or []
    assert "high_heart_rate" in urgent
    assert "sleep_deprived" in urgent
    assert "low_spo2" in urgent
    assert "high_stress" in urgent

