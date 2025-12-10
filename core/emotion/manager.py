import logging
from typing import Dict, Any, Optional, List
import time

from .models import EmotionType, EmotionState, EmotionResponse
from .detector import EmotionDetector
from .store import EmotionStore
from .responder import EmotionResponder
from .calculator import EmotionCalculator

logger = logging.getLogger(__name__)

class EmotionManager:
    """
    情绪模块的核心管理器 (Facade Pattern)
    负责协调检测、存储和响应生成。
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.detector = EmotionDetector(self.config)
        self.store = EmotionStore(self.config.get("data_dir", "data/emotions"))
        self.responder = EmotionResponder()
        self.calculator = EmotionCalculator(self.config)
        
        # 运行时状态缓存 {user_id: EmotionState}
        self._current_states: Dict[str, EmotionState] = {}

    def process_text(self, user_id: str, text: str) -> EmotionState:
        """
        处理用户输入/助手输出，检测情绪并更新状态
        """
        # 1. 检测本次文本的情绪
        detected_state = self.detector.detect(text)
        
        # 2. 获取当前状态并进行叠加计算
        current_state = self.get_current_state(user_id)
        
        # 如果是第一次，current_state 可能是默认的中性，置信度0
        # 如果 detected_state 很强 (例如 LLM 显式输出 [EMO: angry])，它应该主导
        
        new_state = self.calculator.update_state(current_state, detected_state)
        
        # 3. 更新缓存
        self._current_states[user_id] = new_state
        
        # 4. 记录历史
        record = {
            "timestamp": new_state.timestamp,
            "primary": new_state.primary_emotion.value,
            "confidence": new_state.confidence,
            "sub_emotions": new_state.sub_emotions,
            "text_snippet": text[:50] # 仅记录摘要
        }
        self.store.add_record(user_id, record)
        
        return new_state

    def get_current_state(self, user_id: str) -> EmotionState:
        return self._current_states.get(user_id, EmotionState(EmotionType.NEUTRAL, 0.0))

    def get_response_strategy(self, user_id: str, context: str = "") -> EmotionResponse:
        """
        获取针对当前情绪的响应策略
        """
        state = self.get_current_state(user_id)
        return self.responder.generate_response_strategy(state, context)

    # 单例模式支持
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = EmotionManager()
        return cls._instance

def get_emotion_manager() -> EmotionManager:
    return EmotionManager.get_instance()
