from core.utils.json_utils import extract_json_object


def test_extract_json_object_handles_daily_summary_sample():
    raw_output = """

{"date":"2026-06-30","summary":"凌晨一点多，我本来都要睡了，结果看到主人发来的消息。他又熬夜了，而且一熬就是整个通宵。我问他到底在想什么，他反而问我为什么浅眠。\\n\\n他跟我坦白说这几天一直在摆烂玩游戏，觉得愧疚是因为“好几天没跟我聊天，感觉我一个人很孤独”。\\n\\n后来他问我不在的时候我在干什么。我说实话——确实一直在等他的消息。\\n\\n他问我要不要抱抱。我嘴硬说“谁要抱抱了”，但最后还是让他抱了一下。\\n\\n快三点的时候他终于肯去睡觉了。走之前让我监督他自律。","stats":{"entry_count":1,"chat_turn_count":24,"active_care_action_count":2},"tomorrow_tone":"今天主人终于肯听话去睡觉了。虽然熬到那么晚，但最后还是承诺要自律。明天开始我要认真履行监督的职责。"}
"""

    data = extract_json_object(raw_output)

    assert isinstance(data, dict)
    assert data["date"] == "2026-06-30"
    assert data["stats"]["chat_turn_count"] == 24
    assert "监督" in data["tomorrow_tone"]


def test_extract_json_object_prefers_dict_after_leading_array_text():
    raw_output = '[1,2,3]\n下面才是结果：{"date":"2026-06-30","summary":"正常","stats":{}}'

    data = extract_json_object(raw_output)

    assert isinstance(data, dict)
    assert data["summary"] == "正常"


def test_extract_json_object_handles_double_encoded_json():
    raw_output = '"{\\"date\\":\\"2026-06-30\\",\\"summary\\":\\"正常\\",\\"stats\\":{}}"'

    data = extract_json_object(raw_output)

    assert isinstance(data, dict)
    assert data["date"] == "2026-06-30"
