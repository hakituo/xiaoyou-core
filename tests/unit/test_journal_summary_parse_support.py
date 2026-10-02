from core.services.journal.summary_parse_support import parse_daily_summary_payload


def test_parse_daily_summary_payload_handles_wrapped_output():
    raw_output = """
{"daily_summary":{"date":"2026-07-01","summary":"正常总结","stats":{"entry_count":2}}}
"""

    data = parse_daily_summary_payload(raw_output)

    assert data["date"] == "2026-07-01"
    assert data["summary"] == "正常总结"
    assert data["stats"]["entry_count"] == 2


def test_parse_daily_summary_payload_recovers_broken_outer_json():
    raw_output = """
{"date":"2026-07-01","summary":"今天正常写完总结。","stats":{"entry_count":1,"chat_turn_count":18},"tomorrow_tone":"明天继续盯他早点睡。”}
"""

    data = parse_daily_summary_payload(raw_output)

    assert data["date"] == "2026-07-01"
    assert data["summary"] == "今天正常写完总结。"
    assert data["stats"]["chat_turn_count"] == 18
    assert "早点睡" in data["tomorrow_tone"]
