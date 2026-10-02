from core.utils.logger import get_logger
import asyncio

import os
import re
from typing import Any, Dict, List, Optional
from core.services.data_ops.bert_analyzer import get_bert_analyzer

logger = get_logger(__name__)

# [DEPRECATED] _intent_llm 相关变量保留以兼容可能的旧调用，但实际上已被 BERT 取代
_intent_llm = None
_intent_llm_lock = asyncio.Lock()
_intent_inference_lock = asyncio.Lock()

# 规则正则表达式
# 虽然有了 BERT，保留部分极高频的正则匹配作为第一层拦截仍然是高效的
_RULE_SWITCH_VERBS_RE = re.compile(
    r"(切换到|切到|换成|换到|改成|改用|更换|切换|换一个|换个|切|换|用|变)",
    re.IGNORECASE,
)
_RULE_LIST_VERBS_RE = re.compile(
    r"(列出|列表|有哪些|有什么|查看|看下|看看|显示|给我|告诉我|一览)",
    re.IGNORECASE,
)
_RULE_CLEAR_VERBS_RE = re.compile(
    r"(清空|清除|重置|忘掉|忘记|忘了|删除|清|格式化)", re.IGNORECASE
)
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
_RULE_PRAISE_RE = re.compile(
    r"(真好|太好了|喜欢|谢谢|爱你|有你真好|靠谱|厉害|棒|赞)", re.IGNORECASE
)
_RULE_NARRATIVE_PREFIX_RE = re.compile(
    r"^(还是|只是|正在|已经|刚|刚刚|才|就|只有|一直|总是|老是|用来|用于|其实|就是|感觉|觉得|好像|似乎|可能|应该|大概|也许|不过|但是|可是|而且|然后|接着|所以|因为|虽然|哪怕|就算|哪怕|反正|不管|无论|当然|确实|真的|明明|本来|原来|毕竟|反而|倒|却|幸亏|好在|只好|只能|不得不|难道|岂|怎|怎么|怎样|什么|为什么|为啥|哪|哪里|哪个|谁|多少|几|多|想|要|会|能|可以|敢|肯|愿|得|需要|必须|应该|得|不得不)",
    re.IGNORECASE
)
_RULE_QUOTE_OR_REFERENCE_RE = re.compile(
    r"(你(刚才|之前|之前|刚刚|之前|不是)?(说|说的|说过|发的|回复的|回的)|这句话(不是|不是你|不是你说的)|不是你(说|说过的|发的)|你(不是|不是刚)?(说了|说了什么)|你(刚才|之前)?不是(说|说了|说过)|引用|转述|复述|原话)",
    re.IGNORECASE,
)

_RULE_SEMANTIC_CLEAR_RE = re.compile(
    r"(别记了|以前的都别记|不要记|别保存|不要保存|忘掉过去|忘掉刚才|删掉刚才|删除刚才|把刚才删了|把刚才忘了)",
    re.IGNORECASE,
)
_RULE_CLEAR_CMD_PREFIX_RE = re.compile(
    r"(请|帮我|给我|麻烦|把|将|我要|我想|能不能|可以|来个|执行|一下|立刻|马上)",
    re.IGNORECASE,
)
_RULE_CLEAR_STATUS_RE = re.compile(
    r"(已|已经|刚刚|刚才|正在|会|被).{0,6}(清除|清空|重置|删除|忘记|格式化)",
    re.IGNORECASE,
)
_RULE_SEMANTIC_STATUS_RE = re.compile(
    r"(生理指标|脑子[^，。！？\n]{0,4}快|卡不卡|运行得怎么样|身体状况|占用|负载|显存|不[^，。！？\n]{0,2}对劲|状态指标)",
    re.IGNORECASE,
)
_RULE_SEMANTIC_PERSONA_RE = re.compile(
    r"(换[^，。！？\n]{0,4}个人[^，。！？\n]{0,4}(聊|说话)|变[^，。！？\n]{0,3}(样|风格)|换[^，。！？\n]{0,4}(活法|语气|性格|人格|角色)|相处[^，。！？\n]{0,4}(方式|模式)|另[^，。！？\n]{0,4}种[^，。！？\n]{0,4}相处|换种身份)",
    re.IGNORECASE,
)
_RULE_SEMANTIC_MODEL_RE = re.compile(
    r"(换[^，。！？\n]{0,6}(脑子|驱动|引擎|智商|认知系统|认知模型)|更[^，。！？\n]{0,4}(聪明|有逻辑|强|厉害))",
    re.IGNORECASE,
)
_RULE_SEMANTIC_LATENCY_RE = re.compile(
    r"(模拟[^，。！？\n]{0,4}(思考|人类)|认知模式|思考过程|慢一点|快一点)",
    re.IGNORECASE,
)
_RULE_ACTIVE_CARE_DELAY_RE = re.compile(
    r"(过一会|过会|晚点|稍后|再提醒|再叫我|再找我|过多久提醒|多久后提醒|两小时后|半小时后|分钟后|小时后)",
    re.IGNORECASE,
)
_RULE_ACTIVE_CARE_DELAY_CONTEXT_RE = re.compile(
    r"(之后|以后|等会|一会儿|等一会儿)",
    re.IGNORECASE,
)
_RULE_ACTIVE_CARE_SNOOZE_VERB_RE = re.compile(
    r"(提醒|叫|找|通知|打扰|烦)",
    re.IGNORECASE,
)
_RULE_IMAGE_GEN_RE = re.compile(
    r"(/生图|画个|画一张|画一幅|生成图片|画下|生个图|画画)", re.IGNORECASE
)
_RULE_IMAGE_GEN_NEGATIVE_RE = re.compile(
    r"(画什么画|画[^，。！？]{0,10}什么东西|(不要|别|不准|停止).{0,5}画|会画[^，。！？]{0,5}吗|画质|画面|看你画|画了|画过|画完|画的|画出来|画好|画得|画着|画[^，。！？\n]{0,6}画|给他画|给她画|给我画了)",
    re.IGNORECASE,
)

_known_model_aliases_cache: Optional[Dict[str, str]] = None
_known_persona_names_cache: Optional[List[str]] = None


# 废弃函数清理区
# 原 _build_intent_sys_prompt, _get_known_persona_names, _try_parse_intent_from_text 已不再使用


def get_default_intent_model_path() -> str:
    """
    [Compatibility] 获取默认意图模型路径。
    注意：现在的意图识别主要由 BERT (onnx) 完成，此函数仅用于兼容旧接口或配置查询。
    """
    return os.path.join(os.path.dirname(__file__), "models", "bert_intent.onnx")


def _get_known_model_aliases() -> Dict[str, str]:
    global _known_model_aliases_cache
    if _known_model_aliases_cache is not None:
        return _known_model_aliases_cache

    aliases: Dict[str, str] = {}
    try:
        from core.core_engine.model_manager import get_model_manager

        manager = get_model_manager()

        for name, info in manager._models.items():
            name_norm = name.strip().lower()
            if name_norm:
                aliases[name_norm] = name

            path = info.model_path
            if path:
                base_name = os.path.splitext(os.path.basename(path))[0].lower()
                if base_name and len(base_name) >= 3:
                    aliases.setdefault(base_name, name)

                if path.startswith("cloud:"):
                    parts = path.split(":")
                    if len(parts) >= 3:
                        cloud_model = parts[2].lower()
                        if cloud_model and len(cloud_model) >= 3:
                            aliases.setdefault(cloud_model, name)

            for token in re.split(r"[^a-zA-Z0-9\u4e00-\u9fa5]+", name.lower()):
                token = token.strip()
                if token and len(token) >= 2:
                    aliases.setdefault(token, name)
    except Exception as e:
        logger.warning(f"Error building model aliases: {e}")

    for base in [
        ("qwen", "qwen"),
        ("deepseek", "deepseek"),
        ("llama", "llama"),
        ("glm", "glm"),
        ("kimi", "kimi"),
        ("claude", "claude"),
        ("gpt", "gpt"),
    ]:
        aliases.setdefault(base[0], base[1])

    _known_model_aliases_cache = aliases
    return aliases


def _extract_model_name_from_text(text: str) -> str:
    t = str(text or "").strip().lower()
    if not t:
        return ""

    aliases = _get_known_model_aliases()
    best_alias = ""
    for a in sorted(aliases.keys(), key=len, reverse=True):
        if not a or len(a) < 3:
            continue
        if a in t:
            best_alias = a
            break
    if best_alias:
        return str(aliases.get(best_alias) or best_alias).strip()

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
    m = re.search(
        r"(?P<name>[^，。！？\n]{1,24})\s*(?:人设|角色|性格|人格|设定|风格)", t
    )
    if m and _RULE_SWITCH_VERBS_RE.search(t):
        name = str(m.group("name") or "").strip()
        if name and not _RULE_SWITCH_VERBS_RE.search(name):
            if name not in (
                "切一下",
                "换一下",
                "切一",
                "换一",
                "切下",
                "换下",
                "切个",
                "换个",
            ):
                return name
    return ""


def _is_explicit_clear_memory_command(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if re.match(r"^/\s*(清空|清除|重置|删除)\s*(记忆|上下文|对话|聊天|会话|历史)", t, re.IGNORECASE):
        return True
    if _RULE_CLEAR_STATUS_RE.search(t):
        return False
    if not (_RULE_CLEAR_VERBS_RE.search(t) and _RULE_MEMORY_OBJ_RE.search(t)):
        return False
    if re.fullmatch(
        r"\s*(请|麻烦)?\s*(清空|清除|重置|删除|忘掉|忘记|格式化)\s*(一下|下)?\s*(我(的)?|全部|所有)?\s*(记忆|上下文|对话|聊天|会话|历史|记录)\s*(吧|呀|呢)?\s*",
        t,
        re.IGNORECASE,
    ):
        return True
    return bool(_RULE_CLEAR_CMD_PREFIX_RE.search(t))


def _has_explicit_command_tone(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if t.startswith("/"):
        return True
    if re.match(
        r"^\s*(请|麻烦|帮我|给我|把|将|立刻|马上|现在)?\s*(查看|显示|列出|切换|设置|开启|关闭|打开|禁用|启用|清空|清除|重置|删除|恢复|改成|改为|调整)",
        t,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(请|麻烦|帮我|给我).{0,8}(查看|显示|列出|切换|设置|开启|关闭|清空|清除|重置|删除|调整)",
        t,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(回复模式|latency|延迟|仿生延迟|私密模式|隐私模式|学习模式).{0,8}(改成|改为|切换|设置|开启|关闭|打开|关掉|开)",
        t,
        re.IGNORECASE,
    ):
        return True
    return False


def _has_explicit_snooze_tone(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if _RULE_QUOTE_OR_REFERENCE_RE.search(t):
        return False
    if _RULE_ACTIVE_CARE_DELAY_RE.search(t):
        return True
    if _RULE_ACTIVE_CARE_DELAY_CONTEXT_RE.search(t) and _RULE_ACTIVE_CARE_SNOOZE_VERB_RE.search(t):
        return True
    if re.search(
        r"(别|不要|不用|先别|暂停|停).{0,6}(提醒|打扰|烦|找|发消息|发来)",
        t,
        re.IGNORECASE,
    ):
        return True
    return False


def rule_classify_intent(text: str, candidates: list[str]) -> Optional[Dict[str, Any]]:
    t = str(text or "").strip()
    if not t:
        return None
    if re.fullmatch(r"\[[^\]]+\]", t):
        return {"intent": "NONE", "confidence": 0.99, "slots": {}, "raw": "[RULE]"}

    # 负面意图拦截：防止画画相关的模糊语句误触发
    if "NONE" in candidates and _RULE_IMAGE_GEN_NEGATIVE_RE.search(t):
        return {
            "intent": "NONE",
            "confidence": 0.99,
            "slots": {},
            "raw": "[RULE_NEGATIVE]",
        }

    if "DISABLE_VOICE_REPLY" in candidates and (
        re.search(r"(不要|不用|别|停止|关闭|关掉).{0,6}(语音|声音).{0,4}(回复|说|发)?", t, re.IGNORECASE)
        or re.search(r"(改成|换成|切成).{0,4}文字.{0,4}(回复)?", t, re.IGNORECASE)
    ):
        return {
            "intent": "DISABLE_VOICE_REPLY",
            "confidence": 0.98,
            "slots": {},
            "raw": "[RULE]",
        }

    if "CLEAR_MEMORY" in candidates and _RULE_SEMANTIC_CLEAR_RE.search(t) and _has_explicit_command_tone(t):
        return {
            "intent": "CLEAR_MEMORY",
            "confidence": 0.95,
            "slots": {},
            "raw": "[RULE]",
        }

    # 状态查看、人设切换、模型切换、提醒、搜索 等全部交给语义模型判定
    # 规则层仅保留极少数绝对明确的硬指令拦截

    if "TOGGLE_LATENCY" in candidates and _RULE_SEMANTIC_LATENCY_RE.search(t):
        if not _has_explicit_command_tone(t):
            return None
        return {
            "intent": "TOGGLE_LATENCY",
            "confidence": 0.95,
            "slots": {},
            "raw": "[RULE]",
        }

    # IMAGE_GEN 移出规则匹配，强制走语义模型识别

    if (
        "CLEAR_LOCAL_MEMORY" in candidates
        and _RULE_CLEAR_VERBS_RE.search(t)
        and (
            re.search(r"(本地|数据库|所有|全部|彻底|永久)", t, re.IGNORECASE)
            and _RULE_MEMORY_OBJ_RE.search(t)
            or re.search(r"清.{0,2}本地", t)
        )
        and _has_explicit_command_tone(t)
    ):
        return {
            "intent": "CLEAR_LOCAL_MEMORY",
            "confidence": 0.98,
            "slots": {},
            "raw": "[RULE]",
        }

    if "ACTIVE_CARE_SNOOZE" in candidates:
        if _RULE_QUOTE_OR_REFERENCE_RE.search(t):
            pass
        else:
            snooze_matched = _RULE_ACTIVE_CARE_DELAY_RE.search(t)
            context_matched = _RULE_ACTIVE_CARE_DELAY_CONTEXT_RE.search(t)
            if snooze_matched:
                return {
                    "intent": "ACTIVE_CARE_SNOOZE",
                    "confidence": 0.92,
                    "slots": {},
                    "raw": "[RULE]",
                }
            if context_matched and _RULE_ACTIVE_CARE_SNOOZE_VERB_RE.search(t):
                return {
                    "intent": "ACTIVE_CARE_SNOOZE",
                    "confidence": 0.90,
                    "slots": {},
                    "raw": "[RULE]",
                }

    if (
        "CLEAR_MEMORY" in candidates
        and _is_explicit_clear_memory_command(t)
        and not _RULE_PERSONA_WORD_RE.search(t) # [FIX] 避免"修改人设"误触发"重置记忆"
    ):
        return {
            "intent": "CLEAR_MEMORY",
            "confidence": 0.97,
            "slots": {},
            "raw": "[RULE]",
        }

    # 人设切换
    if "SWITCH_PERSONA" in candidates:
        # [Optimization] 增加对"改"、"修改"等动词的支持，并放宽条件
        persona_verbs = re.compile(r"(切换|换|切|变|改|修改|调整|恢复|回|设为|设置为|变成)", re.IGNORECASE)
        
        if _RULE_PERSONA_WORD_RE.search(t) and persona_verbs.search(t):
            persona_name = ""
            # 尝试提取
            m = re.search(
                r"(?:换成|切到|变成|恢复|到|为|是|做)([^，。！？\n]{1,10})(?:人设|性格|角色|设定|风格|模式)?",
                t,
            )
            if m:
                persona_name = m.group(1).strip()
            # 如果没提取到，可能就在动词后面
            if not persona_name:
                 m2 = re.search(r"(?:改|修改|调整|换|变)[^，。！？\n]{0,2}(?:人设|性格|角色|设定)(?:为|成)?([^，。！？\n]{1,10})", t)
                 if m2:
                     persona_name = m2.group(1).strip()

            return {
                "intent": "SWITCH_PERSONA",
                "confidence": 0.95,  # 提高置信度
                "slots": {"persona_name": persona_name},
                "raw": "[RULE]",
            }

    if "SHOW_STATUS" in candidates:
        if _RULE_SYSTEM_ANCHOR_RE.search(t) and _has_explicit_command_tone(t) and (
            _RULE_STATUS_QUERY_RE.search(t)
            or re.search(r"(看下|查看|显示).{0,8}(状态|负载)", t, re.IGNORECASE)
        ):
            return {
                "intent": "SHOW_STATUS",
                "confidence": 0.92,
                "slots": {},
                "raw": "[RULE]",
            }

    has_any_system_signal = bool(
        _RULE_SYSTEM_ANCHOR_RE.search(t)
        or _RULE_HELP_RE.search(t)
        or (_RULE_MODEL_WORD_RE.search(t) and _RULE_LIST_VERBS_RE.search(t))
        or (_RULE_VOICE_WORD_RE.search(t) and _RULE_LIST_VERBS_RE.search(t))
        or (
            _RULE_LATENCY_WORD_RE.search(t)
            and (_RULE_ON_RE.search(t) or _RULE_OFF_RE.search(t))
        )
        or (_RULE_CLEAR_VERBS_RE.search(t) and _RULE_MEMORY_OBJ_RE.search(t))
        or (
            _RULE_SWITCH_VERBS_RE.search(t)
            and (_RULE_MODEL_WORD_RE.search(t) or _RULE_PERSONA_WORD_RE.search(t))
        )
    )

    if "NONE" in candidates and not has_any_system_signal:
        if _RULE_NARRATIVE_PREFIX_RE.search(t):
            return {"intent": "NONE", "confidence": 0.97, "slots": {}, "raw": "[RULE]"}
        if re.search(r"^(我|你|他|她|它)", t, re.IGNORECASE):
            return {"intent": "NONE", "confidence": 0.96, "slots": {}, "raw": "[RULE]"}
        if re.search(
            r"(不喜欢|讨厌|喜欢|爱|变了|想你|表白|在一起|累了|困了|烦|无聊|开心|难过|生气|焦虑|郁闷|emo|心情|感觉|觉得)",
            t
        ) and not _RULE_SWITCH_VERBS_RE.search(t):
            return {"intent": "NONE", "confidence": 0.98, "slots": {}, "raw": "[RULE]"}

        if _RULE_NEGATIVE_STATUS_RE.search(t) and "状态" in t:
            return {"intent": "NONE", "confidence": 0.97, "slots": {}, "raw": "[RULE]"}
        if (
            _RULE_VOICE_WORD_RE.search(t)
            and not _RULE_LIST_VERBS_RE.search(t)
            and not _RULE_SWITCH_VERBS_RE.search(t)
        ):
            return {"intent": "NONE", "confidence": 0.93, "slots": {}, "raw": "[RULE]"}
        # 如果既不是系统指令，也不是明确的 NONE 场景，则返回 None 触发模型识别
        return None

    if (
        "NONE" in candidates
        and "系统" in t
        and _RULE_PRAISE_RE.search(t)
        and not _RULE_STATUS_QUERY_RE.search(t)
    ):
        return {"intent": "NONE", "confidence": 0.93, "slots": {}, "raw": "[RULE]"}

    return None


def _apply_regex_rules(t: str, candidates: List[str]) -> Optional[Dict[str, Any]]:
    return rule_classify_intent(t, candidates)


def _parse_delay_seconds_from_text(text: str) -> int:
    raw = str(text or "").strip().lower()
    if not raw:
        return 0

    if "半小时" in raw:
        return 1800

    zh_num_map = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }

    def _zh_to_int(token: str) -> int:
        s = str(token or "").strip()
        if not s:
            return 0
        if s in zh_num_map:
            return zh_num_map[s]
        if "十" in s:
            if s == "十":
                return 10
            if s.startswith("十"):
                return 10 + zh_num_map.get(s[1:], 0)
            if s.endswith("十"):
                return zh_num_map.get(s[0], 0) * 10
            parts = s.split("十", 1)
            return zh_num_map.get(parts[0], 0) * 10 + zh_num_map.get(parts[1], 0)
        return 0

    m_digit = re.search(r"(\d{1,3})\s*(小时|分钟|分|min|mins|minute|minutes|h|hr|hrs)", raw, re.IGNORECASE)
    if m_digit:
        val = int(m_digit.group(1))
        unit = str(m_digit.group(2) or "").lower()
        if unit in {"小时", "h", "hr", "hrs"}:
            return max(60, min(val * 3600, 24 * 3600))
        return max(60, min(val * 60, 24 * 3600))

    m_zh = re.search(r"([一二两三四五六七八九十]{1,3})\s*个?\s*(小时|分钟|分)", raw)
    if m_zh:
        val = _zh_to_int(str(m_zh.group(1)))
        unit = str(m_zh.group(2) or "")
        if val > 0:
            if unit == "小时":
                return max(60, min(val * 3600, 24 * 3600))
            return max(60, min(val * 60, 24 * 3600))

    if any(k in raw for k in ["等会", "一会", "过会", "过一会", "稍后", "晚点"]):
        return 1800
    return 0


def normalize_slots(intent: str, slots_obj: Any, raw_text: str = "") -> Dict[str, Any]:
    slots = slots_obj if isinstance(slots_obj, dict) else {}
    out: Dict[str, Any] = {}

    intent_upper = str(intent or "").strip().upper()
    if intent_upper == "SWITCH_MODEL":
        model_name = str(slots.get("model_name") or slots.get("model") or "").strip()
        if model_name:
            out["model_name"] = model_name
    elif intent_upper == "SWITCH_PERSONA":
        p_name = str(slots.get("persona_name") or slots.get("persona") or "").strip()
        if p_name:
            # 移除常见的后缀
            p_name = re.sub(r"(模式|人设|性格|角色|设定|风格)$", "", p_name)
            out["persona_name"] = p_name
        else:
            # 如果slots为空，尝试从raw text中提取
            # 这里需要上下文，但normalize_slots没有传入text
            # 暂时只能依赖前面的规则提取
            pass
    elif intent_upper == "TOGGLE_LATENCY":
        state = str(slots.get("state") or slots.get("mode") or "").strip().lower()
        if state in ("on", "off"):
            out["state"] = state
    elif intent_upper == "IMAGE_GEN":
        prompt = str(
            slots.get("prompt") or slots.get("text") or slots.get("content") or ""
        ).strip()
        if prompt:
            out["prompt"] = prompt
    elif intent_upper == "REMINDER":
        out["time"] = str(slots.get("time") or "").strip()
        out["event"] = str(slots.get("event") or "").strip()
    elif intent_upper == "SEARCH":
        out["query"] = str(slots.get("query") or slots.get("keyword") or "").strip()
    elif intent_upper == "ACTIVE_CARE_SNOOZE":
        delay_seconds = _parse_delay_seconds_from_text(raw_text)
        if delay_seconds > 0:
            out["delay_seconds"] = delay_seconds
    elif intent_upper == "SET_REMINDER":
        # 提取时间和提醒内容
        # 匹配 "X点提醒我Y" 或 "晚上X点提醒我Y" 等模式
        time_patterns = [
            r"(\d{1,2})[点时:：](\d{0,2})?\s*提醒[我你]?[，,]?\s*(.+)",
            r"(晚上|早上|下午|中午|傍晚|凌晨)(\d{1,2})[点时:：]?(\d{0,2})?\s*提醒[我你]?[，,]?\s*(.+)",
            r"提醒[我你]?[，,]?\s*(.+?)[，,]?\s*(\d{1,2})[点时:：](\d{0,2})?",
            r"(\d+)分钟[后之]提醒[我你]?[，,]?\s*(.+)",
            r"(\d+)小时[后之]提醒[我你]?[，,]?\s*(.+)",
        ]
        for pattern in time_patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if "分钟" in raw_text or "小时" in raw_text:
                    # 相对时间
                    if "分钟" in raw_text:
                        out["minutes"] = float(groups[0]) if groups[0] else 0
                    else:
                        out["minutes"] = float(groups[0]) * 60 if groups[0] else 0
                    out["message"] = groups[-1] if groups[-1] else ""
                else:
                    # 绝对时间
                    time_period = groups[0] if groups[0] and groups[0] in ["晚上", "早上", "下午", "中午", "傍晚", "凌晨"] else ""
                    hour = int(groups[1]) if len(groups) > 1 and groups[1] else 0
                    minute = int(groups[2]) if len(groups) > 2 and groups[2] else 0
                    message = groups[-1] if groups[-1] else ""
                    
                    # 转换为相对时间（简化处理）
                    import time as tm
                    now = tm.localtime()
                    current_hour = now.tm_hour
                    current_min = now.tm_min
                    
                    # 根据时间段调整小时
                    if time_period == "晚上":
                        if hour < 12:
                            hour += 12
                    elif time_period == "下午":
                        if hour < 12:
                            hour += 12
                    elif time_period in ["早上", "上午"]:
                        if hour >= 12:
                            hour -= 12
                    elif time_period == "凌晨":
                        pass  # 凌晨就是凌晨
                    
                    # 计算分钟差
                    target_minutes = hour * 60 + minute
                    current_minutes = current_hour * 60 + current_min
                    diff = target_minutes - current_minutes
                    if diff < 0:
                        diff += 24 * 60  # 第二天
                    out["minutes"] = diff
                    out["message"] = message
                break
        
        # 如果没有匹配到时间模式，尝试提取提醒内容
        if "message" not in out:
            content_match = re.search(r"提醒[我你]?[，,]?\s*(.+)", raw_text, re.IGNORECASE)
            if content_match:
                out["message"] = content_match.group(1).strip()
                out["minutes"] = 30  # 默认30分钟后

    return out




async def classify_intent(
    text: str,
    candidates: Optional[List[str]] = None,
    model_path: Optional[str] = None,
    temperature: float = 0.0,
    top_p: float = 0.9,
    max_tokens: int = 96,
) -> Dict[str, Any]:
    if not text:
        return {"intent": "NONE", "confidence": 0.0, "slots": {}}

    if not candidates:
        candidates = [
            "CLEAR_MEMORY",
            "SHOW_STATUS",
            "SHOW_HELP",
            "LIST_MODELS",
            "LIST_VOICES",
            "SWITCH_MODEL",
            "SWITCH_MODEL_HINT",
            "SWITCH_PERSONA",
            "TOGGLE_LATENCY",
            "ACTIVE_CARE_SNOOZE",
            "IMAGE_GEN",
            "NONE",
        ]
    candidates = [str(x).strip() for x in candidates if str(x).strip()]
    if "NONE" not in candidates:
        candidates.append("NONE")

    # 1. 规则匹配（产生信号，不短路）
    rule_result = rule_classify_intent(text, candidates)
    rule_intent = None
    rule_confidence = 0.0
    rule_slots = {}
    if isinstance(rule_result, dict):
        rule_intent = str(rule_result.get("intent") or "NONE").strip().upper() or "NONE"
        rule_confidence = float(rule_result.get("confidence") or 0.0)
        rule_slots = (
            rule_result.get("slots")
            if isinstance(rule_result.get("slots"), dict)
            else {}
        )

    # 2. BERT 语义分析
    bert_intent = "NONE"
    bert_confidence = 0.0
    bert_available = False
    try:
        analyzer = await asyncio.to_thread(get_bert_analyzer)
        loop = asyncio.get_running_loop()
        analysis = await asyncio.wait_for(
            loop.run_in_executor(None, analyzer.analyze_intent, text, candidates),
            timeout=10.0,
        )
        bert_intent = str(analysis.get("intent", "NONE") or "NONE").upper()
        bert_confidence = float(analysis.get("confidence", 0.0))
        bert_available = True
    except asyncio.TimeoutError:
        logger.warning("BERT intent analysis timed out (10s)")
    except Exception as e:
        logger.error(f"BERT intent analysis failed: {e}")

    # 3. 信号融合裁决
    # 规则层和 BERT 都同意 → 高置信度返回
    # 规则层命中但 BERT 否决 → 降级为 NONE
    # BERT 单独命中 → 安全守卫检查后返回
    # 都没命中 → NONE
    # BERT 不可用时，规则层结果降权但不被否决

    if rule_intent and rule_intent != "NONE" and rule_confidence > 0:
        if not bert_available:
            return {
                "intent": rule_intent,
                "confidence": rule_confidence * 0.6,
                "slots": normalize_slots(rule_intent, rule_slots, text),
                "raw": "[FUSION_RULE_ONLY_BERT_UNAVAILABLE]",
            }
        if bert_intent == "NONE" and bert_confidence < 0.5:
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "slots": {},
                "raw": "[FUSION_RULE_VETOED_BY_BERT]",
            }
        if bert_intent != rule_intent and bert_confidence > 0.6:
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "slots": {},
                "raw": "[FUSION_RULE_BERT_DISAGREE]",
            }
        fused_confidence = min(rule_confidence * 0.6 + bert_confidence * 0.4, 1.0) if bert_intent == rule_intent else rule_confidence * 0.5
        return {
            "intent": rule_intent,
            "confidence": fused_confidence,
            "slots": normalize_slots(rule_intent, rule_slots, text),
            "raw": "[FUSION_RULE_PRIMARY]",
        }

    if bert_intent != "NONE" and bert_confidence > 0.75:
        if bert_intent in ("CLEAR_MEMORY", "CLEAR_LOCAL_MEMORY") and not _is_explicit_clear_memory_command(text):
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "slots": {},
                "raw": "[BERT_GUARD]"
            }
        if bert_intent in ("TOGGLE_LATENCY", "SHOW_STATUS", "TOGGLE_REPLY_MODE") and not _has_explicit_command_tone(text):
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "slots": {},
                "raw": "[BERT_GUARD]"
            }
        if bert_intent in ("SWITCH_MODEL", "SWITCH_MODEL_HINT", "LIST_MODELS", "LIST_VOICES") and not _has_explicit_command_tone(text):
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "slots": {},
                "raw": "[BERT_GUARD]"
            }
        if bert_intent == "ACTIVE_CARE_SNOOZE" and not _has_explicit_snooze_tone(text):
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "slots": {},
                "raw": "[BERT_GUARD]"
            }
        if bert_intent == "IMAGE_GEN" and _RULE_IMAGE_GEN_NEGATIVE_RE.search(text):
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "slots": {},
                "raw": "[BERT_GUARD_IMAGE_GEN]"
            }
        return {
            "intent": bert_intent,
            "confidence": bert_confidence,
            "slots": normalize_slots(bert_intent, {}, text),
            "raw": "[FUSION_BERT_PRIMARY]",
        }

    return {
        "intent": "NONE",
        "confidence": 0.0,
        "slots": {},
        "raw": "[FUSION_NONE]"
    }

