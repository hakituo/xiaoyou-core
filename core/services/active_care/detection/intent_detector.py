"""
意图检测模块
负责检测用户的晚安、早安、清醒等意图

架构：BERT 语义先行 + 关键词兜底
优先使用 BERT 语义理解检测意图（如 SLEEP_NOW、WAKEUP_NOW），
关键词匹配作为快速路径和 BERT 不可用时的回退。
这样"我先躺了"、"困死了"、"明天见"等语义上明显是睡觉意图的话也能被检测到。
"""
import time
from typing import Any, Dict, List

from core.utils.logger import get_module_logger
from core.services.active_care.shared.constants import (
    GoodnightKeywords,
    GoodnightNegationPatterns,
    GoodmorningKeywords,
    AwakePresenceKeywords,
    SleepHintKeywords,
)
from core.utils.timestamp_utils import safe_timestamp

logger = get_module_logger("ACTIVE_CARE_INTENT", "active_care_schedule.log")

# BERT 检测置信度阈值
_BERT_SLEEP_CONFIDENCE_THRESHOLD = 0.40
_BERT_WAKEUP_CONFIDENCE_THRESHOLD = 0.40
_BERT_SLEEP_HINT_CONFIDENCE_THRESHOLD = 0.45
_ASSISTANT_EXPLICIT_GOODNIGHT_PHRASES = (
    "晚安", "good night", "做个好梦", "好梦",
    "早点睡", "早点休息", "快去睡", "该睡了", "睡吧", "去睡吧",
    "先睡了", "我先睡了", "我要睡了", "我去睡了", "我真要睡了",
    "准备睡了", "这就睡", "这就去睡", "睡觉去", "去休息吧",
    "明天见", "明早见", "明天聊", "明天再说",
)
_ASSISTANT_WAKE_CONFLICT_PHRASES = (
    "起床", "起来", "起了", "刚起", "醒了", "醒着", "早晨", "早上好", "早安",
)


class IntentDetector:
    """意图检测器，负责检测用户的各种意图信号

    采用 BERT 语义先行 + 关键词兜底的架构：
    1. 先尝试 BERT 语义检测（如 SLEEP_NOW、WAKEUP_NOW）
    2. BERT 不命中时，回退到关键词匹配
    3. 否定语境检测始终作为最终过滤
    """

    def __init__(self, mode_state_resolver=None):
        self._mode_state_resolver = mode_state_resolver
        self._bert_analyzer = None

    def _get_bert_analyzer(self):
        """延迟加载 BERT 分析器"""
        if self._bert_analyzer is not None:
            return self._bert_analyzer
        try:
            from core.services.data_ops.bert_analyzer import get_bert_analyzer
            self._bert_analyzer = get_bert_analyzer()
        except ImportError:
            self._bert_analyzer = None
        except Exception as e:
            logger.debug("BERT 分析器初始化失败: %s", e)
            self._bert_analyzer = None
        return self._bert_analyzer

    def _detect_bert_state_event(self, text: str, target_state: str, confidence_threshold: float = 0.40) -> tuple:
        """通用 BERT 状态事件检测

        Returns:
            (detected: bool, confidence: float)
        """
        analyzer = self._get_bert_analyzer()
        if not analyzer:
            return False, 0.0
        try:
            result = analyzer.analyze(text)
            if not result:
                return False, 0.0
            state_event = str(result.get("state_event") or "NONE")
            confidence = float(result.get("state_event_confidence") or 0.0)
            trigger_allowed = bool(result.get("trigger_allowed", False))
            if trigger_allowed and state_event == target_state and confidence >= confidence_threshold:
                return True, confidence
        except Exception as e:
            logger.debug("BERT 状态检测异常: %s", e)
        return False, 0.0

    def contains_goodnight_intent(self, text: str) -> bool:
        """检测晚安/睡觉意图

        检测顺序：
        1. BERT 语义检测 SLEEP_NOW（能理解"我先躺了"、"困死了"等）
        2. 关键词匹配兜底（BERT 不可用或未命中时）
        3. 否定语境过滤（始终生效）
        """
        lower = str(text or "").strip().lower()
        if not lower:
            return False

        # 否定语境始终优先检查
        if self._is_negated_goodnight(lower):
            logger.info("Active Care: 检测到否定/反问语境，跳过晚安意图: %s", text[:60])
            return False

        # 第一层：BERT 语义检测
        bert_detected, bert_conf = self._detect_bert_state_event(
            lower, "SLEEP_NOW", _BERT_SLEEP_CONFIDENCE_THRESHOLD
        )
        if bert_detected:
            logger.info(
                "Active Care: BERT 语义检测到晚安意图 (SLEEP_NOW, conf=%.2f): %s",
                bert_conf, text[:60],
            )
            return True

        # 第二层：关键词匹配兜底
        sleep_keywords = GoodnightKeywords.EXTENDED
        has_count_sleep = "数" in lower and ("就睡" in lower or "再睡" in lower)
        keyword_matched = has_count_sleep or any(kw in lower for kw in sleep_keywords)

        if not keyword_matched:
            return False

        # 关键词命中后，用 BERT 做二次验证（防止误触发）
        if bert_conf > 0 and bert_conf < _BERT_SLEEP_CONFIDENCE_THRESHOLD:
            # BERT 检测过但置信度不够，且关键词命中，检查 BERT 是否明确否决
            if self._mode_state_resolver:
                bert_verify = getattr(self._mode_state_resolver, "detect_sleep_with_bert", None)
                if bert_verify:
                    try:
                        if not bert_verify(lower):
                            logger.info(
                                "Active Care: 关键词命中晚安但 BERT 否决: %s", text[:60]
                            )
                            return False
                    except Exception:
                        pass

        logger.info("Active Care: 关键词检测到晚安意图: %s", text[:60])
        return True

    def _is_negated_goodnight(self, lower: str) -> bool:
        if any(combo in lower for combo in GoodnightNegationPatterns.NEGATION_COMBOS):
            return True
        for prefix in GoodnightNegationPatterns.NEGATION_PREFIXES:
            idx = lower.find(prefix)
            if idx < 0:
                continue
            after = lower[idx + len(prefix):]
            if any(kw in after for kw in GoodnightKeywords.PRIMARY):
                return True
        return False

    def contains_goodmorning_intent(self, text: str) -> bool:
        """检测早安/起床意图

        检测顺序：
        1. BERT 语义检测 WAKEUP_NOW（能理解"我起了"、"刚醒"等）
        2. 关键词匹配兜底
        """
        lower = str(text or "").strip().lower()
        if not lower:
            return False

        # 第一层：BERT 语义检测
        bert_detected, bert_conf = self._detect_bert_state_event(
            lower, "WAKEUP_NOW", _BERT_WAKEUP_CONFIDENCE_THRESHOLD
        )
        if bert_detected:
            logger.info(
                "Active Care: BERT 语义检测到早安意图 (WAKEUP_NOW, conf=%.2f): %s",
                bert_conf, text[:60],
            )
            return True

        # 第二层：关键词匹配兜底
        keyword_matched = any(kw in lower for kw in GoodmorningKeywords.ALL)
        if not keyword_matched:
            return False

        # 关键词命中后，BERT 二次验证
        if self._mode_state_resolver:
            bert_verify = getattr(self._mode_state_resolver, "detect_wakeup_with_bert", None)
            if bert_verify:
                try:
                    if not bert_verify(lower):
                        logger.info(
                            "Active Care: 关键词命中早安但 BERT 否决: %s", text[:60]
                        )
                        return False
                except Exception:
                    pass

        logger.info("Active Care: 关键词检测到早安意图: %s", text[:60])
        return True

    def contains_awake_presence(self, text: str) -> bool:
        """检测清醒/在线信号

        检测顺序：
        1. BERT 语义检测 WAKEUP_NOW
        2. 关键词匹配兜底
        """
        lower = str(text or "").strip().lower()
        if not lower:
            return False

        # 第一层：BERT 语义检测
        bert_detected, bert_conf = self._detect_bert_state_event(
            lower, "WAKEUP_NOW", _BERT_WAKEUP_CONFIDENCE_THRESHOLD
        )
        if bert_detected:
            logger.info(
                "Active Care: BERT 语义检测到清醒信号 (WAKEUP_NOW, conf=%.2f): %s",
                bert_conf, text[:60],
            )
            return True

        # 第二层：关键词匹配兜底
        keyword_matched = any(kw in lower for kw in AwakePresenceKeywords.ALL)
        if not keyword_matched:
            return False

        # 关键词命中后，BERT 二次验证
        if self._mode_state_resolver:
            bert_verify = getattr(self._mode_state_resolver, "detect_wakeup_with_bert", None)
            if bert_verify:
                try:
                    if not bert_verify(lower):
                        logger.info(
                            "Active Care: 关键词命中清醒但 BERT 否决: %s", text[:60]
                        )
                        return False
                except Exception:
                    pass

        return True

    def contains_sleep_hint(self, text: str) -> bool:
        """检测条件性睡眠暗示，如'没回就是睡了'

        检测顺序：
        1. 关键词匹配（睡眠暗示是非常特定的句式，关键词精度高）
        2. BERT 语义补充检测（能识别"不回的话就是困了"等变体）
        """
        lower = str(text or "").strip().lower()
        if not lower:
            return False

        # 第一层：关键词匹配（睡眠暗示句式特定，关键词精度高）
        keyword_matched = any(kw in lower for kw in SleepHintKeywords.ALL)
        if keyword_matched:
            logger.info("Active Care: 检测到睡眠暗示(关键词): %s", text[:60])
            return True

        # 第二层：BERT 语义补充检测
        bert_detected, bert_conf = self._detect_bert_state_event(
            lower, "SLEEP_NOW", _BERT_SLEEP_HINT_CONFIDENCE_THRESHOLD
        )
        if bert_detected:
            # BERT 检测到 SLEEP_NOW，但需要判断是否是"条件性暗示"而非直接晚安
            # 如果文本包含条件性表达（"如果"、"的话"、"不回"等），视为睡眠暗示
            conditional_patterns = ["如果", "的话", "不回", "没回", "回不了", "没动静"]
            if any(p in lower for p in conditional_patterns):
                logger.info(
                    "Active Care: BERT 语义检测到睡眠暗示 (SLEEP_NOW+条件, conf=%.2f): %s",
                    bert_conf, text[:60],
                )
                return True

        return False

    def extract_latest_user_signal(
        self,
        history: List[Dict[str, Any]],
        safe_ts_func=None
    ) -> Dict[str, Any]:
        """
        从历史记录中提取最新的用户信号
        
        Args:
            history: 历史记录列表
            safe_ts_func: 安全时间戳转换函数
            
        Returns:
            {"content": str, "timestamp": float}
        """
        for item in reversed(history or []):
            role = str(item.get("role") or "").strip().lower()
            if role != "user":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            
            # 使用传入的 safe_ts 函数或统一工具
            if safe_ts_func:
                ts = safe_ts_func(item.get("timestamp"))
            else:
                ts = safe_timestamp(item.get("timestamp"))
            
            return {"content": content, "timestamp": ts}
        return {}

    def extract_latest_assistant_goodnight(
        self,
        history: List[Dict[str, Any]],
        now: float,
        max_age_seconds: float = 600.0,
        safe_ts_func=None,
    ) -> Dict[str, Any]:
        """
        从历史记录中检测助手最近是否说了晚安
        
        当助手主动说晚安时，意味着用户应该去睡觉了，
        需要激活睡眠会话以防止后续 active care 发出矛盾消息。
        
        Args:
            history: 历史记录列表
            now: 当前时间戳
            max_age_seconds: 最大消息年龄（秒），默认600秒（10分钟）
            safe_ts_func: 安全时间戳转换函数
            
        Returns:
            {"detected": bool, "content": str, "timestamp": float}
        """
        result = {"detected": False, "content": "", "timestamp": 0.0}
        if not history:
            return result

        def _safe_ts(value):
            if safe_ts_func:
                return safe_ts_func(value)
            return safe_timestamp(value)

        for item in reversed(history):
            role = str(item.get("role") or "").strip().lower()
            if role != "assistant":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            ts = _safe_ts(item.get("timestamp"))
            if ts <= 0:
                continue
            age = now - ts
            if age > max_age_seconds:
                break
            if self.contains_assistant_goodnight_intent(content):
                result["detected"] = True
                result["content"] = content
                result["timestamp"] = ts
                return result

        return result

    def contains_assistant_goodnight_intent(self, text: str) -> bool:
        """检测助手是否明确表达了“准备去睡/已经道晚安”。

        这里故意比通用的 contains_goodnight_intent 更严格：
        - 只接受明确的晚安/睡前告别表达；
        - 单纯提到“睡觉/起床/早晨”的吐槽、复述、调侃不算；
        - 避免把“下午五点起床”“睡了一整天”这类内容误判成晚安。
        """
        lower = str(text or "").strip().lower()
        if not lower:
            return False
        if self._is_negated_goodnight(lower):
            return False

        has_explicit_goodnight = any(
            phrase in lower for phrase in _ASSISTANT_EXPLICIT_GOODNIGHT_PHRASES
        )
        if has_explicit_goodnight:
            return True

        # 仅提到“睡/起床/早晨”但没有明确睡前告别，不视为助手晚安。
        if any(phrase in lower for phrase in _ASSISTANT_WAKE_CONFLICT_PHRASES):
            return False
        return False

    def infer_late_night_activity(
        self,
        history: List[Dict[str, Any]],
        now: float,
        safe_ts_func=None
    ) -> Dict[str, Any]:
        """
        基于最近聊天记录推断用户是否可能有深夜/凌晨活动
        
        如果用户在深夜(0-5点)有对话，且当前是早上(6-10点),
        推断用户可能刚睡不久或睡得晚。
        
        Args:
            history: 历史记录列表
            now: 当前时间戳
            safe_ts_func: 安全时间戳转换函数
            
        Returns:
            {
                "has_late_night_activity": bool,
                "latest_late_night_hour": int,
                "hours_since_late_night": int,
                "late_night_message_preview": str,
            }
        """
        result = {
            "has_late_night_activity": False,
            "latest_late_night_hour": -1,
            "hours_since_late_night": -1,
            "late_night_message_preview": "",
        }
        if not history:
            return result
        
        # 使用传入的 safe_ts 函数或统一工具
        def _safe_ts(value):
            if safe_ts_func:
                return safe_ts_func(value)
            return safe_timestamp(value)
        
        # 查找最近的历史记录中是否有深夜对话
        for item in reversed(history):
            role = str(item.get("role") or "").strip().lower()
            ts = _safe_ts(item.get("timestamp"))
            if ts <= 0 or role != "user":
                continue
            
            try:
                msg_dt = time.localtime(ts)
                msg_hour = msg_dt.tm_hour
                
                # 深夜时段：0-5点
                if 0 <= msg_hour <= 5:
                    elapsed = max(0.0, now - ts)
                    hours_since = int(elapsed / 3600)
                    
                    result["has_late_night_activity"] = True
                    result["latest_late_night_hour"] = msg_hour
                    result["hours_since_late_night"] = hours_since
                    content = str(item.get("content") or "")[:30]
                    result["late_night_message_preview"] = content
                    break
            except Exception:
                continue
        
        return result
