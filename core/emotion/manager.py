
from core.utils.logger import get_logger
import random
import threading
from typing import Dict, Any, Optional, List, Callable

from .models import (
    EmotionType,
    EmotionState,
    EmotionInfluence,
    EmotionDebugSnapshot,
    DialogueAffectContext,
    ResponseStrategy,
)
from .detector_v2 import EmotionDetectorV2
from .store import EmotionStore
from .calculator import EmotionCalculator
from .constants import EMOTION_CN_MAP, EMOTION_COLOR_MAP, EMOTION_BREATHING_RATE_MAP

logger = get_logger(__name__)

_NEGATIVE_INSOMNIA_EMOTIONS = frozenset({
    EmotionType.ANXIOUS, EmotionType.SAD,
    EmotionType.LONELY, EmotionType.FEAR,
})


class EmotionManager:
    """
    情绪模块核心管理器 (Facade Pattern)
    支持两种检测模式：
    1. Legacy: LLM 标签提取 ([EMO: sad])
    2. Smart: 关键词 + BERT 零样本分类（默认）
    
    配置项：
    - enabled: 模块总开关（false=完全禁用）
    - detector_mode: 检测模式 (smart/legacy)
    - affect_prompt_enabled: 是否注入情绪prompt
    - hardware_control_enabled: 是否控制硬件
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # 模块总开关
        self._enabled = self.config.get("enabled", True)
        
        # 子功能开关
        self._affect_prompt_enabled = self.config.get("affect_prompt_enabled", True)
        self._hardware_control_enabled = self.config.get("hardware_control_enabled", True)
        
        # 如果模块禁用，不初始化其他组件
        if not self._enabled:
            logger.info("Emotion module is DISABLED via config")
            self.detector = None
            self.store = None
            self.calculator = None
            self._current_states = {}
            self._recent_influences = {}
            self._global_state = EmotionState(EmotionType.NEUTRAL, 0.0)
            self._global_influences = []
            self._lock = threading.RLock()
            self._rng = random.random
            return
        
        self._detector_mode = self.config.get("detector_mode", "smart")

        if self._detector_mode == "legacy":
            self.detector = EmotionDetectorV2(self.config)
        else:
            from .detector_smart import get_emotion_detector_smart
            self.detector = get_emotion_detector_smart()

        self.store = EmotionStore(self.config.get("data_dir", "data/emotions"))
        self.calculator = EmotionCalculator(self.config)

        self._current_states: Dict[str, EmotionState] = {}
        self._recent_influences: Dict[str, List[EmotionInfluence]] = {}
        self._max_recent_influences = int(
            self.config.get("max_recent_influences", 32) or 32
        )

        self._global_state = EmotionState(EmotionType.NEUTRAL, 0.0)
        self._global_influences: List[EmotionInfluence] = []
        self._lock = threading.RLock()
        self._rng: Callable[[], float] = random.random
        
        logger.info(f"Emotion module enabled, mode={self._detector_mode}")

    def is_enabled(self) -> bool:
        """检查模块是否启用"""
        return self._enabled
    
    def is_affect_prompt_enabled(self) -> bool:
        """检查是否启用情绪prompt注入"""
        return self._enabled and self._affect_prompt_enabled
    
    def is_hardware_control_enabled(self) -> bool:
        """检查是否启用硬件控制"""
        return self._enabled and self._hardware_control_enabled

    def process_text(self, user_id: str, text: str) -> EmotionState:
        # 模块禁用时返回默认状态
        if not self._enabled:
            return EmotionState(EmotionType.NEUTRAL, 0.0)
        
        detected_state = self.detector.detect(text)
        with self._lock:
            current_state = self._get_current_state_unlocked(user_id)
            new_state = self.calculator.update_state(current_state, detected_state)
            self._current_states[user_id] = new_state

        record = {
            "timestamp": new_state.timestamp,
            "primary": new_state.primary_emotion.value,
            "confidence": new_state.confidence,
            "sub_emotions": new_state.sub_emotions,
            "text_snippet": text[:50],
        }
        self.store.add_record(user_id, record)
        return new_state

    def apply_influence(
        self,
        user_id: str,
        weights: Dict[str, float],
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EmotionState:
        # 模块禁用时返回默认状态
        if not self._enabled:
            return EmotionState(EmotionType.NEUTRAL, 0.0)
        
        normalized = self._normalize_weights(weights)
        if not normalized:
            return self.get_current_state(user_id)

        influence_state = self._weights_to_state(normalized)
        with self._lock:
            current_state = self._get_current_state_unlocked(user_id)
            new_state = self.calculator.update_state(current_state, influence_state)
            self._current_states[user_id] = new_state

            infl = EmotionInfluence(
                source=str(source or "unknown"),
                weights=normalized,
                metadata=metadata or {},
            )
            history = self._recent_influences.setdefault(user_id, [])
            history.append(infl)
            if len(history) > self._max_recent_influences:
                del history[: len(history) - self._max_recent_influences]

        return new_state

    def ingest_life_stats(
        self,
        user_id: str,
        life_stats: Dict[str, Any],
        intimacy_level: Optional[float] = None,
    ) -> EmotionState:
        # 模块禁用时返回默认状态
        if not self._enabled:
            return EmotionState(EmotionType.NEUTRAL, 0.0)
        
        weights, mood_score, shyness_score, immune_damage, is_sick = (
            self._life_stats_to_weights(life_stats, intimacy_level)
        )
        return self.apply_influence(
            user_id,
            weights,
            source="life_simulation",
            metadata={
                "mood_score": mood_score,
                "shyness_score": shyness_score,
                "immune_damage": immune_damage,
                "is_sick": is_sick,
                "intimacy_level": intimacy_level,
            },
        )

    def apply_global_influence(
        self,
        weights: Dict[str, float],
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EmotionState:
        # 模块禁用时返回默认状态
        if not self._enabled:
            return EmotionState(EmotionType.NEUTRAL, 0.0)
        
        normalized = self._normalize_weights(weights)
        if not normalized:
            with self._lock:
                return self._global_state

        influence_state = self._weights_to_state(normalized)
        with self._lock:
            self._global_state = self._merge_states_no_decay(
                self._global_state, influence_state
            )
            self._global_influences.append(
                EmotionInfluence(
                    source=str(source or "unknown"),
                    weights=normalized,
                    metadata=metadata or {},
                )
            )
            if len(self._global_influences) > self._max_recent_influences:
                del self._global_influences[
                    : len(self._global_influences) - self._max_recent_influences
                ]
            return self._global_state

    def compute_life_influence_weights(
        self,
        life_stats: Dict[str, Any],
        intimacy_level: Optional[float] = None,
    ) -> Dict[str, float]:
        weights, _, _, _, _ = self._life_stats_to_weights(life_stats, intimacy_level)
        return weights

    def get_effective_state(self, user_id: str) -> EmotionState:
        with self._lock:
            user_state = self._get_current_state_unlocked(user_id)
            return self._merge_states_no_decay(self._global_state, user_state)

    def get_effective_payload(self, user_id: str) -> Dict[str, Any]:
        state = self.get_effective_state(user_id)
        return {
            "primary_emotion": state.primary_emotion.value,
            "intensity": float(state.intensity or 0.0),
            "confidence": float(state.confidence or 0.0),
            "sub_emotions": dict(state.sub_emotions or {}),
        }

    def get_hardware_payload(self, user_id: str) -> Dict[str, Any]:
        # 模块禁用或硬件控制禁用时返回空
        if not self._enabled or not self._hardware_control_enabled:
            return {}
        
        state = self.get_effective_state(user_id)
        emo = state.primary_emotion
        color = EMOTION_COLOR_MAP.get(emo, "#FFFFFF")
        breathing_rate = EMOTION_BREATHING_RATE_MAP.get(emo, 4000)
        return {
            "light": {
                "color": [
                    int(color[1:3], 16),
                    int(color[3:5], 16),
                    int(color[5:7], 16),
                ],
                "mode": "breathing",
                "interval": breathing_rate,
                "brightness": state.intensity,
            },
            "emotion": emo.value,
            "intensity": state.intensity,
        }

    def get_response_strategy(self, user_id: str) -> Optional[ResponseStrategy]:
        # 模块禁用时返回 None
        if not self._enabled:
            return None
        
        state = self.get_effective_state(user_id)
        hw_payload = self.get_hardware_payload(user_id)
        return ResponseStrategy(
            emotion=state.primary_emotion,
            intensity=state.intensity,
            metadata={"hardware_intent": _HardwareIntent(hw_payload)} if hw_payload else {},
        )

    def build_dialogue_affect_instruction(
        self,
        *,
        user_id: str = "",
        life_level: int = 5,
        mood_score: float = 80.0,
        shyness_score: float = 0.0,
        immune_damage: float = 0.0,
        is_sick: bool = False,
        intimacy_level: float = 0.5,
        soft_reply_char_limit: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        # 模块禁用或prompt注入禁用时返回空字符串
        if not self._enabled or not self._affect_prompt_enabled:
            return ""
        
        ctx = DialogueAffectContext(
            life_level=life_level,
            mood_score=mood_score,
            shyness_score=shyness_score,
            immune_damage=immune_damage,
            is_sick=is_sick,
            intimacy_level=intimacy_level,
            soft_reply_char_limit=soft_reply_char_limit,
            max_tokens=max_tokens,
        )
        return self._build_affect_instruction(user_id, ctx)

    def build_dialogue_affect_instruction_from_ctx(
        self, user_id: str, ctx: DialogueAffectContext
    ) -> str:
        return self._build_affect_instruction(user_id, ctx)

    def _build_affect_instruction(
        self, user_id: str, ctx: DialogueAffectContext
    ) -> str:
        # 精简版：只给自然语言描述，不给数字指标
        parts = []
        
        if ctx.is_sick:
            parts.append("你身体不太舒服")
        
        emotion_simple = self._resolve_emotion_desc_simple(user_id)
        if emotion_simple:
            parts.append(emotion_simple)
        
        warmth = self._resolve_warmth(ctx.intimacy_level, ctx.mood_score)
        warmth_map = {
            "语气更克制，短句，低意愿": "语气克制点",
            "语气更克制，少用亲昵称呼": "语气克制点",
            "语气更温和，适度亲近": "语气温和点",
            "语气更亲近，更主动表达关心": "语气亲近点",
        }
        warmth_short = warmth_map.get(warmth, warmth)
        
        if parts:
            return "，".join(parts) + "，" + warmth_short + "。"
        elif warmth_short:
            return warmth_short + "。"
        return ""

    def _resolve_emotion_desc_simple(self, user_id: str) -> str:
        """精简版情绪描述，不给百分比数字"""
        if not user_id:
            return ""
        try:
            state = self.get_effective_state(user_id)
            if (
                state
                and state.primary_emotion != EmotionType.NEUTRAL
                and state.intensity > 0.3
            ):
                cn = EMOTION_CN_MAP.get(
                    state.primary_emotion.value, state.primary_emotion.value
                )
                return f"现在有点{cn}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _resolve_warmth(intimacy_level: float, mood_score: float) -> str:
        if mood_score < 25:
            return "语气更克制，短句，低意愿"
        if intimacy_level < 0.3:
            return "语气更克制，少用亲昵称呼"
        if intimacy_level < 0.7:
            return "语气更温和，适度亲近"
        return "语气更亲近，更主动表达关心"

    @staticmethod
    def _resolve_length(
        soft_reply_char_limit: Optional[int],
        max_tokens: Optional[int],
    ) -> str:
        if soft_reply_char_limit:
            return f"回复请尽量保持在{soft_reply_char_limit}字以内，保持自然，不要刻意截断。"
        if max_tokens:
            if max_tokens <= 150:
                return "回复请保持简短自然，不要刻意截断句子。"
            if max_tokens <= 350:
                return "回复请保持简洁，控制在80字左右。"
            if max_tokens >= 800:
                return "回复可以详细一些，不需要刻意控制字数，多说一点。"
        return ""

    def _resolve_emotion_desc(self, user_id: str) -> str:
        if not user_id:
            return ""
        try:
            state = self.get_effective_state(user_id)
            if (
                state
                and state.primary_emotion != EmotionType.NEUTRAL
                and state.intensity > 0.3
            ):
                cn = EMOTION_CN_MAP.get(
                    state.primary_emotion.value, state.primary_emotion.value
                )
                pct = int(round(state.intensity * 100))
                return f"当前情绪{cn}({pct}%)"
        except Exception:
            pass
        return ""

    def get_debug_snapshot(self, user_id: str) -> EmotionDebugSnapshot:
        state = self.get_effective_state(user_id)
        with self._lock:
            influences = list(self._global_influences) + list(
                self._recent_influences.get(user_id, []) or []
            )
        return EmotionDebugSnapshot(
            primary_emotion=state.primary_emotion,
            confidence=state.confidence,
            sub_emotions=dict(state.sub_emotions or {}),
            influences=influences,
        )

    def check_insomnia_risk(
        self, user_id: str, life_stats: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        state = self.get_effective_state(user_id)
        primary = state.primary_emotion
        intensity = state.intensity

        base_risk = 0.0
        reason = "none"
        insomnia_type = "none"

        if primary in _NEGATIVE_INSOMNIA_EMOTIONS and intensity > 0.6:
            base_risk += 0.4
            reason = f"feeling very {primary.value}"
            insomnia_type = "anxiety"

        if life_stats:
            energy = float(life_stats.get("energy", 50))
            if energy > 85:
                base_risk += 0.2
                if insomnia_type == "none":
                    reason = "too much energy"
                    insomnia_type = "energy"
            elif energy > 70:
                base_risk += 0.1

        nightmare_chance = 0.02
        if self._rng() < nightmare_chance:
            return {
                "is_insomniac": True,
                "risk_score": 1.0,
                "reason": "had a nightmare",
                "type": "nightmare",
            }

        is_insomniac = self._rng() < base_risk

        if is_insomniac and insomnia_type == "none":
            insomnia_type = "anxiety"
            reason = "general restlessness"

        return {
            "is_insomniac": is_insomniac,
            "risk_score": base_risk,
            "reason": reason,
            "type": insomnia_type,
        }

    def _weights_to_state(self, normalized: Dict[str, float]) -> EmotionState:
        primary_key, primary_val = self._pick_primary(normalized)
        try:
            primary = EmotionType(str(primary_key))
        except Exception:
            primary = EmotionType.NEUTRAL

        clamped = max(0.0, min(1.0, primary_val))
        return EmotionState(
            primary_emotion=primary,
            confidence=clamped,
            sub_emotions=normalized,
            emotion_mix=dict(normalized),
            intensity=clamped,
        )

    @staticmethod
    def _pick_primary(weights: Dict[str, float]) -> tuple:
        if not weights:
            return EmotionType.NEUTRAL.value, 0.0
        key = max(weights.items(), key=lambda kv: kv[1])[0]
        return key, float(weights.get(key, 0.0) or 0.0)

    def _life_stats_to_weights(
        self,
        life_stats: Dict[str, Any],
        intimacy_level: Optional[float],
    ) -> tuple:
        weights: Dict[str, float] = {}

        mood_score = float(life_stats.get("mood_score", 80.0) or 80.0)
        shyness_score = float(life_stats.get("shyness_score", 0.0) or 0.0)
        immune_damage = float(life_stats.get("immune_damage", 0.0) or 0.0)
        is_sick = bool(life_stats.get("is_sick", False))

        if mood_score <= 20:
            weights[EmotionType.LOST.value] = 0.85
            weights[EmotionType.SAD.value] = 0.55
        elif mood_score <= 40:
            weights[EmotionType.SAD.value] = 0.65
        elif mood_score >= 85:
            weights[EmotionType.HAPPY.value] = 0.65
            weights[EmotionType.EXCITED.value] = 0.35
        elif mood_score >= 70:
            weights[EmotionType.HAPPY.value] = 0.45

        if shyness_score >= 70:
            shy_w = 0.25 + min(0.55, (shyness_score - 70.0) / 30.0 * 0.55)
            weights[EmotionType.SHY.value] = shy_w

        if is_sick or immune_damage >= 50:
            tired_w = 0.25
            if immune_damage > 50:
                tired_w = min(0.75, tired_w + (immune_damage - 50.0) / 50.0 * 0.5)
            weights[EmotionType.TIRED.value] = tired_w
            weights[EmotionType.ANXIOUS.value] = 0.25

        if intimacy_level is not None:
            lvl = float(intimacy_level or 0.0)
            if lvl >= 0.8:
                weights[EmotionType.COQUETRY.value] = 0.45
            elif lvl >= 0.6:
                weights[EmotionType.SHY.value] = max(
                    weights.get(EmotionType.SHY.value, 0.0), 0.20
                )

        return weights, mood_score, shyness_score, immune_damage, is_sick

    def _merge_states_no_decay(self, a: EmotionState, b: EmotionState) -> EmotionState:
        merged: Dict[str, float] = {}
        for k, v in (a.sub_emotions or {}).items():
            merged[str(k)] = float(v)
        for k, v in (b.sub_emotions or {}).items():
            try:
                vv = float(v)
            except Exception:
                continue
            if vv <= 0:
                continue
            merged[str(k)] = max(float(merged.get(str(k), 0.0)), vv)

        merged = self._normalize_weights(merged)
        if not merged:
            return EmotionState(EmotionType.NEUTRAL, 0.0)

        primary_key, primary_val = self._pick_primary(merged)
        try:
            primary = EmotionType(str(primary_key))
        except Exception:
            primary = EmotionType.NEUTRAL

        clamped = max(0.0, min(1.0, primary_val))
        return EmotionState(
            primary_emotion=primary,
            confidence=clamped,
            sub_emotions=merged,
            emotion_mix=dict(merged),
            intensity=clamped,
        )

    @staticmethod
    def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
        cleaned: Dict[str, float] = {}
        for k, v in (weights or {}).items():
            if k is None:
                continue
            try:
                vv = float(v)
            except Exception:
                continue
            if vv <= 0:
                continue
            cleaned[str(k)] = max(0.0, min(1.0, vv))

        if not cleaned:
            return {}

        total = sum(cleaned.values())
        if total <= 0:
            return {}

        if total > 1.0:
            cleaned = {k: v / total for k, v in cleaned.items()}

        return cleaned

    def get_current_state(self, user_id: str) -> EmotionState:
        with self._lock:
            return self._get_current_state_unlocked(user_id)

    def _get_current_state_unlocked(self, user_id: str) -> EmotionState:
        return self._current_states.get(user_id, EmotionState(EmotionType.NEUTRAL, 0.0))

    _instance = None
    _instance_lock = threading.Lock()
    _instance_config = None

    @classmethod
    def get_instance(cls, config: Optional[Dict[str, Any]] = None):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    # 如果没有传入配置，尝试从 app.yaml 加载
                    if config is None and cls._instance_config is None:
                        config = cls._load_config_from_yaml()
                    cls._instance = EmotionManager(config or cls._instance_config)
        return cls._instance
    
    @classmethod
    def _load_config_from_yaml(cls) -> Dict[str, Any]:
        """从 app.yaml 加载 emotion 配置"""
        try:
            from config.integrated_config import get_settings
            settings = get_settings()
            # 尝试从 settings 中获取 emotion 配置
            emotion_config = getattr(settings, 'emotion', None)
            if emotion_config:
                if hasattr(emotion_config, '__dict__'):
                    return {k: v for k, v in emotion_config.__dict__.items() if not k.startswith('_')}
                elif isinstance(emotion_config, dict):
                    return emotion_config
        except Exception as e:
            logger.debug(f"Failed to load emotion config from yaml: {e}")
        return {}

    @classmethod
    def set_config(cls, config: Dict[str, Any]):
        """设置配置（在初始化前调用）"""
        cls._instance_config = config


class _HardwareIntent:
    """硬件控制意图，兼容 handler.py 中的 to_dict() 调用"""

    __slots__ = ("_payload",)

    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._payload)


def get_emotion_manager(config: Optional[Dict[str, Any]] = None) -> EmotionManager:
    return EmotionManager.get_instance(config)
