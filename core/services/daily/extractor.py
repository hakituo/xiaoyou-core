import re
import asyncio
from memory.core.discourse import analyze_discourse, infer_state_event
from core.services.daily.manager import get_daily_manager
from core.services.daily.correction import (
    apply_fast_correction as apply_daily_fast_correction,
    apply_semantic_correction as apply_daily_semantic_correction,
    extract_time_hhmm,
    has_correction_intent,
    _extract_all_times,
    _parse_sleep_wakeup_correction,
)
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("ACTIVITY_EXTRACTOR")


class ActivityExtractor:
    """
    智能活动提取器。
    基于规则与 BERT 语义识别，从用户对话中提取结构化生活细节。
    """

    def __init__(self):
        self.manager = get_daily_manager()
        self._last_record_source = ""
        self._bert_runtime_available = None
        # UIE 提取器（懒加载，避免初始化时阻塞）
        self._uie_extractor = None
        self._uie_available: bool | None = None

    def _get_uie_extractor(self):
        """懒加载 UIE 提取器单例。

        UIE 后端不可用时返回 None，调用方需自行回退到正则。
        """
        if self._uie_available is False:
            return None
        if self._uie_extractor is not None:
            return self._uie_extractor
        try:
            from core.services.data_ops.uie_extractor import get_uie_extractor

            extractor = get_uie_extractor()
            if not extractor._backend:
                self._uie_available = False
                return None
            self._uie_extractor = extractor
            self._uie_available = True
            return extractor
        except Exception as e:
            logger.debug(f"UIE初始化失败，将回退正则提取: {e}")
            self._uie_available = False
            return None

    async def _uie_extract_async(
        self,
        text: str,
        schema: list[str] | None = None,
    ) -> dict:
        """异步调用 UIE 提取（同步 UIE 用 run_in_executor 包装）。

        返回原始结果，字段名为 schema 中的中文 key。
        每个 key 对应一个 list，元素结构 {"text": "...", "probability": float, ...}。
        """
        extractor = self._get_uie_extractor()
        if extractor is None:
            return {}
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: extractor.extract(text, schema),
            )
        except Exception as e:
            logger.debug(f"UIE提取失败: {e}")
            return {}

    def _uie_time_to_hhmm(
        self,
        uie_time: str,
        raw: str,
        is_sleep: bool,
    ) -> str | None:
        """把 UIE 提取的时间文本转为 HH:MM。

        UIE 提取的可能是"7点"、"7点半"、"晚上11点"等。
        若 UIE 文本本身含上下午关键词，extract_time_hhmm 会处理；
        否则结合 raw 上下文推断上下午（睡→晚上，起→早上）。
        """
        if not uie_time:
            return None
        # 检查 UIE 文本本身是否含上下午关键词
        uie_has_period = bool(
            re.search(r"(早上|早晨|清晨|上午|凌晨|晚上|晚|夜里|夜间|夜晚|傍晚|深夜|半夜)", uie_time)
        )
        if uie_has_period:
            # UIE 文本本身有上下午信息，直接解析
            return extract_time_hhmm(uie_time) or None
        # UIE 文本无上下午信息，从 raw 推断后拼接再解析
        is_pm = bool(re.search(r"(晚上|晚|夜里|夜间|夜晚|傍晚|深夜|半夜|昨晚|今晚)", raw))
        is_am = bool(re.search(r"(早上|早晨|清晨|上午|凌晨|今早|今晨)", raw))
        combined = uie_time
        if is_pm:
            combined = "晚上" + combined
        elif is_am:
            combined = "早上" + combined
        elif is_sleep:
            # 睡觉时间默认推断为晚上
            combined = "晚上" + combined
        return extract_time_hhmm(combined) or None

    def _augment_text_with_time(self, text: str, intent: str) -> str:
        """为无时间表述的文本拼接当前时间（提升 UIE 提取成功率）。

        例如："我醒了" → "早上7点20分我醒了"（当前是早上7:20）
        例如："准备睡了" → "晚上11点准备睡了"（当前是晚上11:00）

        Args:
            text: 原始文本
            intent: 当前意图（RECORD_WAKEUP/RECORD_SLEEP 等）

        Returns:
            拼接时间后的文本（如果原文本已有时间表述，不拼接）
        """
        # 检查是否已有时间表述
        has_time = bool(
            re.search(
                r"([01]?\d|2[0-3])[:：]([0-5]?\d)|"
                r"[零一二三四五六七八九十两\d]+\s*点",
                text,
            )
        )
        if has_time:
            return text  # 已有时间，不拼接

        # 只为起床/睡觉意图拼接时间（其他意图不需要）
        if intent not in ("RECORD_WAKEUP", "RECORD_SLEEP"):
            return text

        # 获取当前时间
        from core.utils.time_utils import get_time_period, get_current_time
        now = get_current_time()
        time_period = get_time_period()

        # 拼接时间表述
        # 中文小时表述："7点" 或 "11点"
        hour_cn = str(now.hour)
        minute_cn = ""
        if now.minute > 0:
            # 分钟表述："20" → "20分"，"30" → "半"
            if now.minute == 30:
                minute_cn = "半"
            else:
                minute_cn = f"{now.minute}分"

        time_prefix = f"{time_period}{hour_cn}点{minute_cn}"
        return f"{time_prefix}{text}"

    def _has_record_intent(self, text: str) -> bool:
        raw = str(text or "").strip().lower()
        if not raw:
            return False
        return bool(
            re.search(
                r"(记录一下|记一下|帮我记|记一条|补录|补记|登记一下|"
                r"记到状态|记录到状态|更新状态)",
                raw,
                re.IGNORECASE,
            )
        )

    def _has_correction_intent(self, text: str) -> bool:
        return has_correction_intent(text)

    def _apply_fast_correction(self, text: str) -> bool:
        changed = apply_daily_fast_correction(text, self.manager)
        if changed:
            self._last_record_source = "fast_correction"
        return changed

    def _extract_meal_content(self, text: str) -> str:
        raw = str(text or "").strip()
        m = re.search(r"(?:吃了|喝了)([^，。！？,\n]{1,18})", raw)
        if m:
            return str(m.group(1) or "").strip()
        return "已吃"

    def _extract_study_payload(self, text: str):
        raw = str(text or "").strip()
        m = re.search(
            r"(?:学了|复习了|刷了|背了|看了|做了)\s*([^，。！？,\n]{1,24})", raw
        )
        topic = str(m.group(1) or "").strip() if m else ""
        if not topic:
            study_keywords = [
                "英语", "单词", "数学", "高数", "物理", "化学",
                "编程", "算法", "作业", "论文", "阅读"
            ]
            for kw in study_keywords:
                if kw in raw:
                    topic = kw
                    break
        if not topic:
            topic = "学习"
        return topic, raw[:80]

    def _extract_activity_content(self, text: str) -> str:
        raw = str(text or "").strip()
        m = re.search(r"(?:在|去|刚)([^，。！？,\n]{1,20})", raw)
        if m:
            return str(m.group(1) or "").strip()
        return raw[:50] or "活动"

    def _extract_health_symptom(self, text: str) -> str:
        raw = str(text or "").strip()
        health_keywords = [
            "头痛", "头疼", "发烧", "咳嗽", "肚子痛", "胃痛", "胃疼",
            "不舒服", "鼻塞", "喉咙痛", "头晕", "恶心", "拉肚子",
            "感冒", "流鼻涕", "嗓子疼", "腰疼", "腿疼", "眼睛疼"
        ]
        for kw in health_keywords:
            if kw in raw:
                return kw
        # 如果没有匹配到健康关键词，返回空字符串表示不应该记录
        return ""

    def _extract_mood_label(self, text: str) -> str:
        raw = str(text or "").strip()
        mood_keywords = ["开心", "难过", "焦虑", "紧张", "生气", "平静", "沮丧", "烦", "郁闷", "高兴", "快乐", "伤心", "崩溃"]
        for kw in mood_keywords:
            if kw in raw:
                return kw
        # 如果没有匹配到心情关键词，返回空字符串表示不应该记录
        return ""

    def _extract_vocab_word(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        matches = re.findall(r"[A-Za-z][A-Za-z'\-]{1,31}", raw)
        if not matches:
            return ""
        return str(matches[-1]).lower().strip()

    def _looks_like_wakeup(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        # 明确的起床信号：从睡眠状态中醒来
        wake_tokens = [
            "醒了",
            "醒啦",
            "刚醒",
            "起床",
            "起来了",
            "起来",
            "我起了",
            "我起来",
            "早安",
            "早上好",
            "早啊",  # 新增
            "被吵醒",
            "被叫醒",
            "自然醒",
            "睡醒",
            "醒来",
            "睡够了",
            "睡饱了",
            "起",
        ]
        if any(token in raw for token in wake_tokens):
            return True
        # "早啊"、"早呀"、"早~" 等问候语变体
        if re.search(r"早[啊呀~!！]", raw):
            return True
        # 单独的"早"（作为问候语，通常出现在句子开头）
        if re.match(r"^早[，。！？\s]|^早$", raw):
            return True
        # "没睡"不是起床信号，而是失眠/熬夜的描述
        # "不困"/"精神"/"清醒"只是状态描述，不代表刚起床
        if "醒" in raw and not self._looks_like_sleep(raw):
            # 排除"没醒"/"没睡醒"等否定
            if "没醒" not in raw and "没睡醒" not in raw:
                return True
        # 模式匹配：时间+起/醒
        if re.search(r"([01]?\d|2[0-3])[:：]([0-5]?\d).*?[起醒]", raw):
            return True
        if re.search(r"[零一二三四五六七八九十两\d]+\s*点.*?[起醒]", raw):
            return True
        return False

    def _looks_like_sleep(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        if self._looks_like_bath_activity(raw):
            return False
        sleep_tokens = [
            "晚安",
            "要睡",
            "先睡",
            "去睡",
            "我睡了",
            "睡觉了",
            "准备睡",
            "困了",
            "躺下",
            "睡了",
            "睡觉",
        ]
        if any(token in raw for token in sleep_tokens):
            return True
        # 模式匹配：时间+睡
        if re.search(r"([01]?\d|2[0-3])[:：]([0-5]?\d).*?睡", raw):
            return True
        if re.search(r"[零一二三四五六七八九十两\d]+\s*点.*?睡", raw):
            return True
        return False

    def _looks_like_bath_activity(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        bath_tokens = [
            "洗澡",
            "冲澡",
            "淋浴",
            "泡澡",
            "洗头",
            "洗漱",
            "洗个澡",
        ]
        return any(token in raw for token in bath_tokens)

    @staticmethod
    def _is_likely_midnight_wakeup(current_hour: int) -> bool:
        """判断当前是否可能是半夜起来上厕所/喝水（不应记录为正式起床）

        逻辑：结合用户典型作息判断。如果用户通常凌晨2-3点才睡，
        那凌晨1点发消息不可能是"半夜起来"，而是还没睡。
        只有在用户应该已经睡了的情况下（如通常23点睡），凌晨1-3点发消息才可能是半夜起来。
        """
        try:
            from core.services.active_care.scheduling.schedule_adapter import get_schedule_adapter
            adapter = get_schedule_adapter()
            params = adapter.get_adaptive_params()
            typical_sleep = params.get("typical_sleep_hour", -1.0)
            typical_wakeup = params.get("typical_wakeup_hour", -1.0)

            if typical_sleep < 0 or typical_wakeup < 0:
                # 没有学习到作息数据，使用保守默认值
                return 0 <= current_hour < 5

            # 如果用户通常凌晨X点睡，那么在X点之前都不算"半夜起来"
            # 例如：用户通常2点睡，凌晨1点发消息→还没睡，不是半夜起来
            if 0 <= typical_sleep < 12:
                # 夜猫子：睡觉时间在凌晨
                sleep_hour_int = int(typical_sleep)
                # 只有在睡觉时间之后到起床时间之前，才可能是半夜起来
                if sleep_hour_int <= current_hour < int(typical_wakeup):
                    # 但需要距离睡觉至少2小时（不太可能睡了1小时就起来聊天）
                    return False  # 无法确定距离，保守不拦截
                return current_hour < sleep_hour_int  # 还没到睡觉时间，不是半夜起来
            else:
                # 正常作息：23点睡8点起
                return 0 <= current_hour < min(5, int(typical_wakeup) - 2)
        except Exception:
            return 0 <= current_hour < 5

    async def _apply_bert_record(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        discourse = analyze_discourse(raw)
        explicit_sleep_span = (
            len(_extract_all_times(raw)) >= 2
            and "睡" in raw
            and ("睡到" in raw or any(k in raw for k in ["起", "起床", "醒了", "醒来"]))
        )
        if self._bert_runtime_available is False:
            return False
        if "[ACTIVE_CARE_" in raw or "_TRIGGER]" in raw:
            return False
        if self._looks_like_command_or_advice(raw):
            return False
        if not self._is_self_report(raw):
            return False
        if (
            discourse.get("trigger_blocked")
            and not discourse.get("is_correction")
            and not explicit_sleep_span
        ):
            return False
        
        times = _extract_all_times(raw)
        has_sleep_keyword = any(k in raw for k in ["睡", "睡了", "睡觉", "入睡"])
        has_wakeup_keyword = any(k in raw for k in ["起", "起床", "醒了", "醒来", "睡到"])
        
        if len(times) >= 2 and has_sleep_keyword and has_wakeup_keyword:
            parsed = _parse_sleep_wakeup_correction(raw)
            changed = False
            if parsed["sleep"]:
                self.manager.record_sleep(parsed["sleep"])
                changed = True
            if parsed["wakeup"]:
                current_hour = get_current_time().hour
                if not self._is_likely_midnight_wakeup(current_hour):
                    self.manager.record_wakeup(
                        parsed["wakeup"], source="chat_explicit_time"
                    )
                    changed = True
            if changed:
                self._last_record_source = "bert"
                return True
        
        try:
            from core.services.data_ops.bert_analyzer import get_bert_analyzer

            self._bert_runtime_available = True
            analyzer = get_bert_analyzer()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                analyzer.analyze,
                raw,
            )
            intent = str((result or {}).get("intent") or "NONE").upper()
            conf = float((result or {}).get("confidence") or 0.0)
            state_event = str(
                (result or {}).get("state_event") or "NONE"
            ).upper()
            state_event_confidence = float(
                (result or {}).get("state_event_confidence") or 0.0
            )
            trigger_allowed = bool(
                (result or {}).get("trigger_allowed", False)
            )
            state_event_to_intent = {
                "WAKEUP_NOW": "RECORD_WAKEUP",
                "SLEEP_NOW": "RECORD_SLEEP",
                "MEAL_NOW": "RECORD_MEAL",
                "STUDY_NOW": "RECORD_STUDY",
                "HEALTH_NOW": "RECORD_HEALTH",
                "MOOD_NOW": "RECORD_MOOD",
            }
            should_override = (
                state_event in state_event_to_intent
                and trigger_allowed
                and state_event_confidence >= 0.55
            )
            if should_override:
                intent = state_event_to_intent[state_event]
                conf = state_event_confidence
            elif conf < 0.75:
                return False
            wake_like = self._looks_like_wakeup(raw)
            sleep_like = self._looks_like_sleep(raw)
            if intent == "RECORD_SLEEP" and wake_like and not sleep_like:
                intent = "RECORD_WAKEUP"
            elif intent == "RECORD_WAKEUP" and sleep_like and not wake_like:
                intent = "RECORD_SLEEP"
            if intent == "RECORD_SLEEP" and self._looks_like_bath_activity(raw):
                intent = "RECORD_ACTIVITY"
            # 根据 intent 按需选择 UIE schema 字段（减少不必要的推理）
            uie_schema_needed: list[str] = []
            if intent == "RECORD_WAKEUP":
                uie_schema_needed.append("起床时间")
            elif intent == "RECORD_SLEEP":
                uie_schema_needed.append("睡觉时间")
            elif intent == "RECORD_MEAL":
                uie_schema_needed.extend(["吃的食物", "餐次"])
            elif intent == "RECORD_STUDY":
                uie_schema_needed.append("学习内容")
            elif intent == "RECORD_ACTIVITY":
                uie_schema_needed.append("活动内容")
            elif intent == "RECORD_HEALTH":
                uie_schema_needed.append("健康症状")
            elif intent == "RECORD_MOOD":
                uie_schema_needed.append("情绪")

            # UIE 异步提取（失败/不可用时返回空 dict，回退正则）
            # 为 UIE 拼接当前时间（提升无时间表述场景的提取成功率）
            augmented_raw = self._augment_text_with_time(raw, intent)
            uie_result = (
                await self._uie_extract_async(augmented_raw, uie_schema_needed)
                if uie_schema_needed
                else {}
            )

            def _uie_first_text(field: str) -> str:
                """取 UIE 某字段首个 span 的文本，无则返回空串。"""
                spans = uie_result.get(field) or []
                if not spans:
                    return ""
                return str(spans[0].get("text") or "").strip()

            if intent == "RECORD_WAKEUP":
                # UIE 优先提取起床时间，回退到正则
                uie_wakeup = _uie_first_text("起床时间")
                hhmm = (
                    self._uie_time_to_hhmm(uie_wakeup, raw, is_sleep=False)
                    if uie_wakeup
                    else (extract_time_hhmm(raw) or None)
                )
                # 基于用户典型作息判断是否为半夜起来（而非硬编码0-5点）
                current_hour = get_current_time().hour
                if hhmm and not self._is_likely_midnight_wakeup(current_hour):
                    self.manager.record_wakeup(
                        hhmm,
                        source="chat_explicit_time",
                    )
                    self._last_record_source = "bert_uie" if uie_wakeup else "bert"
                return True
            if intent == "RECORD_SLEEP":
                uie_sleep = _uie_first_text("睡觉时间")
                hhmm = (
                    self._uie_time_to_hhmm(uie_sleep, raw, is_sleep=True)
                    if uie_sleep
                    else (extract_time_hhmm(raw) or None)
                )
                if hhmm:
                    self.manager.record_sleep(
                        hhmm,
                        source="chat_explicit_time",
                    )
                    self._last_record_source = "bert_uie" if uie_sleep else "bert"
                return True
            if intent == "RECORD_MEAL":
                # UIE 提取食物内容，回退正则
                uie_food = _uie_first_text("吃的食物")
                food = uie_food or self._extract_meal_content(raw)
                # UIE 提取餐次并标准化，回退到 raw 关键词推断
                uie_meal_type = _uie_first_text("餐次")
                meal_type = "meal"
                if uie_meal_type:
                    from core.services.data_ops.uie_schema import MEAL_TYPE_NORMALIZE

                    for keyword, standard in MEAL_TYPE_NORMALIZE.items():
                        if keyword in uie_meal_type:
                            meal_type = standard
                            break
                if meal_type == "meal":
                    # UIE 未提取到餐次，从 raw 关键词推断
                    if "早餐" in raw or "早饭" in raw:
                        meal_type = "breakfast"
                    elif "午餐" in raw or "午饭" in raw:
                        meal_type = "lunch"
                    elif "晚餐" in raw or "晚饭" in raw:
                        meal_type = "dinner"
                    elif "夜宵" in raw or "宵夜" in raw:
                        meal_type = "late_night"
                self.manager.record_meal(meal_type, food)
                self._last_record_source = "bert_uie" if uie_food else "bert"
                return True
            if intent == "RECORD_STUDY":
                uie_study = _uie_first_text("学习内容")
                if uie_study:
                    self.manager.record_study(uie_study, raw[:80])
                    self._last_record_source = "bert_uie"
                else:
                    topic, content = self._extract_study_payload(raw)
                    self.manager.record_study(topic, content)
                    self._last_record_source = "bert"
                return True
            if intent == "RECORD_ACTIVITY":
                uie_activity = _uie_first_text("活动内容")
                activity_content = uie_activity or self._extract_activity_content(raw)
                self.manager.record_activity("activity", activity_content)
                self._last_record_source = "bert_uie" if uie_activity else "bert"
                return True
            if intent == "RECORD_HEALTH":
                uie_symptom = _uie_first_text("健康症状")
                symptom = uie_symptom or self._extract_health_symptom(raw)
                if symptom:  # 只有提取到有效症状才记录
                    self.manager.record_health(symptom, "")
                    self._last_record_source = "bert_uie" if uie_symptom else "bert"
                return True
            if intent == "RECORD_MOOD":
                # UIE 提取情绪文本（保留中文，不强制标准化为英文）
                uie_mood = _uie_first_text("情绪")
                mood_label = uie_mood or self._extract_mood_label(raw)
                if mood_label:  # 只有提取到有效心情才记录
                    self.manager.record_mood(mood_label, raw[:30])
                    self._last_record_source = "bert_uie" if uie_mood else "bert"
                return True
            if intent in {"RECORD_VOCAB_MISTAKE", "RECORD_VOCAB_UNKNOWN"}:
                from config.integrated_config import get_settings
                if not get_settings().study.enabled:
                    return False
                from core.tools.study.english.vocabulary_manager import (
                    get_vocabulary_manager,
                )

                target_word = self._extract_vocab_word(raw)
                if not target_word:
                    return False
                vm = get_vocabulary_manager()
                if not vm.get_word_info(target_word):
                    vm.add_to_learning(target_word)
                vm.update_word_progress(target_word, 1)
                self._last_record_source = "bert_vocab"
                return True
            return False
        except Exception as e:
            if "transformers" in str(e).lower():
                self._bert_runtime_available = False
            logger.warning(f"BERT activity extraction failed: {e}")
            return False

    def _apply_fast_record(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        discourse = analyze_discourse(raw)
        explicit_sleep_span = (
            len(_extract_all_times(raw)) >= 2
            and "睡" in raw
            and ("睡到" in raw or any(k in raw for k in ["起", "起床", "醒了", "醒来"]))
        )
        if (
            discourse.get("trigger_blocked")
            and not discourse.get("is_correction")
            and not explicit_sleep_span
        ):
            return False
        changed = False

        times = _extract_all_times(raw)
        has_sleep_keyword = any(k in raw for k in ["睡", "睡了", "睡觉", "入睡"])
        has_wakeup_keyword = any(k in raw for k in ["起", "起床", "醒了", "醒来", "睡到"])
        
        if len(times) >= 2 and has_sleep_keyword and has_wakeup_keyword:
            parsed = _parse_sleep_wakeup_correction(raw)
            if parsed["sleep"]:
                self.manager.record_sleep(parsed["sleep"])
                changed = True
            if parsed["wakeup"]:
                current_hour = get_current_time().hour
                if not self._is_likely_midnight_wakeup(current_hour):
                    self.manager.record_wakeup(
                        parsed["wakeup"], source="chat_explicit_time"
                    )
                    changed = True
            if changed:
                self._last_record_source = "fast"
                return changed

        state_event = infer_state_event(raw, discourse)
        wake_like = state_event == "WAKEUP_NOW" or (
            self._has_record_intent(raw) and "早起" in raw
        )
        sleep_like = state_event == "SLEEP_NOW"
        hhmm = extract_time_hhmm(raw) or None

        current_hour = get_current_time().hour

        if wake_like and hhmm and not self._is_likely_midnight_wakeup(current_hour):
            self.manager.record_wakeup(
                hhmm,
                source="chat_explicit_time",
            )
            changed = True
        if sleep_like and not wake_like and hhmm:
            self.manager.record_sleep(hhmm, source="chat_explicit_time")
            changed = True

        eat_keywords = ["吃了", "吃过", "有吃"]
        if ("早餐" in raw or "早饭" in raw) and any(k in raw for k in eat_keywords):
            self.manager.record_meal("breakfast", self._extract_meal_content(raw))
            changed = True
        if ("午餐" in raw or "午饭" in raw) and any(k in raw for k in eat_keywords):
            self.manager.record_meal("lunch", self._extract_meal_content(raw))
            changed = True
        if ("晚餐" in raw or "晚饭" in raw) and any(k in raw for k in eat_keywords):
            self.manager.record_meal("dinner", self._extract_meal_content(raw))
            changed = True

        if self._has_record_intent(raw) and ("没吃" in raw or "没有吃" in raw):
            if "午餐" in raw or "午饭" in raw:
                self.manager.record_activity("diet_note", "用户补录：午餐未吃")
                changed = True
            if "晚餐" in raw or "晚饭" in raw:
                self.manager.record_activity("diet_note", "用户补录：晚餐未吃")
                changed = True
            if "早餐" in raw or "早饭" in raw:
                self.manager.record_activity("diet_note", "用户补录：早餐未吃")
                changed = True

        if changed:
            self._last_record_source = "fast"
        return changed

    def _looks_like_command_or_advice(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return True
        lowered = raw.lower()
        blocked_prefixes = [
            "去",
            "快去",
            "记得",
            "别忘了",
            "你去",
            "你该",
            "你要",
            "该去",
            "要不要",
        ]
        # 检查是否是过去时（包含"了"、"过"等标记）
        past_markers = ["了", "过", "完"]
        if any(raw.startswith(prefix) for prefix in blocked_prefixes):
            # 如果是过去时，不是命令
            if any(marker in raw for marker in past_markers):
                return False
            return True
        if "？" in raw or "?" in raw:
            return True
        blocked_tokens = [
            "提醒你",
            "让你",
            "建议你",
            "你应该",
            "你可以",
            "you should",
            "remember to",
        ]
        if any(token in lowered for token in blocked_tokens):
            return True
        return False

    def _is_self_report(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        discourse = analyze_discourse(raw)
        if self._has_record_intent(raw):
            return True
        if self._looks_like_command_or_advice(raw):
            return False
        if discourse.get("is_reported_speech") or discourse.get("is_hypothetical"):
            return False
        
        # 过滤疑问句（以"吗"、"呢"、"？"结尾）
        if raw.endswith("吗") or raw.endswith("呢"):
            return False
        
        # 过滤请求/命令句
        request_patterns = [
            "你不能", "你能", "帮我", "请帮我", "能不能", "可以不",
            "你为什么不", "你怎么不", "配合我", "跟我一起"
        ]
        if any(p in raw for p in request_patterns):
            return False
        
        # 过滤感叹/抱怨句（不是真实事件）
        complaint_patterns = [
            "哎", "唉", "烦死了", "气死", "累死", "摆烂"
        ]
        if any(p in raw for p in complaint_patterns):
            # 除非明确包含事件关键词或心情关键词
            event_keywords = ["吃了", "睡了", "起床", "学了", "做了"]
            mood_keywords = ["开心", "难过", "焦虑", "紧张", "生气", "沮丧", "郁闷", "高兴", "快乐", "伤心"]
            if not any(k in raw for k in event_keywords) and not any(k in raw for k in mood_keywords):
                return False
        
        # 过滤歌词/引用内容（包含日语、英语歌词特征）
        lyric_patterns = [
            "が", "の", "に", "は", "を", "です", "ます",  # 日语
            "孤独の友", "我が",  # 日语歌词常见
        ]
        if any(p in raw for p in lyric_patterns):
            return False
        
        # 过滤"我是说"、"我是想"开头的解释性语句
        explanation_patterns = ["我是说", "我是想", "我的意思是", "I mean"]
        if any(raw.startswith(p) for p in explanation_patterns):
            return False
        
        self_markers = [
            "我",
            "刚",
            "已经",
            "刚刚",
            "才",
            "我在",
            "我刚",
            "i ",
            "i'm",
            "i am",
            "i just",
            "i already",
        ]
        lowered = raw.lower()
        
        # 明确的事件关键词（即使没有self_markers也认为是self_report）
        explicit_event_keywords = [
            # 喝水
            "喝水了", "喝了水", "喝了杯水", "喝杯水", "喝点水",
            # 活动
            "去玩了", "去玩", "出门了", "出门",
            "运动了", "健身了", "逛街了",
            "打游戏", "看了电影", "看电影", "玩游戏",
            # 学习
            "学习了", "学习", "复习了", "背了单词", "写代码", "刷题了",
            "看了书", "做作业", "写了作业", "做了作业", "学英语", "学了英语",
            # 心情
            "心情好", "心情不好", "开心", "难过", "焦虑", "紧张", "生气", "沮丧", "郁闷", "高兴", "快乐", "伤心",
            # 健康
            "头疼", "头痛", "发烧", "咳嗽", "肚子痛", "胃痛", "胃疼", "不舒服", "头晕", "喉咙痛", "感冒了", "流鼻涕", "嗓子疼",
            # 饮食
            "吃了早餐", "吃了午餐", "吃了晚餐", "吃了饭", "吃早餐", "吃午餐", "吃晚餐",
            "吃了午饭", "吃了晚饭", "吃午饭", "吃晚饭", "刚吃完", "正在吃", "吃好了",
            "八点半吃早饭", "吃早饭", "吃午饭", "吃晚饭",
            "吃过早餐", "吃过午餐", "吃过晚餐", "吃过饭",
        ]
        if any(k in raw for k in explicit_event_keywords):
            return True
        
        if any(marker in raw for marker in self_markers[:6]):
            # 额外检查：必须包含实际事件动词或健康/心情关键词
            event_verbs = [
                "吃", "喝", "睡", "醒", "起", "学", "复习", "做", "看",
                "玩", "去", "来", "买", "洗", "运动", "健身", "写"
            ]
            # 健康和心情关键词也应该允许
            health_mood_keywords = [
                "头疼", "头痛", "发烧", "咳嗽", "肚子痛", "胃痛", "不舒服", "头晕",
                "开心", "难过", "焦虑", "紧张", "生气", "沮丧", "烦", "郁闷", "高兴"
            ]
            if not any(v in raw for v in event_verbs) and not any(k in raw for k in health_mood_keywords):
                return False
            return True
        if any(marker in lowered for marker in self_markers[7:]):
            # 英文输入需要更严格的检查
            english_event_verbs = ["ate", "eaten", "slept", "woke", "studied", "learned", "went"]
            if not any(v in lowered for v in english_event_verbs):
                return False
            return True
        short_self_reports = {
            "晚安", "睡了", "我睡了", "刚醒", "醒了",
            "起床了", "早安", "早上好"
        }
        return raw in short_self_reports

    async def analyze_and_record(self, user_input: str):
        """
        基于纠正规则、快速规则与 BERT 语义识别记录生活事件。
        """
        self._last_record_source = ""
        if await apply_daily_semantic_correction(user_input, self.manager):
            self._last_record_source = "bert_correction"
            return
        if self._apply_fast_correction(user_input):
            return
        if self._apply_fast_record(user_input):
            return
        if await self._apply_bert_record(user_input):
            return
        return


_instance = None


def get_activity_extractor():
    global _instance
    if _instance is None:
        _instance = ActivityExtractor()
    return _instance
