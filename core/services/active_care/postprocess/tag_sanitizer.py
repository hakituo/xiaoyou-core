"""消息标签规范化

背景（2026-09-02）：
    LLM 会把语音/表情等标签当成 Markdown 数学公式，输出 `$[VOICE]$` 这种
    被美元符号包裹的形式。历史上有过一个一次性清洗脚本
    （scripts/maintenance/clean_voice_tag_pollution.py），但它只清理已经落盘的
    chat_history，不匹配运行时输出，于是形成闭环污染：

        LLM 输出 $[VOICE]$ → 原样发给用户 → 写进 chat_history
        → 下一次决策把这条脏历史塞进 prompt → LLM 照着学 → 继续输出 $[VOICE]$

    用户当天连续 5 次指出这个问题，模型甚至为错误输出辩解
    （「$[VOICE]$ 是语音标记，怎么了，碍着你了？」）。

    正确做法不是继续在 prompt 里加禁令（VOICE_GUIDE 里早就写了
    「严禁在标签外加任何符号（如 $...$）」，但没有拦住），
    而是在后处理层做确定性清理——这是字符串变换，不依赖模型配合。

职责：
    把被 `$` / `$$` / 反引号包裹的已知标签还原成裸标签，只做这一件事。
"""

from __future__ import annotations

import re

# 允许出现在标签位的内置标签名。只清理这些，避免误伤正文里真实的美元金额或公式。
KNOWN_TAGS = ("VOICE", "MEME", "IMG", "IMAGE", "DELAY", "VOICE_REF")

# 构造形如：
#   (?<!\\)[$＄]{1,2}\s*[`\s]*(\[\[］]?(?:VOICE|MEME|...)[^\]］]*[\]］])\s*[`\s]*[$＄]{1,2}
# 捕获组保留标签本体，只丢弃两侧的包裹符号。
# 兼容组合：$[VOICE]$、$$[VOICE]$$、$［VOICE］$、`[VOICE]`、$[VOICE:xxx]$
_TAG_ALT = "|".join(KNOWN_TAGS)
WRAPPED_TAG_PATTERN = re.compile(
    r"[$＄]{1,2}[`\s]*"
    r"([\[［]\s*(?:" + _TAG_ALT + r")\b[^\]］]*[\]］])"
    r"[`\s]*[$＄]{1,2}",
    flags=re.IGNORECASE,
)

# 反引号包裹：`` `[VOICE]` `` / ``` [MEME:xx] ```
# 与 $ 包裹同理，属 Markdown 定界符被误用。只清理已知标签，不动代码讨论里的反引号。
BACKTICK_TAG_PATTERN = re.compile(
    r"[`]{1,3}[ \t]*"
    r"([\[［]\s*(?:" + _TAG_ALT + r")\b[^\]］]*[\]］])"
    r"[ \t]*[`]{1,3}",
    flags=re.IGNORECASE,
)

# 孤立的多余美元符号：标签没被包裹、但正文里残留了成对的 $（如 "……吗？$"）
# 只清理出现在行尾/标签附近的单个或成对 $，避免误伤 "$100" 这类金额。
STRAY_DOLLAR_PATTERN = re.compile(r"\$+(\s*$)")


class TagSanitizer:
    """规范化消息里被多余符号包裹的标签"""

    @staticmethod
    def normalize_wrapped_tags(text: str) -> str:
        """把 `$[VOICE]$` / `$$[MEME:xx]$$` 等还原成 `[VOICE]` / `[MEME:xx]`。

        不动裸标签，也不动正文里普通的 `$` 用法。
        """
        if not text:
            return text
        result = WRAPPED_TAG_PATTERN.sub(lambda m: m.group(1), text)
        result = BACKTICK_TAG_PATTERN.sub(lambda m: m.group(1), result)
        return result

    @staticmethod
    def strip_trailing_dollars(text: str) -> str:
        """去掉正文结尾残留的孤立美元符号。

        典型形态：「嗯，看路，别玩太久。$」。行尾的 $ 没有任何语义，
        留着会被用户当成乱码。
        """
        if not text:
            return text
        cleaned = STRAY_DOLLAR_PATTERN.sub("", text)
        # 连着清理多次，处理 "…。$$" 这类叠加
        while True:
            nxt = STRAY_DOLLAR_PATTERN.sub("", cleaned)
            if nxt == cleaned:
                break
            cleaned = nxt
        return cleaned

    @staticmethod
    def has_wrapped_tag(text: str) -> bool:
        """文本里是否存在被包裹的标签（供日志/测试判定）"""
        if not text:
            return False
        return bool(
            WRAPPED_TAG_PATTERN.search(text) or BACKTICK_TAG_PATTERN.search(text)
        )

    @classmethod
    def sanitize(cls, text: str) -> str:
        """完整规范化：先还原被包裹的标签，再清理结尾孤立美元符号。"""
        if not text:
            return text
        result = cls.normalize_wrapped_tags(text)
        result = cls.strip_trailing_dollars(result)
        return result
