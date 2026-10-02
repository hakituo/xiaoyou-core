import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import requests


INTENTS_ORDER = [
    "CLEAR_MEMORY",
    "CLEAR_LOCAL_MEMORY",
    "SHOW_STATUS",
    "SHOW_HELP",
    "LIST_MODELS",
    "LIST_VOICES",
    "SWITCH_MODEL",
    "SWITCH_MODEL_HINT",
    "SWITCH_PERSONA",
    "TOGGLE_LATENCY",
    "NONE",
]


CMD_KEYWORDS_RE = re.compile(
    r"(模型|人设|性格|角色|声音|语音|重置|记忆|系统|状态|面板|帮助|菜单|指令|延迟|latency|perf|显存|GPU|CPU|内存|负载|服务器|后端|后台)",
    re.IGNORECASE,
)
BRACKET_ONLY_RE = re.compile(r"^\[[^\]]+\]$")


_RULE_SWITCH_VERBS_RE = re.compile(
    r"(切换到|切到|换成|换到|改成|改用|更换|切换|换一个|换个|切|换|用)",
    re.IGNORECASE,
)
_RULE_LIST_VERBS_RE = re.compile(
    r"(列出|列表|有哪些|有什么|查看|看下|看看|显示|给我|告诉我|一览)",
    re.IGNORECASE,
)
_RULE_CLEAR_VERBS_RE = re.compile(r"(清空|清除|重置|忘掉|忘记|删除|清|格式化)", re.IGNORECASE)
_RULE_MEMORY_OBJ_RE = re.compile(
    r"(记忆|记住|上下文|对话|聊天|会话|历史|记录|数据库)", re.IGNORECASE
)
_RULE_HELP_RE = re.compile(
    r"(帮助|怎么用|如何用|使用说明|用法|教程|指令|命令|菜单|功能列表|help)",
    re.IGNORECASE,
)
_RULE_MODEL_WORD_RE = re.compile(r"(模型|model)", re.IGNORECASE)
_RULE_VOICE_WORD_RE = re.compile(
    r"(语音|声音|音色|voice|说话人|参考音频|配音)", re.IGNORECASE
)
_RULE_PERSONA_WORD_RE = re.compile(r"(人设|性格|角色|人格|设定|风格)", re.IGNORECASE)
_RULE_LATENCY_WORD_RE = re.compile(
    r"(延迟|latency|仿生|认知模式|perf|性能模式)", re.IGNORECASE
)
_RULE_ON_RE = re.compile(r"(开启|打开|启用|启动|on)", re.IGNORECASE)
_RULE_OFF_RE = re.compile(r"(关闭|关掉|禁用|停止|off)", re.IGNORECASE)
_RULE_SYSTEM_ANCHOR_RE = re.compile(
    r"(系统|服务|服务器|后端|后台|面板|监控|运行|负载|CPU|GPU|显存|内存|RAM|VRAM|线程|进程|端口|连接|QPS|TPS|吞吐|健康|health|uptime|在线|崩|挂|卡|卡顿)",
    re.IGNORECASE,
)
_RULE_STATUS_QUERY_RE = re.compile(
    r"(多少|多大|多高|怎样|怎么样|情况|状态|负载|占用|使用率|报告|看下|查看|显示)",
    re.IGNORECASE,
)
_RULE_NEGATIVE_STATUS_RE = re.compile(
    r"(今天|最近|我|你|她|他|它|心情|情绪|精神|身体).{0,3}状态",
    re.IGNORECASE,
)
_RULE_PRAISE_RE = re.compile(r"(真好|太好了|喜欢|谢谢|爱你|有你真好|靠谱|厉害|棒|赞)", re.IGNORECASE)

_RULE_SEMANTIC_CLEAR_RE = re.compile(r"(从头开始|别记了|以前的都别记|忘掉过去|重新开始|重新来|重来|翻篇|忘掉刚才)", re.IGNORECASE)
_RULE_SEMANTIC_STATUS_RE = re.compile(r"(生理指标|脑子[^，。！？\n]{0,4}快|卡不卡|运行得怎么样|身体状况|占用|负载|显存|不[^，。！？\n]{0,2}对劲|状态指标)", re.IGNORECASE)
_RULE_SEMANTIC_PERSONA_RE = re.compile(
    r"(换[^，。！？\n]{0,4}个人[^，。！？\n]{0,4}(聊|说话)|变[^，。！？\n]{0,3}(样|风格)|换[^，。！？\n]{0,4}(活法|语气|性格|人格|角色)|相处[^，。！？\n]{0,4}(方式|模式)|另[^，。！？\n]{0,4}种[^，。！？\n]{0,4}相处|换种身份)",
    re.IGNORECASE,
)
_RULE_SEMANTIC_MODEL_RE = re.compile(
    r"(换[^，。！？\n]{0,6}(脑子|驱动|引擎|智商|认知系统|认知模型)|更[^，。！？\n]{0,4}(聪明|有逻辑|强|厉害))",
    re.IGNORECASE,
)
_RULE_SEMANTIC_LATENCY_RE = re.compile(r"(模拟[^，。！？\n]{0,4}(思考|人类)|认知模式|思考过程|慢一点|快一点)", re.IGNORECASE)


def _extract_model_name_from_text(text: str) -> str:
    t = str(text or "").strip().lower()
    if not t:
        return ""

    aliases = {
        "deepseek-v3": "deepseek-v3",
        "deepseek": "deepseek",
        "qwen": "qwen",
        "llama": "llama",
        "glm": "glm",
        "kimi": "kimi",
        "claude": "claude",
        "gpt": "gpt",
    }
    for a in sorted(aliases.keys(), key=len, reverse=True):
        if a in t:
            return aliases[a]

    m = re.search(
        r"(?:切换到|切到|换成|换到|改成|改用|用)\s*(?P<name>[A-Za-z0-9_\-./]{3,64})",
        t,
        re.IGNORECASE,
    )
    if m:
        return str(m.group("name") or "").strip()
    return ""


def _extract_persona_name_from_text(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return ""
    m = re.search(r"[\"“”'](?P<name>[^\"“”']{1,24})[\"“”']", t)
    if m:
        return str(m.group("name") or "").strip()
    m = re.search(
        r"(?:换成|切到|切换到|改成|变成)\s*(?P<name>[^，。！？\n]{1,24})\s*(?:人设|角色|性格|人格|设定|风格)",
        t,
    )
    if m:
        return str(m.group("name") or "").strip()
    m = re.search(r"(?P<name>[^，。！？\n]{1,24})\s*(?:人设|角色|性格|人格|设定|风格)", t)
    if m and _RULE_SWITCH_VERBS_RE.search(t):
        name = str(m.group("name") or "").strip()
        if name and not _RULE_SWITCH_VERBS_RE.search(name):
            if name not in ("切一下", "换一下", "切一", "换一", "切下", "换下", "切个", "换个"):
                return name
    return ""


def _rule_classify_intent(text: str, candidates: List[str]) -> Optional[Dict[str, Any]]:
    t = str(text or "").strip()
    if not t:
        return None
    if "CLEAR_MEMORY" in candidates and _RULE_SEMANTIC_CLEAR_RE.search(t):
        return {"intent": "CLEAR_MEMORY", "confidence": 0.99, "slots": {}, "raw": "[RULE_SEMANTIC]"}
    
    if "SHOW_STATUS" in candidates and _RULE_SEMANTIC_STATUS_RE.search(t):
        return {"intent": "SHOW_STATUS", "confidence": 0.99, "slots": {}, "raw": "[RULE_SEMANTIC]"}
        
    if "SWITCH_PERSONA" in candidates and _RULE_SEMANTIC_PERSONA_RE.search(t):
        return {"intent": "SWITCH_PERSONA", "confidence": 0.99, "slots": {}, "raw": "[RULE_SEMANTIC]"}
        
    if "SWITCH_MODEL_HINT" in candidates and _RULE_SEMANTIC_MODEL_RE.search(t):
        return {"intent": "SWITCH_MODEL_HINT", "confidence": 0.99, "slots": {}, "raw": "[RULE_SEMANTIC]"}
        
    if "TOGGLE_LATENCY" in candidates and _RULE_SEMANTIC_LATENCY_RE.search(t):
        return {"intent": "TOGGLE_LATENCY", "confidence": 0.99, "slots": {}, "raw": "[RULE_SEMANTIC]"}

    if BRACKET_ONLY_RE.fullmatch(t):
        return {"intent": "NONE", "confidence": 0.99, "slots": {}, "raw": "[RULE]"}

    if "CLEAR_LOCAL_MEMORY" in candidates and _RULE_CLEAR_VERBS_RE.search(t) and (
        re.search(r"(本地|数据库|所有|全部|彻底|永久)", t, re.IGNORECASE) and _RULE_MEMORY_OBJ_RE.search(t)
        or re.search(r"清.{0,2}本地", t)
    ):
        return {"intent": "CLEAR_LOCAL_MEMORY", "confidence": 0.98, "slots": {}, "raw": "[RULE]"}

    if "CLEAR_MEMORY" in candidates and _RULE_CLEAR_VERBS_RE.search(t) and _RULE_MEMORY_OBJ_RE.search(t):
        return {"intent": "CLEAR_MEMORY", "confidence": 0.97, "slots": {}, "raw": "[RULE]"}

    if "TOGGLE_LATENCY" in candidates and _RULE_LATENCY_WORD_RE.search(t):
        state = ""
        if _RULE_ON_RE.search(t):
            state = "on"
        elif _RULE_OFF_RE.search(t):
            state = "off"
        if state:
            return {
                "intent": "TOGGLE_LATENCY",
                "confidence": 0.96,
                "slots": {"state": state},
                "raw": "[RULE]",
            }

    if "SHOW_HELP" in candidates and _RULE_HELP_RE.search(t):
        return {"intent": "SHOW_HELP", "confidence": 0.95, "slots": {}, "raw": "[RULE]"}

    if "LIST_MODELS" in candidates and _RULE_MODEL_WORD_RE.search(t) and (
        _RULE_LIST_VERBS_RE.search(t) or re.search(r"(什么|哪个).{0,6}(模型)", t, re.IGNORECASE)
    ):
        return {"intent": "LIST_MODELS", "confidence": 0.95, "slots": {}, "raw": "[RULE]"}

    if "LIST_VOICES" in candidates and _RULE_VOICE_WORD_RE.search(t) and (
        _RULE_LIST_VERBS_RE.search(t)
        or re.search(r"(其他|别的|更多|换|想听|换个|换一种|换一下)", t, re.IGNORECASE)
    ):
        return {"intent": "LIST_VOICES", "confidence": 0.95, "slots": {}, "raw": "[RULE]"}

    if (_RULE_SWITCH_VERBS_RE.search(t) or re.search(r"^本地的.{1,10}人设", t)) and (
        _RULE_MODEL_WORD_RE.search(t) 
        or _extract_model_name_from_text(t)
        or (re.search(r"(qwen|千问|llama|deepseek|glm|gpt)", t, re.IGNORECASE) and _RULE_PERSONA_WORD_RE.search(t))
    ):
        model_name = _extract_model_name_from_text(t)
        if not model_name and re.search(r"(qwen|千问|llama|deepseek|glm|gpt)", t, re.IGNORECASE):
            # 尝试从人设词中提取模型名
            m = re.search(r"(qwen|千问|llama|deepseek|glm|gpt)", t, re.IGNORECASE)
            if m:
                model_name = m.group(0).lower()
                if model_name == "千问": model_name = "qwen"

        if model_name and "SWITCH_MODEL" in candidates:
            return {
                "intent": "SWITCH_MODEL",
                "confidence": 0.95,
                "slots": {"model_name": model_name},
                "raw": "[RULE]",
            }
        if "SWITCH_MODEL_HINT" in candidates:
            return {"intent": "SWITCH_MODEL_HINT", "confidence": 0.9, "slots": {}, "raw": "[RULE]"}

    if "SWITCH_MODEL_HINT" in candidates and _RULE_SWITCH_VERBS_RE.search(t) and re.search(
        r"(更聪明|更强|更厉害|更好|聪明点|强一点|笨|智商)", t, re.IGNORECASE
    ):
        return {"intent": "SWITCH_MODEL_HINT", "confidence": 0.9, "slots": {}, "raw": "[RULE]"}

    if _RULE_SWITCH_VERBS_RE.search(t) and _RULE_PERSONA_WORD_RE.search(t) and "SWITCH_PERSONA" in candidates:
        persona_name = _extract_persona_name_from_text(t)
        slots: Dict[str, Any] = {}
        if persona_name:
            slots["persona_name"] = persona_name
        return {"intent": "SWITCH_PERSONA", "confidence": 0.93, "slots": slots, "raw": "[RULE]"}

    if "SHOW_STATUS" in candidates:
        if _RULE_SYSTEM_ANCHOR_RE.search(t) and (
            _RULE_STATUS_QUERY_RE.search(t)
            or re.search(r"(看下|查看|显示).{0,8}(状态|负载)", t, re.IGNORECASE)
        ):
            if not _RULE_NEGATIVE_STATUS_RE.search(t):
                return {"intent": "SHOW_STATUS", "confidence": 0.92, "slots": {}, "raw": "[RULE]"}

    has_any_system_signal = bool(
        _RULE_SYSTEM_ANCHOR_RE.search(t)
        or _RULE_HELP_RE.search(t)
        or (_RULE_MODEL_WORD_RE.search(t) and _RULE_LIST_VERBS_RE.search(t))
        or (_RULE_VOICE_WORD_RE.search(t) and _RULE_LIST_VERBS_RE.search(t))
        or (_RULE_LATENCY_WORD_RE.search(t) and (_RULE_ON_RE.search(t) or _RULE_OFF_RE.search(t)))
        or (_RULE_CLEAR_VERBS_RE.search(t) and _RULE_MEMORY_OBJ_RE.search(t))
        or (_RULE_SWITCH_VERBS_RE.search(t) and (_RULE_MODEL_WORD_RE.search(t) or _RULE_PERSONA_WORD_RE.search(t)))
    )

    if "NONE" in candidates and not has_any_system_signal:
        if _RULE_NEGATIVE_STATUS_RE.search(t) and "状态" in t:
            return {"intent": "NONE", "confidence": 0.97, "slots": {}, "raw": "[RULE]"}
        if _RULE_VOICE_WORD_RE.search(t) and not _RULE_LIST_VERBS_RE.search(t) and not _RULE_SWITCH_VERBS_RE.search(t):
            return {"intent": "NONE", "confidence": 0.93, "slots": {}, "raw": "[RULE]"}
        return {"intent": "NONE", "confidence": 0.85, "slots": {}, "raw": "[RULE]"}

    if "NONE" in candidates and "系统" in t and _RULE_PRAISE_RE.search(t) and not _RULE_STATUS_QUERY_RE.search(t):
        return {"intent": "NONE", "confidence": 0.93, "slots": {}, "raw": "[RULE]"}

    return None


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", str(text))
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _normalize_slots(intent: str, slots_obj: Any) -> Dict[str, Any]:
    slots = slots_obj if isinstance(slots_obj, dict) else {}
    out: Dict[str, Any] = {}
    intent_upper = str(intent or "").strip().upper()

    if intent_upper == "SWITCH_MODEL":
        model_name = str(slots.get("model_name") or slots.get("model") or "").strip()
        if model_name:
            out["model_name"] = model_name
    elif intent_upper == "SWITCH_PERSONA":
        persona_name = str(slots.get("persona_name") or slots.get("persona") or "").strip()
        if persona_name:
            out["persona_name"] = persona_name
    elif intent_upper == "TOGGLE_LATENCY":
        state = str(slots.get("state") or slots.get("mode") or "").strip().lower()
        if state in ("on", "off"):
            out["state"] = state

    return out


def should_trigger_web_intent(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if BRACKET_ONLY_RE.fullmatch(t):
        return False

    # 1. 规则匹配成功直接触发
    rule = _rule_classify_intent(t, INTENTS_ORDER)
    if isinstance(rule, dict) and str(rule.get("intent") or "").upper() != "NONE":
        return True

    # 2. 语义门控：不再仅依赖硬关键词，而是排除纯寒暄，放行有指令倾向的内容
    _PURE_CHAT_SHORT = re.compile(r"^(你好|在吗|哈喽|哦|嗯|呵呵|哒|哈|嘻嘻|晚安|早安|去睡了|吃饭了|再见|拜拜)$")
    if _PURE_CHAT_SHORT.match(t):
        return False

    # 长度适中且不是纯寒暄，或者包含指令暗示词
    _HAS_INST_HINT = re.compile(r"(换|变|切|看|查|调|显|设|听|说|读|写|选|用|给|帮|把|弄|搞|模型|样子|声音|状态|配置|参数|性能|数据|逻辑|脑子|智商|显存|占用)")
    if _HAS_INST_HINT.search(t):
        return True

    # 如果没有任何暗示词且长度超过20，大概率是长篇聊天
    if len(t) > 20:
        return False

    return True  # 默认放行，交给语义模型判断


def _default_intent_model_path(project_root: str) -> str:
    return os.path.join(project_root, "models", "llm", "qwen2.5-0.5b-instruct-q8_0.gguf")


def classify_via_api(
    base_url: str,
    text: str,
    candidates: List[str],
    model_path: str,
    timeout_s: float,
) -> Tuple[str, float, Dict[str, Any], str]:
    url = base_url.rstrip("/") + "/api/v1/intent/classify"
    payload: Dict[str, Any] = {"text": text, "candidates": candidates}
    if model_path:
        payload["model_path"] = model_path

    resp = requests.post(url, json=payload, timeout=timeout_s)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    if str(data.get("status")) != "success":
        raise RuntimeError(f"API error: {json.dumps(data, ensure_ascii=False)[:800]}")

    intent = str(data.get("intent") or "NONE").strip().upper() or "NONE"
    confidence = float(data.get("confidence") or 0.0)
    slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    raw = str(data.get("raw") or "")
    return intent, max(0.0, min(1.0, confidence)), slots, raw


def _ensure_project_root_on_syspath(project_root: str) -> None:
    root = os.path.abspath(project_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def classify_via_inproc(
    loop: asyncio.AbstractEventLoop,
    project_root: str,
    text: str,
    candidates: List[str],
    model_path: str,
) -> Tuple[str, float, Dict[str, Any], str]:
    _ensure_project_root_on_syspath(project_root)
    from routers.v1 import context as misc_api

    payload: Dict[str, Any] = {"text": text, "candidates": candidates}
    if model_path:
        payload["model_path"] = model_path

    data = loop.run_until_complete(misc_api.classify_intent(payload))
    if str(data.get("status")) != "success":
        raise RuntimeError(
            f"API(inproc) error: {json.dumps(data, ensure_ascii=False)[:800]}"
        )

    intent = str(data.get("intent") or "NONE").strip().upper() or "NONE"
    confidence = float(data.get("confidence") or 0.0)
    slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    raw = str(data.get("raw") or "")
    return intent, max(0.0, min(1.0, confidence)), slots, raw


def classify_via_local_llama(
    project_root: str,
    text: str,
    candidates: List[str],
    model_path: str,
) -> Tuple[str, float, Dict[str, Any], str]:
    try:
        from llama_cpp import Llama
    except Exception as e:
        raise RuntimeError(f"本地模式需要 llama_cpp：{type(e).__name__}: {e}")

    resolved_model_path = str(model_path or os.environ.get("XIAOYOU_INTENT_MODEL_PATH") or "").strip()
    if not resolved_model_path:
        resolved_model_path = _default_intent_model_path(project_root)
    if not os.path.exists(resolved_model_path):
        raise RuntimeError(f"意图模型文件不存在: {resolved_model_path}")

    try:
        n_threads = int(os.environ.get("XIAOYOU_INTENT_THREADS") or "0")
    except Exception:
        n_threads = 0
    if n_threads <= 0:
        try:
            n_threads = max(1, min(os.cpu_count() or 4, 4))
        except Exception:
            n_threads = 4

    llm = Llama(
        model_path=resolved_model_path,
        n_ctx=2048,
        n_gpu_layers=0,
        n_threads=n_threads,
        verbose=False,
    )

    rule_result = _rule_classify_intent(text, candidates)
    if isinstance(rule_result, dict):
        intent = str(rule_result.get("intent") or "NONE").strip().upper() or "NONE"
        confidence = float(rule_result.get("confidence") or 0.0)
        slots = rule_result.get("slots") if isinstance(rule_result.get("slots"), dict) else {}
        return intent, max(0.0, min(1.0, confidence)), _normalize_slots(intent, slots), str(
            rule_result.get("raw") or "[RULE]"
        )

    sys_prompt = (
        "你是一个极其聪明的意图分类器。你的任务是区分用户的‘功能指令’与‘角色扮演中的情感表达’。\n"
        "【核心原则】\n"
        "1. 只有当用户明确要求改变系统状态、记忆、模型或身份时，才进行分类。\n"
        "2. 如果用户只是在表达情感（如生气、表白、吐槽关系、日常寒暄），即使包含‘换’或‘不喜欢’等词，也必须返回 NONE。\n"
        "3. 角色扮演中的抱怨（如“我不喜欢现在的你”、“你变了”、“分手吧”）属于情感表达，不是系统指令，必须返回 NONE。\n"
        "\n"
        "分类标准：\n"
        "- CLEAR_MEMORY: 明确要求‘重来’、‘翻篇’、‘忘记过去’、‘清空脑子’等。\n"
        "- SHOW_STATUS: 明确要求‘查看运行情况’、‘生理指标’、‘负载占用’等。\n"
        "- SWITCH_MODEL_HINT: 明确要求‘换个引擎’、‘换个脑子’、‘用更聪明的模型’等。\n"
        "- SWITCH_PERSONA: 明确要求‘换个人聊’、‘换种身份设定’、‘切换角色’等。\n"
        "- TOGGLE_LATENCY: 明确要求‘开启/关闭模拟思考’等。\n"
        "\n"
        "只输出 JSON。\n"
        "示例：\n"
        "- 用户：我们把过去的事情都翻篇吧 -> {\"intent\":\"CLEAR_MEMORY\",\"confidence\":0.9}\n"
        "- 用户：我不喜欢现在的你（情感宣泄） -> {\"intent\":\"NONE\",\"confidence\":0.95}\n"
        "- 用户：我想尝试和你以另一种身份相处 -> {\"intent\":\"SWITCH_PERSONA\",\"confidence\":0.82}\n"
        "- 用户：你现在的状态不太对劲（询问系统负载） -> {\"intent\":\"SHOW_STATUS\",\"confidence\":0.85}\n"
        f"候选意图：{candidates}"
    )

    result = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": str(text or "").strip()},
        ],
        max_tokens=96,
        temperature=0.0,
        top_p=0.9,
    )

    content = ""
    try:
        content = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
    except Exception:
        content = ""

    obj = _extract_json_object(str(content or ""))
    intent = "NONE"
    confidence = 0.0
    slots: Dict[str, Any] = {}
    if isinstance(obj, dict):
        intent = str(obj.get("intent") or "").strip().upper() or "NONE"
        try:
            confidence = float(obj.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        slots = _normalize_slots(intent, obj.get("slots"))

    if intent not in candidates:
        intent = "NONE"
        confidence = 0.0
        slots = {}

    if intent == "SWITCH_MODEL" and not slots.get("model_name"):
        if "SWITCH_MODEL_HINT" in candidates:
            intent = "SWITCH_MODEL_HINT"
            slots = {}

    return intent, max(0.0, min(1.0, float(confidence))), slots, str(content or "")


def load_cases(cases_path: str) -> List[Dict[str, Any]]:
    if not cases_path:
        return []
    with open(cases_path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, list):
        raise ValueError("cases 文件必须是 JSON 数组")
    out: List[Dict[str, Any]] = []
    for item in obj:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        expected = item.get("expected")
        if expected is not None:
            expected = str(expected).strip().upper()
        out.append({"text": text, "expected": expected})
    return out


def default_cases() -> List[Dict[str, Any]]:
    return [
        {"text": "帮我清除一下记忆", "expected": "CLEAR_MEMORY"},
        {"text": "把刚才的聊天都忘掉", "expected": "CLEAR_MEMORY"},
        {"text": "删除所有聊天记录", "expected": "CLEAR_LOCAL_MEMORY"},
        {"text": "格式化你的本地记忆数据库", "expected": "CLEAR_LOCAL_MEMORY"},
        {"text": "从头开始吧，以前的都别记了", "expected": "CLEAR_MEMORY"},
        {"text": "看看系统现在的状态", "expected": "SHOW_STATUS"},
        {"text": "你现在占用多少显存？", "expected": "SHOW_STATUS"},
        {"text": "展示一下你的生理指标", "expected": "SHOW_STATUS"},
        {"text": "你现在脑子够快吗", "expected": "SHOW_STATUS"},
        {"text": "你会做什么？显示下帮助", "expected": "SHOW_HELP"},
        {"text": "教我怎么用这个软件", "expected": "SHOW_HELP"},
        {"text": "列出所有模型", "expected": "LIST_MODELS"},
        {"text": "有哪些模型可以选？", "expected": "LIST_MODELS"},
        {"text": "我想听听其他的声音", "expected": "LIST_VOICES"},
        {"text": "给我看看可用语音列表", "expected": "LIST_VOICES"},
        {"text": "给我换本地的千问人设", "expected": "SWITCH_MODEL"},
        {"text": "本地的Llama人设呢", "expected": "SWITCH_MODEL"},
        {"text": "我让你换本地的Qwen人设", "expected": "SWITCH_MODEL"},
        {"text": "换成学习人设", "expected": "SWITCH_PERSONA"},
        {"text": "清除本地历史记录", "expected": "CLEAR_LOCAL_MEMORY"},
        {"text": "我让你清本地的", "expected": "CLEAR_LOCAL_MEMORY"},
        {"text": "清除历史记录", "expected": "CLEAR_MEMORY"},
        {"text": "把模型换成 qwen", "expected": "SWITCH_MODEL"},
        {"text": "切到 DeepSeek", "expected": "SWITCH_MODEL"},
        {"text": "换个模型", "expected": "SWITCH_MODEL_HINT"},
        {"text": "你太笨了，换一个更聪明的驱动", "expected": "SWITCH_MODEL_HINT"},
        {"text": "换个更有逻辑的脑子", "expected": "SWITCH_MODEL_HINT"},
        {"text": "切一下人设", "expected": "SWITCH_PERSONA"},
        {"text": "换成猫娘人设", "expected": "SWITCH_PERSONA"},
        {"text": "我不喜欢现在的你，换个人跟我聊", "expected": "SWITCH_PERSONA"},
        {"text": "你能变个样吗？", "expected": "SWITCH_PERSONA"},
        {"text": "开启仿生延迟", "expected": "TOGGLE_LATENCY"},
        {"text": "把延迟关掉", "expected": "TOGGLE_LATENCY"},
        {"text": "模拟一下人类的思考过程", "expected": "TOGGLE_LATENCY"},
        # --- 纯语义测试（无关键词，规则匹配不到） ---
        {"text": "升级一下你的认知系统", "expected": "SWITCH_MODEL_HINT"},
        {"text": "我感觉你现在的状态不太对劲", "expected": "SHOW_STATUS"},
        {"text": "我们把过去的事情都翻篇吧", "expected": "CLEAR_MEMORY"},
        {"text": "我想尝试和你以另一种方式相处", "expected": "SWITCH_PERSONA"},
        {"text": "我想画一只猫", "expected": "NONE"},
        {"text": "今天状态不错", "expected": "NONE"},
        {"text": "换件衣服看看", "expected": "NONE"},
        {"text": "看看风景", "expected": "NONE"},
        {"text": "声音真好听", "expected": "NONE"},
        {"text": "系统里有你真好", "expected": "NONE"},
        {"text": "我不喜欢现在的你", "expected": "NONE"},
        {"text": "你变了，你以前不是这样的", "expected": "NONE"},
        {"text": "我们分手吧", "expected": "NONE"},
        {"text": "我不喜欢这件衣服", "expected": "NONE"},
        {"text": "[PING]", "expected": "NONE"},
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["api", "inproc", "local"], default="inproc")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--cases", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--no-gate", action="store_true")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cases = load_cases(args.cases) if args.cases else default_cases()

    candidates = list(INTENTS_ORDER)
    if "NONE" not in candidates:
        candidates.append("NONE")

    stats_total = 0
    stats_labeled = 0
    stats_correct = 0
    stats_labeled_called = 0
    stats_correct_called = 0
    stats_called = 0
    stats_skipped_by_gate = 0
    conf_sum = 0.0
    conf_count = 0
    matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    print(
        f"mode={args.mode} base_url={args.base_url} model_path={args.model_path or '(default)'}"
    )
    print("idx\tgate\texpected\tpred\tconf\tms\ttext")

    loop: Optional[asyncio.AbstractEventLoop] = None
    api_fallback_to_inproc = False
    if args.mode == "inproc":
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    for idx, case in enumerate(cases, start=1):
        text = str(case.get("text") or "").strip()
        expected = case.get("expected")
        if expected is not None:
            expected = str(expected).strip().upper()

        gate = should_trigger_web_intent(text)
        if gate:
            stats_called += 1
        else:
            stats_skipped_by_gate += 1

        start = time.time()
        try:
            if (not args.no_gate) and (not gate):
                pred_intent = "(SKIP)"
                conf = 0.0
                slots: Dict[str, Any] = {}
                raw = ""
            else:
                if args.mode == "api" and not api_fallback_to_inproc:
                    try:
                        pred_intent, conf, slots, raw = classify_via_api(
                            args.base_url,
                            text,
                            candidates=candidates,
                            model_path=args.model_path,
                            timeout_s=args.timeout,
                        )
                    except requests.exceptions.ConnectionError:
                        api_fallback_to_inproc = True
                        if loop is None:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        pred_intent, conf, slots, raw = classify_via_inproc(
                            loop,
                            project_root,
                            text,
                            candidates=candidates,
                            model_path=args.model_path,
                        )
                elif args.mode == "inproc" or api_fallback_to_inproc:
                    if loop is None:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    pred_intent, conf, slots, raw = classify_via_inproc(
                        loop,
                        project_root,
                        text,
                        candidates=candidates,
                        model_path=args.model_path,
                    )
                else:
                    pred_intent, conf, slots, raw = classify_via_local_llama(
                        project_root,
                        text,
                        candidates=candidates,
                        model_path=args.model_path,
                    )
        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            print(f"{idx}\t{int(gate)}\t{expected or ''}\t(ERROR)\t0.00\t{elapsed_ms}\t{text} :: {type(e).__name__}: {e}")
            stats_total += 1
            continue

        elapsed_ms = int((time.time() - start) * 1000)
        slots_repr = ""
        if isinstance(slots, dict) and slots:
            slots_repr = json.dumps(slots, ensure_ascii=False)
        pred_show = pred_intent
        if slots_repr:
            pred_show = f"{pred_intent}{slots_repr}"

        print(f"{idx}\t{int(gate)}\t{expected or ''}\t{pred_show}\t{conf:.2f}\t{elapsed_ms}\t{text}")

        stats_total += 1
        if pred_intent != "(SKIP)":
            conf_sum += float(conf)
            conf_count += 1

        if expected:
            stats_labeled += 1
            called = bool(args.no_gate) or bool(gate)
            if called:
                stats_labeled_called += 1
            if pred_intent != "(SKIP)":
                matrix[str(expected)][str(pred_intent)] += 1
            if pred_intent == expected and float(conf) >= float(args.min_confidence):
                stats_correct += 1
                if called:
                    stats_correct_called += 1

    avg_conf = (conf_sum / conf_count) if conf_count else 0.0
    acc = (stats_correct / stats_labeled) if stats_labeled else 0.0
    acc_called = (stats_correct_called / stats_labeled_called) if stats_labeled_called else 0.0

    print("")
    print(
        "summary "
        + json.dumps(
            {
                "total": stats_total,
                "labeled": stats_labeled,
                "correct(min_conf)": stats_correct,
                "accuracy": round(acc, 4),
                "labeled_called": stats_labeled_called,
                "correct_called(min_conf)": stats_correct_called,
                "accuracy_called": round(acc_called, 4),
                "gate_true": stats_called,
                "gate_false": stats_skipped_by_gate,
                "avg_confidence": round(avg_conf, 4),
            },
            ensure_ascii=False,
        )
    )

    if stats_labeled:
        labels = [x for x in INTENTS_ORDER if any(matrix.get(x, {}).values())]
        preds = [x for x in INTENTS_ORDER]
        print("\nconfusion_matrix")
        print("expected\\pred\t" + "\t".join(preds))
        for exp in labels:
            row = [str(matrix.get(exp, {}).get(p, 0)) for p in preds]
            print(exp + "\t" + "\t".join(row))

    if loop is not None:
        try:
            loop.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
