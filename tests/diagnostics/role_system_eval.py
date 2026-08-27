import json
import os

from core.agents.chat_agent_components.persona import get_dynamic_system_prompt


class _DummyConfig:
    def __init__(self):
        self.system_prompt = "你是一个助手，请用中文回答用户问题。"

class _DummyLLMModule:
    def __init__(self, model_name: str):
        self._model_name = model_name

    def get_current_model_name(self):
        return self._model_name


class _DummyAgent:
    def __init__(self, model_name: str):
        self.config = _DummyConfig()
        self.llm_module = _DummyLLMModule(model_name)
        self.memory_echoes = None

    def _is_study_mode(self, message: str) -> bool:
        return False

    def _get_memory_manager(self, cid: str):
        raise RuntimeError("no memory")


def _detect_conflicts(prompt: str):
    conflicts = []

    if "严禁输出任何表情" in prompt and "可用简单颜文字" in prompt:
        conflicts.append("ban_all_expressions_vs_allow_kaomoji")

    if "任何括号里的描述" in prompt and "允许使用颜文字" in prompt:
        conflicts.append("ban_all_parentheses_vs_allow_kaomoji")

    if "严禁使用 [微笑]" in prompt and "例如：\n- [微笑]" in prompt:
        conflicts.append("ban_weixiao_vs_weixiao_example")

    return conflicts


def _has_qq_guard(prompt: str) -> bool:
    return "【QQ 平台硬约束】" in prompt or "QQ Platform Final Constraints" in prompt


def _qq_forbidden_phrases_present(prompt: str):
    forbidden = [
        "动作与神态描写必须用全角括号",
        "动作与神态描写可用全角括号",
        "环境氛围渲染与感官细节",
    ]
    return [p for p in forbidden if p in prompt]


def main():
    agent = _DummyAgent(model_name="cloud:deepseek:deepseek-chat")

    scenarios = [
        {
            "name": "non_qq_short",
            "user_id": "test_user",
            "mode": "chat",
            "message": "你在干嘛",
        },
        {
            "name": "non_qq_long",
            "user_id": "test_user",
            "mode": "chat",
            "message": "详细说下怎么做",
        },
        {
            "name": "qq_short",
            "user_id": "group_123_456",
            "mode": "chat",
            "message": "你在干嘛",
        },
        {
            "name": "qq_long",
            "user_id": "group_123_456",
            "mode": "chat",
            "message": "详细说下怎么做",
        },
        {
            "name": "qq_sensitive",
            "user_id": "private_123_456",
            "mode": "chat",
            "message": "/sensitive 你想我吗",
        },
    ]

    results = []
    for s in scenarios:
        prompt = get_dynamic_system_prompt(
            agent,
            user_id=s["user_id"],
            mode=s["mode"],
            message=s["message"],
        )

        is_cloud = "cloud:" in str(agent.llm_module.get_current_model_name() or "").lower()
        conflicts = _detect_conflicts(prompt)
        is_qq = "group_" in s["user_id"] or "private_" in s["user_id"]
        results.append(
            {
                "name": s["name"],
                "is_qq": is_qq,
                "is_cloud": is_cloud,
                "prompt_length": len(prompt or ""),
                "has_qq_guard": _has_qq_guard(prompt) if is_qq else False,
                "qq_forbidden_phrases": _qq_forbidden_phrases_present(prompt) if is_qq else [],
                "conflicts": conflicts,
            }
        )

    payload = {"results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    fail = str(os.getenv("XIAOYOU_DIAG_PROMPT_FAIL", "")).lower() in ("1", "true", "yes", "on")
    try:
        max_chars = int(os.getenv("XIAOYOU_DIAG_PROMPT_MAX_CHARS", "0") or "0")
    except Exception:
        max_chars = 0
    if fail and max_chars > 0:
        over = [r for r in results if int(r.get("prompt_length") or 0) > max_chars]
        if over:
            raise SystemExit(2)


if __name__ == "__main__":
    main()

