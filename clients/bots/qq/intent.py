import json
import os
import re

from clients.bots.qq.settings import logger


class SemanticIntentRecognizer:
    """
    Recognizes natural language intents for system control.
    Loads patterns from commands.json if available, otherwise uses defaults.

    [Fix] 只有 / 开头的消息才进行本地正则意图匹配，避免普通聊天被误识别为指令。
    例如 "switch model" 在普通聊天中不应该被识别为切换模型的命令。
    """

    def __init__(self):
        self.patterns = []
        self._load_patterns()

    def _load_patterns(self):
        defaults = [
            (re.compile(r"^/?(清除|清空|删除|忘掉)\s*(记忆|历史|聊天记录)"), "CLEAR_MEMORY"),
            (re.compile(r"^/?(查看|看看|显示)\s*(状态|系统|负载|占用)"), "SHOW_STATUS"),
            (re.compile(r"^/?(帮助|菜单|指令列表|功能列表|功能菜单)"), "SHOW_HELP"),
            (re.compile(r"^/?(模块|功能)\s*(介绍|说明|文档|指南|readme)", re.IGNORECASE), "SHOW_MODULE_DOC"),
            (re.compile(r"^/?(切换|换个)\s*(模型|LLM)"), "SWITCH_MODEL_HINT"),
            (re.compile(r"^/?(查看|列出)\s*(模型)"), "LIST_MODELS"),
            (re.compile(r"^/?(查看|列出)\s*(音频|声音|语音)"), "LIST_VOICES"),
            (re.compile(r"^/?(tts|TTS|语音)\s*(模式|切换|类型)"), "SWITCH_TTS_MODE"),
        ]

        json_path = os.path.join(os.path.dirname(__file__), "commands.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        intent = item.get("intent")
                        patterns = item.get("patterns", [])
                        for p_str in patterns:
                            try:
                                self.patterns.append((re.compile(p_str, re.IGNORECASE), intent))
                            except re.error as e:
                                logger.error(f"Invalid regex pattern '{p_str}': {e}")
                logger.info(f"Loaded {len(self.patterns)} semantic patterns from commands.json")
            except Exception as e:
                logger.error(f"Failed to load commands.json: {e}")
                self.patterns = defaults
        else:
            self.patterns = defaults

    def match(self, text: str):
        """
        尝试使用本地正则匹配意图。
        如果匹配成功，返回 {"intent": "XXX", "slots": {}, "confidence": 1.0}
        如果匹配失败，返回 None

        [Fix] 只有以 / 开头的消息才进行本地正则匹配，避免普通聊天被误识别为指令。
        """
        if not text:
            return None

        text = text.strip()

        if not text.startswith("/"):
            return None

        for pattern, intent in self.patterns:
            match = pattern.search(text)
            if match:
                logger.info(f"Local Intent Match: {intent} (pattern: {pattern.pattern})")
                return {
                    "intent": intent,
                    "slots": {},
                    "confidence": 1.0,
                    "source": "local_regex"
                }

        return None

