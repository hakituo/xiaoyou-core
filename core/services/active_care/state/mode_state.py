"""
模式状态管理器
负责管理用户的模式切换：正常模式、学习模式、私密模式等
"""
import asyncio
import re
from collections import OrderedDict
from typing import Any, Dict

from core.services.active_care.state.base import StateBase
from core.services.active_care.shared.constants import (
    FocusEnterKeywords,
    FocusExitKeywords,
    is_focus_presence_statement,
    extract_expected_end_ts,
    StateKeys,
)
from core.utils.logger import get_module_logger

logger = get_module_logger("MODE_STATE", "state_manager.log")


def is_direct_awake_statement(text: str) -> bool:
    """仅识别用户对“此刻清醒”的直接陈述，不抽取正式起床事实。"""
    raw = str(text or "").strip().lower()
    if re.fullmatch(r"(早安|早上好|good morning|morning)[啊呀。！!,.，]*", raw):
        return True
    return bool(
        re.fullmatch(
            r"(我)?(终于|总算|已经|刚刚|刚才|刚)?(从床上)?(午睡|午觉)?(睡)?"
            r"(醒了|醒啦|睡醒了|起来了|起床了|刚起来|爬起来了|下床了)"
            r"[啊呀嘛吧。！!,.，]*",
            raw,
        )
    )


class ModeStateManager(StateBase):
    """
    模式状态管理器
    
    职责：
    1. 检测模式切换意图
    2. 管理模式状态
    3. 构建模式状态更新
    """
    
    MODE_DAILY = "daily"
    MODE_STUDY = "study_teaching"
    MODE_REDUCED = "low_presence"
    
    BERT_STATE_TO_MODE = {
        "WAKEUP_NOW": {"action": "exit_reduced", "reason": "morning", "label": "wake"},
        "SLEEP_NOW": {"action": "enter_reduced", "reason": "goodnight", "label": "sleep"},
        "STUDY_NOW": {"action": "enter_reduced", "reason": "focus", "label": "focus"},
        "MEAL_NOW": {"action": "exit_reduced", "reason": "done", "label": "finished"},
        "DRINK_NOW": {"action": "exit_reduced", "reason": "done", "label": "finished"},
        "HEALTH_NOW": {"action": "exit_reduced", "reason": "done", "label": "finished"},
        "MOOD_NOW": {"action": "exit_reduced", "reason": "done", "label": "finished"},
    }
    
    BERT_STATE_TO_FOCUS_ENTER = {"STUDY_NOW"}
    
    def __init__(self, storage=None):
        super().__init__(storage)
        self._bert_analyzer = None
        self._bert_cache: OrderedDict = OrderedDict()
        self._bert_cache_max = 32
    
    def _get_bert_analyzer(self):
        if self._bert_analyzer is None:
            try:
                from core.services.data_ops.bert_analyzer import get_bert_analyzer
                self._bert_analyzer = get_bert_analyzer()
            except ImportError:
                self._bert_analyzer = None
            except Exception as e:
                logger.error(f"BERT分析器初始化失败: {e}", exc_info=True)
                self._bert_analyzer = None
        return self._bert_analyzer
    
    async def get_current_state(self) -> Dict[str, Any]:
        try:
            state = await self._get_state()
            
            preference_mode = "normal"
            try:
                from core.managers.preference_manager import get_preference_manager
                preference_mode = get_preference_manager().get_mode()
            except ImportError:
                pass
            except Exception as e:
                logger.warning(f"获取偏好模式失败: {e}")
            
            reduced_mode_active = bool(state.get(StateKeys.REDUCED_MODE_ACTIVE))
            reduced_mode_reason = str(state.get(StateKeys.REDUCED_MODE_REASON) or "none")
            
            if preference_mode == "study":
                mode = self.MODE_STUDY
            elif reduced_mode_active:
                mode = self.MODE_REDUCED
            else:
                mode = self.MODE_DAILY
            
            return {
                "mode": mode,
                "reduced_mode_active": reduced_mode_active,
                "reduced_mode_reason": reduced_mode_reason,
                "preference_mode": preference_mode,
            }
            
        except Exception as e:
            logger.error(f"获取模式状态失败: {e}")
            return {
                "mode": self.MODE_DAILY,
                "reduced_mode_active": False,
                "reduced_mode_reason": "none",
                "preference_mode": "normal",
            }
    
    async def reset(self) -> bool:
        updates = {
            StateKeys.REDUCED_MODE_ACTIVE: False,
            StateKeys.REDUCED_MODE_REASON: "none",
            StateKeys.REDUCED_MODE_LABEL: "",
            StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
            StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
        }
        return await self._save_state(updates)
    
    async def detect_transition_intent(self, text: str) -> Dict[str, Any]:
        raw = str(text or "").strip()
        lower = raw.lower()

        # 这里只把直接陈述当作“恢复正常打扰”的信号；不提取正式起床时间。
        # 限定整句可避免“你起床了吗”“我午睡醒了算起床吗”之类讨论误触发。
        if is_direct_awake_statement(raw):
            return {
                "action": "exit_reduced",
                "reason": "morning",
                "label": "wake",
                "source": "rule",
            }

        state_event, bert_confidence = await self._detect_state_event_with_bert_async(raw)
        bert_veto = False
        # 起床会直接退出用户的晚安低打扰，属于高影响状态切换。
        # 零样本 BERT 的相似度不等于校准后的概率，不能仅凭 WAKEUP_NOW 标签改状态；
        # 明确的当前起床陈述已由上面的高精度规则处理。
        if state_event == "WAKEUP_NOW":
            logger.info(
                "忽略缺少明确起床陈述的 BERT WAKEUP_NOW: conf=%.2f text=%s",
                bert_confidence,
                raw[:60],
            )
            return {"action": "none"}

        if state_event and state_event != "NONE" and bert_confidence >= 0.40:
            bert_intent = self.BERT_STATE_TO_MODE.get(state_event)
            if bert_intent:
                bert_intent = dict(bert_intent)
                bert_intent["source"] = "bert"
                bert_intent["bert_confidence"] = bert_confidence
                if state_event in self.BERT_STATE_TO_FOCUS_ENTER:
                    if self._is_passive_study_mention(raw):
                        logger.info(
                            "BERT检测到STUDY_NOW但文本为被动提及学习话题，否决进入专注模式: %s",
                            raw[:60],
                        )
                        return {"action": "none"}
                    bert_intent["expected_end_ts"] = extract_expected_end_ts(lower)
                if state_event == "SLEEP_NOW" and (
                    self._is_time_reference_sleep(raw) or self._is_correction_context(raw)
                ):
                    pass
                else:
                    return bert_intent
        elif state_event == "NONE" and bert_confidence < 0.3:
            bert_veto = True

        if any(kw in lower for kw in FocusExitKeywords.ALL):
            if bert_veto:
                return {"action": "none"}
            return {"action": "exit_reduced", "reason": "done", "label": "finished", "source": "rule"}

        if self._is_time_reference_sleep(raw) or self._is_correction_context(raw):
            return {"action": "none"}

        if any(kw in lower for kw in FocusEnterKeywords.ALL):
            if bert_veto:
                return {"action": "none"}
            expected_end_ts = extract_expected_end_ts(lower)
            return {
                "action": "enter_reduced",
                "reason": "focus",
                "label": "focus",
                "expected_end_ts": expected_end_ts,
                "source": "rule",
            }

        if is_focus_presence_statement(raw):
            if bert_veto:
                return {"action": "none"}
            expected_end_ts = extract_expected_end_ts(lower)
            return {
                "action": "enter_reduced",
                "reason": "focus",
                "label": "focus",
                "expected_end_ts": expected_end_ts,
                "source": "rule",
            }

        return {"action": "none"}
    
    def build_state_updates(
        self,
        intent: Dict[str, Any],
        now_ts: float,
    ) -> Dict[str, Any]:
        action = str(intent.get("action") or "none")
        
        if action == "enter_reduced":
            return {
                StateKeys.REDUCED_MODE_ACTIVE: True,
                StateKeys.REDUCED_MODE_REASON: str(intent.get("reason") or "manual"),
                StateKeys.REDUCED_MODE_LABEL: str(intent.get("label") or "focus"),
                StateKeys.REDUCED_MODE_STARTED_TS: now_ts,
                StateKeys.REDUCED_MODE_EXPECTED_END_TS: float(intent.get("expected_end_ts") or 0.0),
            }
        
        if action == "exit_reduced":
            return {
                StateKeys.REDUCED_MODE_ACTIVE: False,
                StateKeys.REDUCED_MODE_REASON: "none",
                StateKeys.REDUCED_MODE_LABEL: "",
                StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
                StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
            }
        
        return {}
    
    def resolve_active_care_mode(
        self,
        preference_mode: str,
        proactive_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        pref = str(preference_mode or "normal").strip().lower()
        reduced_mode_active = bool(proactive_state.get(StateKeys.REDUCED_MODE_ACTIVE))
        
        if pref == "study":
            return {
                "mode": self.MODE_STUDY,
                "reduced_mode_active": reduced_mode_active,
                "reduced_mode_reason": str(proactive_state.get(StateKeys.REDUCED_MODE_REASON) or "none"),
            }
        
        if reduced_mode_active:
            return {
                "mode": self.MODE_REDUCED,
                "reduced_mode_active": True,
                "reduced_mode_reason": str(proactive_state.get(StateKeys.REDUCED_MODE_REASON) or "focus"),
            }
        
        return {
            "mode": self.MODE_DAILY,
            "reduced_mode_active": False,
            "reduced_mode_reason": "none",
        }
    
    def _analyze_with_bert(self, text: str) -> Dict[str, Any]:
        cache_key = text.strip().lower()
        if cache_key in self._bert_cache:
            self._bert_cache.move_to_end(cache_key)
            return self._bert_cache[cache_key]
        analyzer = self._get_bert_analyzer()
        if not analyzer:
            return {}
        try:
            result = analyzer.analyze(text)
            if len(self._bert_cache) >= self._bert_cache_max:
                self._bert_cache.popitem(last=False)
            self._bert_cache[cache_key] = result
            return result
        except Exception:
            return {}

    async def _analyze_with_bert_async(self, text: str) -> Dict[str, Any]:
        cache_key = text.strip().lower()
        if cache_key in self._bert_cache:
            self._bert_cache.move_to_end(cache_key)
            return self._bert_cache[cache_key]
        analyzer = self._get_bert_analyzer()
        if not analyzer:
            return {}
        try:
            result = await asyncio.to_thread(analyzer.analyze, text)
            if len(self._bert_cache) >= self._bert_cache_max:
                self._bert_cache.popitem(last=False)
            self._bert_cache[cache_key] = result
            return result
        except Exception:
            return {}

    def _detect_bert_state(self, text: str, target_state: str) -> bool:
        """通用BERT状态检测方法，消除 detect_wakeup_with_bert/detect_sleep_with_bert 的重复"""
        result = self._analyze_with_bert(text)
        if not result:
            return False
        state_event = str(result.get("state_event") or "NONE")
        confidence = float(result.get("state_event_confidence") or 0.0)
        trigger_allowed = bool(result.get("trigger_allowed", False))
        return trigger_allowed and state_event == target_state and confidence >= 0.40

    def detect_wakeup_with_bert(self, text: str) -> bool:
        return self._detect_bert_state(text, "WAKEUP_NOW")
    
    def detect_sleep_with_bert(self, text: str) -> bool:
        return self._detect_bert_state(text, "SLEEP_NOW")
    
    def _detect_state_event_with_bert(self, text: str) -> tuple:
        result = self._analyze_with_bert(text)
        if not result:
            return None, 0.0
        state_event = str(result.get("state_event") or "NONE")
        confidence = float(result.get("state_event_confidence") or 0.0)
        trigger_allowed = bool(result.get("trigger_allowed", False))
        if not trigger_allowed:
            return "NONE", 0.0
        return state_event, confidence

    async def _detect_state_event_with_bert_async(self, text: str) -> tuple:
        """异步版本的BERT状态检测，不阻塞事件循环"""
        result = await self._analyze_with_bert_async(text)
        if not result:
            return None, 0.0
        state_event = str(result.get("state_event") or "NONE")
        confidence = float(result.get("state_event_confidence") or 0.0)
        trigger_allowed = bool(result.get("trigger_allowed", False))
        if not trigger_allowed:
            return "NONE", 0.0
        return state_event, confidence
    
    def _is_time_reference_sleep(self, text: str) -> bool:
        raw = str(text or "").strip()
        if re.search(r"\d{1,2}[.:：]\d{2}\s*睡觉", raw):
            return True
        if re.search(r"\d{1,2}点\s*睡觉", raw):
            return True
        if re.search(r"(记录|记录的|写的|存的|显示|显示的|记的|编的|自己编的).{0,6}睡觉", raw):
            return True
        if re.search(r"睡觉.{0,4}(的时间|的时候|时间|时候)", raw):
            return True
        return False
    
    _PASSIVE_STUDY_PATTERNS = [
        r"也不知道",
        r"也不知道你",
        r"你.{0,4}(哪来|哪看到|从哪|怎么知道|怎么看到|谁告诉)",
        r"就算.{0,6}又怎么样",
        r"就算.{0,6}又怎样",
        r"那又.{0,4}(怎么样|怎样|如何)",
        r"(最|太|挺|蛮|真).{0,2}(简单|容易|基础|基本)",
        r"(不是|又不是|也不是|才不是).{0,6}(学习|学|复习|做题|考试|工作)",
        r"(没|没有|没在).{0,4}(学习|学|复习|做题|工作)",
        r"有什么.{0,4}(了不起|大不了|好说的|好炫耀)",
        r"谁说.{0,6}(学习|学|考|满分|成绩)",
        r"(这|那个|这个).{0,2}(是|算).{0,4}(最简单|最基础|最基本|最容易)",
    ]

    def _is_passive_study_mention(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        for pat in self._PASSIVE_STUDY_PATTERNS:
            if re.search(pat, raw):
                return True
        return False

    def _is_correction_context(self, text: str) -> bool:
        raw = str(text or "").strip()
        correction_patterns = [
            r"自己编的", r"编的", r"记错了", r"不是.*是",
            r"不对", r"更正", r"搞错了", r"弄错了", r"写错了",
            r"你.{0,4}(记错|搞错|弄错|写错|编|瞎|乱)",
        ]
        for pat in correction_patterns:
            if re.search(pat, raw):
                return True
        return False
