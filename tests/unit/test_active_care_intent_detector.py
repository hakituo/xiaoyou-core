from core.services.active_care.detection.intent_detector import IntentDetector


def test_extract_latest_assistant_goodnight_ignores_wakeup_teasing():
    detector = IntentDetector()
    history = [
        {
            "role": "assistant",
            "content": '下午五点起床，你可真行。这叫"起来"还是叫"睡了一整天"？',
            "timestamp": 1000.0,
        }
    ]

    result = detector.extract_latest_assistant_goodnight(
        history=history,
        now=1200.0,
    )

    assert result["detected"] is False


def test_extract_latest_assistant_goodnight_accepts_explicit_sleep_farewell():
    detector = IntentDetector()
    history = [
        {
            "role": "assistant",
            "content": "别闹了，我真要睡了，晚安。",
            "timestamp": 1000.0,
        }
    ]

    result = detector.extract_latest_assistant_goodnight(
        history=history,
        now=1200.0,
    )

    assert result["detected"] is True
    assert result["timestamp"] == 1000.0
