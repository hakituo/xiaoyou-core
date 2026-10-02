
import re

def test_topic_extraction():
    # Test cases based on the instruction in aveline.py
    test_cases = [
        "[EMO: happy] [TOPIC: 编程, python] 好的，我们可以聊聊 Python。",
        "[EMO: neutral][TOPIC:日常/天气]今天天气真不错。",
        "[TOPIC: 游戏] [EMO: excited] 这款游戏太好玩了！", # Order shouldn't matter for regex, but usually EMO comes first
        "没有标签的回复",
        "[TOPIC:   ] 空标签",
        "[TOPIC: topic1, topic2, topic3] 多标签"
    ]

    print("Testing Topic Extraction Logic...")
    
    for content in test_cases:
        print(f"\nInput: {content}")

        # Logic from streaming.py
        extracted_topics = []
        final_content = content

        topic_match = re.search(r"\[TOPIC:\s*(.*?)\]", content, re.IGNORECASE)
        if topic_match:
            raw_topics = topic_match.group(1).strip()
            # Remove the tag from history content
            final_content = content.replace(topic_match.group(0), "").strip()

            if raw_topics:
                # Split by comma, slash or space
                extracted_topics = [t.strip() for t in re.split(r"[,，/、\s]+", raw_topics) if t.strip()]

        print(f"Extracted Topics: {extracted_topics}")
        print(f"Final Content: {final_content}")

        assert isinstance(extracted_topics, list), "extracted_topics 应为列表"
        assert isinstance(final_content, str), "final_content 应为字符串"
        assert all(isinstance(t, str) for t in extracted_topics), "所有 topic 应为字符串"
        if topic_match:
            assert "[TOPIC:" not in final_content, "final_content 不应再包含 [TOPIC: 标签"

if __name__ == "__main__":
    test_topic_extraction()
