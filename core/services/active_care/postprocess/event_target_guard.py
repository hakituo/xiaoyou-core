"""Active Care 硬事件的确定性目标守卫。

当前只保留词汇任务状态纠偏。数字健康（应用使用超限）的文案纠偏已移除：
原先会在模型没写出应用正式名时硬拼「{应用名}：...」前缀，观感像系统通知，
且别名表 key 与指令里的中文显示名对不上，导致模型用「B站」这类口语叫法时
被误判为漏目标。现在完全信任模型输出，prompt 中已约束不得声称设备执行结果。
"""

import re

_VOCAB_TOPIC_PATTERN = re.compile(
    r"(?:背|复习|记|学).{0,3}(?:单词|词汇)|(?:单词|词汇).{0,3}(?:背|复习|任务)"
)
_VOCAB_PENDING_PATTERN = re.compile(
    r"(?:背完(?:了)?没|背得怎么样|还(?:有|剩)|待复习|要(?:背|复习)|该(?:背|复习)|"
    r"今天背完|个呢|压着|等着|别.{0,8}拖|赶紧.{0,5}(?:背|复习))"
)
_VOCAB_COUNT_PATTERN = re.compile(r"\d+\s*个(?=\s*(?:单词|词汇|词|呢))")


def mentions_vocabulary_topic(content: str) -> bool:
    """判断主动消息是否在谈词汇任务。"""
    return bool(_VOCAB_TOPIC_PATTERN.search(str(content or "")))


def enforce_vocabulary_status(content: str, status: dict) -> str:
    """用实时词汇状态纠正旧数量和已完成后的继续催促。"""
    text = str(content or "").strip()
    if not text or not mentions_vocabulary_topic(text):
        return text

    remaining = max(0, int(status.get("remaining_words") or 0))
    unresolved = max(0, int(status.get("unresolved_words") or 0))
    has_pending_claim = bool(_VOCAB_PENDING_PATTERN.search(text))
    has_numeric_count = bool(_VOCAB_COUNT_PATTERN.search(text))

    if bool(status.get("completed")) and has_pending_claim:
        if unresolved > 0:
            return f"今天的单词已经背完了，{unresolved}个没掌握的也留到明天复习了。今晚不用再赶。"
        return "今天的单词已经背完了。辛苦啦，今晚不用再赶。"

    if remaining > 0 and has_pending_claim and has_numeric_count:
        return _VOCAB_COUNT_PATTERN.sub(f"{remaining}个", text)
    return text
