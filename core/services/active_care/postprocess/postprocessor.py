"""
后处理模块
从 executor 中提取，负责 LLM 输出的后处理管线：
- 推理段剥离
- Emoji 剥离
- 语言处理（英文重写）
- 语义去重（委托 Deduplicator）
- 睡眠净化（委托 SleepSanitizer）
- Prompt/推理泄露检测（委托 LeakDetector）
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger, get_module_logger
from core.utils.config_accessor import get_active_care_config
from core.services.active_care.postprocess.sleep_sanitizer import SleepSanitizer
from core.services.active_care.postprocess.deduplicator import Deduplicator
from core.services.active_care.postprocess.leak_detector import LeakDetector

logger = get_logger("ACTIVE_CARE_POSTPROCESSOR")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")

# 短句关怀类 sys_prompt_type：天然容易与历史重复（"晚安""早安"等），
# 去重会误杀这类必要的一次性关怀，因此跳过整句去重和句子级部分包含检测，
# 仅保留后续的睡眠净化和泄露检测。
_DEDUP_BYPASS_SYS_PROMPT_TYPES = frozenset(
    {"goodnight_proactive", "good_morning_proactive", "sleep_again_proactive"}
)


@dataclass
class PostprocessContext:
    """后处理管线上下文，封装 postprocess 方法的参数"""
    target_conversation_id: str = ""
    preferred_language: str = "auto"
    repeat_anchors: List[str] = field(default_factory=list)
    last_user_message: str = ""
    last_proactive_assistant_message: str = ""
    sleep_session_active: bool = False
    sleep_confirmed_by_silence: bool = False
    known_sleep_time: str = ""
    now_ts: float = 0.0
    # P2-1: sys_prompt_type 移入 ctx，供 pipeline step 使用
    sys_prompt_type: str = ""




class LanguageHandler:
    @staticmethod
    def is_mostly_cjk(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", raw))
        latin_count = len(re.findall(r"[A-Za-z]", raw))
        return cjk_count >= max(6, latin_count * 2)

    @staticmethod
    def infer_preferred_language(history_msgs: List[Dict[str, Any]]) -> str:
        user_texts: List[str] = []
        for item in reversed(history_msgs):
            role = str(item.get("role") or "").strip().lower()
            if role == "user":
                text = str(item.get("content") or "").strip()
                if text:
                    user_texts.append(text)
                if len(user_texts) >= 4:
                    break
        if not user_texts:
            for item in reversed(history_msgs):
                text = str(item.get("content") or "").strip()
                if text:
                    user_texts.append(text)
                    break
        if not user_texts:
            return "zh"
        en_votes = 0
        zh_votes = 0
        for candidate_text in user_texts:
            en_count = len(re.findall(r"[A-Za-z]", candidate_text))
            zh_count = len(re.findall(r"[\u4e00-\u9fff]", candidate_text))
            if en_count >= max(8, zh_count * 2):
                en_votes += 1
            elif zh_count >= max(4, en_count):
                zh_votes += 1
        if en_votes > 0 and en_votes >= zh_votes:
            return "en"
        if zh_votes > 0 and zh_votes > en_votes:
            return "zh"
        return "zh"

    @staticmethod
    async def rewrite_to_english_if_needed(
        *,
        agent: Any,
        target_conversation_id: str,
        text: str,
        preferred_language: str,
    ) -> str:
        if str(preferred_language or "").strip().lower() != "en":
            return text
        if not LanguageHandler.is_mostly_cjk(text):
            return text
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
            ENGLISH_REWRITE_PROMPT_TEMPLATE,
            ENGLISH_REWRITE_SYSTEM_PROMPT,
        )
        rewrite_prompt = ENGLISH_REWRITE_PROMPT_TEMPLATE.format(text=text)
        rewrite_system = ENGLISH_REWRITE_SYSTEM_PROMPT
        try:
            rewrite_resp = await agent.handle_message(
                user_id=target_conversation_id,
                message=rewrite_prompt,
                system_prompt_override=rewrite_system,
                save_history=False,
            )
            rewritten = (
                rewrite_resp.get("content", "")
                if isinstance(rewrite_resp, dict)
                else str(rewrite_resp)
            )
            rewritten = str(rewritten or "").strip()
            if rewritten:
                return rewritten
        except Exception as e:
            logger.warning(f"Active Care: English rewrite failed: {e}")
        return text

    @staticmethod
    def build_english_fallback(original_text: str, last_user_message: str) -> str:
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import ENGLISH_FALLBACK_TEMPLATES
        anchor = str(last_user_message or "").strip()
        if len(anchor) > 90:
            anchor = anchor[:90] + "..."
        if anchor:
            return ENGLISH_FALLBACK_TEMPLATES[0].format(anchor=anchor)
        cleaned = str(original_text or "").strip()
        if len(cleaned) > 80:
            cleaned = cleaned[:80] + "..."
        if cleaned:
            return ENGLISH_FALLBACK_TEMPLATES[1].format(cleaned=cleaned)
        return ENGLISH_FALLBACK_TEMPLATES[2]




class ActiveCarePostprocessor:
    def __init__(self):
        self.sleep_sanitizer = SleepSanitizer()
        self.deduplicator = Deduplicator()
        self.language_handler = LanguageHandler()
        self.leak_detector = LeakDetector()

    @staticmethod
    def strip_reasoning_segments(text: str) -> str:
        cleaned = re.sub(r"<think.*?</think\s*>", "", str(text or ""), flags=re.DOTALL)
        # MiniMax-M2.5推理：使用<think\>...</think\>标签。
        # 当API返回空内容但有reasoning_content时，
        # OpenAI客户端会回退到将推理作为原始文本返回。
        # 这意味着整个输出是纯推理，没有实际消息。
        # 剥离配对的<think\>...</think\>块
        cleaned = re.sub(r"<think>.*?</think\s*>", "", cleaned, flags=re.DOTALL)
        # 已禁用：剥离未闭合<think\>块的逻辑 - 曾错误删除实际内容
        # MiniMax-M2.5可能输出：reasoning``actual content``
        # open_think_idx = cleaned.find("<think>")
        # if open_think_idx >= 0:
        #     cleaned = cleaned[:open_think_idx]
        cleaned = re.sub(r"</think\s*>", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(
            r"(?:>\s*\*\*)?(?:Thinking Process|思考过程)\s*:?(?:\*\*)?.*?(?=\n\n|\Z)",
            "",
            cleaned,
            flags=re.DOTALL,
        ).strip()
        cleaned = re.sub(r"^\d+[.、．)\s]+\s*", "", cleaned, flags=re.MULTILINE)

        # 剥离 [TOOL_CALL]...[/TOOL_CALL] 格式
        # MiniMax-M2.5 等模型有时在 content 中输出工具调用格式而非纯文本
        # 格式示例: [TOOL_CALL]{tool => "精灵文字回复", args => {--text "实际消息" --reply true}}[/TOOL_CALL]
        cleaned = ActiveCarePostprocessor._strip_tool_call_segments(cleaned)

        return cleaned

    @staticmethod
    def _strip_tool_call_segments(text: str) -> str:
        """剥离 [TOOL_CALL]...[/TOOL_CALL] 格式，尝试提取其中的实际文本"""
        if "[TOOL_CALL]" not in text and "[/TOOL_CALL]" not in text:
            return text

        # 尝试从 TOOL_CALL 中提取 --text 参数的内容
        extracted_texts = []
        tool_call_pattern = re.compile(
            r"\[TOOL_CALL\](.*?)\[/TOOL_CALL\]", re.DOTALL
        )
        for m in tool_call_pattern.finditer(text):
            body = m.group(1)
            # 尝试提取 --text "..." 或 --text '...' 中的内容
            text_match = re.search(r'--text\s+["\u201c](.+?)["\u201d]', body, re.DOTALL)
            if text_match:
                extracted_texts.append(text_match.group(1).strip())

        # 移除所有 TOOL_CALL 块
        cleaned = tool_call_pattern.sub("", text).strip()

        # 如果提取到了文本，用提取的文本替代
        if extracted_texts:
            return " ".join(extracted_texts)

        # 如果没有提取到文本但还有残留，整体视为泄漏
        return cleaned

    @staticmethod
    def _strip_emoji_markers(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return raw
        cleaned = re.sub(r"\s*🔹\s*", "", raw)
        return cleaned.strip()

    @staticmethod
    def _strip_all_emojis(text: str) -> str:
        """剥离所有emoji字符"""
        raw = str(text or "").strip()
        if not raw:
            return raw
        # 匹配所有emoji范围（不包含中文字符）
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # 表情符号
            "\U0001F300-\U0001F5FF"  # 符号和象形文字
            "\U0001F680-\U0001F6FF"  # 交通和地图符号
            "\U0001F1E0-\U0001F1FF"  # 旗帜
            "\U0001F900-\U0001F9FF"  # 补充符号
            "\U0001FA00-\U0001FA6F"  # 棋子符号
            "\U0001FA70-\U0001FAFF"  # 符号和象形文字扩展
            "\U00002702-\U000027B0"  # 杂项符号
            "\U0000FE00-\U0000FE0F"  # 变体选择符
            "\U0000200D"             # 零宽连接符
            "\U00002600-\U000026FF"  # 杂项符号
            "\U00002700-\U000027BF"  # 装饰符号
            "\U0000231A-\U0000231B"  # 手表和沙漏
            "\U000023E9-\U000023F3"  # 媒体控制符号
            "\U000023F8-\U000023FA"  # 媒体控制符号
            "\U000025AA-\U000025AB"  # 方块
            "\U000025B6"             # 播放按钮
            "\U000025C0"             # 倒退按钮
            "\U000025FB-\U000025FE"  # 方块
            "\U00002614-\U00002615"  # 伞和咖啡
            "\U00002648-\U00002653"  # 星座符号
            "\U0000267F"             # 轮椅符号
            "\U00002934-\U00002935"  # 箭头
            "\U00002B05-\U00002B07"  # 箭头
            "\U00002B1B-\U00002B1C"  # 方块
            "\U00002B50"             # 星星
            "\U00002B55"             # 圆圈
            "\U00003030"             # 波浪破折号
            "\U0000303D"             # 部分替代标记
            "\U00003297"             # 祝贺
            "\U00003299"             # 秘密
            "]+",
            flags=re.UNICODE,
        )
        cleaned = emoji_pattern.sub("", raw)
        # 清理多余的空格
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _strip_cute_symbols_and_monologue(text: str) -> str:
        """过滤软萌符号和内心独白（风格红线硬过滤）

        Aveline 人设绝不使用～♪☆♡等软萌符号，也不输出内心独白。
        这些是风格红线，必须硬过滤，不能只靠 prompt 约束。
        """
        result = str(text or "").strip()
        if not result:
            return result
        # 移除内心独白：（心想：...）或（心里想：...）或（想着：...）
        result = re.sub(r"[（(]\s*(?:心想|心里想|想着|暗想|心说)\s*[:：]?.*?[）)]", "", result)
        # 移除软萌符号：～♪☆♡✧✨💕💗💖❤👉👈🥺👉
        result = re.sub(r"[～♪☆♡✧✨💕💗💖❤🥺👉←→]", "", result)
        # 移除句末波浪号（ASCII ~ 和全角 ～）
        result = re.sub(r"[~～]+$", "", result)
        # 移除句中软萌语气词（呀～、呢～、哦～、嘛～、哇～）
        result = re.sub(r"[呀呢哦嘛哇啊啦][~～]", "", result)
        # 清理多余空格
        result = re.sub(r"\s+", " ", result).strip()
        return result

    async def postprocess(
        self,
        *,
        response: Any,
        agent: Any,
        aveline_service: Any,
        sys_prompt_type: str = "",
        target_conversation_id: str = "",
        preferred_language: str = "auto",
        repeat_anchors: Optional[List[str]] = None,
        last_user_message: str = "",
        last_proactive_assistant_message: str = "",
        sleep_session_active: bool = False,
        sleep_confirmed_by_silence: bool = False,
        known_sleep_time: str = "",
        now_ts: float = 0.0,
        ctx: Optional[PostprocessContext] = None,
    ) -> Optional[Dict[str, Any]]:
        """后处理管线入口

        支持两种调用方式：
        1. 旧接口：逐个传参（向后兼容）
        2. 新接口：传入 PostprocessContext 对象（推荐）

        P2-1: 实际处理逻辑已拆分到 pipeline.py 的 step 中，
              本方法仅负责组装上下文并调用 run_pipeline。
        """
        # 统一上下文：优先使用 ctx，缺失字段用参数补齐
        if ctx is None:
            ctx = PostprocessContext(
                target_conversation_id=target_conversation_id,
                preferred_language=preferred_language,
                repeat_anchors=repeat_anchors or [],
                last_user_message=last_user_message,
                last_proactive_assistant_message=last_proactive_assistant_message,
                sleep_session_active=sleep_session_active,
                sleep_confirmed_by_silence=sleep_confirmed_by_silence,
                known_sleep_time=known_sleep_time,
                now_ts=now_ts,
                sys_prompt_type=sys_prompt_type,
            )
        else:
            # ctx 模式下也允许显式参数覆盖（向后兼容旧调用）
            if not ctx.sys_prompt_type and sys_prompt_type:
                ctx.sys_prompt_type = sys_prompt_type

        # 组装依赖
        from core.services.active_care.postprocess.pipeline import (
            PipelineDependencies,
            run_pipeline,
        )

        deps = PipelineDependencies(
            language_handler=self.language_handler,
            deduplicator=self.deduplicator,
            sleep_sanitizer=self.sleep_sanitizer,
            leak_detector=self.leak_detector,
            postprocessor=self,
            agent=agent,
            aveline_service=aveline_service,
        )

        return await run_pipeline(
            response=response,
            ctx=ctx,
            deps=deps,
        )

    async def _regenerate_non_repetitive_text(
        self,
        *,
        aveline_service: Any,
        target_conversation_id: str,
        candidate_text: str,
        previous_proactive_message: str,
        last_user_message: str,
        preferred_language: str,
        sys_prompt_type: str = "",
    ) -> str:
        candidate = str(candidate_text or "").strip()
        previous = str(previous_proactive_message or "").strip()
        if not candidate or not previous:
            return ""
        user_anchor = str(last_user_message or "").strip()
        if len(user_anchor) > 120:
            user_anchor = user_anchor[:120] + "..."
        if len(previous) > 160:
            previous = previous[:160] + "..."
        if len(candidate) > 160:
            candidate = candidate[:160] + "..."
        language = str(preferred_language or "").strip().lower()
        if language == "en":
            rewrite_patch = (
                "Rewrite the proactive line to avoid repeating the previous proactive message.\n"
                "Keep one natural sentence only, no JSON, no explanation.\n"
                "Must continue from user's latest topic if available.\n"
            )
            if user_anchor:
                rewrite_patch += f"Latest user topic: {user_anchor}\n"
            rewrite_patch += (
                f"Previous proactive message: {previous}\n"
                f"Current candidate: {candidate}\n"
            )
        else:
            rewrite_patch = (
                "请把这条主动消息改写成\u201c非复读版本\u201d。\n"
                "只输出一句自然中文，不要JSON、不要解释。\n"
                "必须避免与上一条主动消息同义。\n"
                "优先衔接用户最近话题，不要突然切题。\n"
            )
            if str(sys_prompt_type or "").strip().lower() == "reminder":
                rewrite_patch += "这是任务提醒场景，可以保留任务核心词，但必须换切入点、换句式，并补一点新的提醒信息。\n"
            if user_anchor:
                rewrite_patch += f"用户最近话题：{user_anchor}\n"
            rewrite_patch += (
                f"上一条主动消息：{previous}\n"
                f"当前候选消息：{candidate}\n"
            )
        try:
            model_hint = ""
            try:
                from config.integrated_config import get_settings
                settings = get_settings()
                model_hint = str(
                    get_active_care_config("active_care_model_hint", default="", settings=settings)
                ).strip()
            except Exception:
                pass
            rewritten = await aveline_service.execute_prompt_patch(
                conversation_id=target_conversation_id,
                content="[ACTIVE_CARE_REWRITE_NON_REPETITIVE]",
                prompt_patch=rewrite_patch,
                save_history=False,
                model_hint=model_hint,
            )
        except Exception:
            return ""
        rewritten_text = (
            rewritten.get("content", "")
            if isinstance(rewritten, dict)
            else str(rewritten)
        )
        return str(rewritten_text or "").strip()
