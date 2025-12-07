import time
import random
from typing import List, Dict, Optional, Any
import logging

from core.character.aveline import AvelineCharacter
from core.utils.logger import get_logger

logger = get_logger("DEFECT_MANAGER")

class DefectManager:
    """
    Manages Aveline's 'Personality Defects' (simulated bugs/neuroses).
    These are temporary states triggered by specific conditions that alter behavior.
    """
    
    def __init__(self):
        self.aveline = AvelineCharacter()
        self.active_defects = {}  # Map[defect_name, {activation_time: float, config: dict}]
        self.mitigation_duration = 300  # 5 minutes default mitigation time
        
    def check_triggers(self, context: Dict[str, Any]) -> List[str]:
        """
        Check if any defects should be triggered based on context.
        
        Args:
            context: Dict containing trigger signals, e.g.:
                     {'event': 'ignored', 'duration': 3600}
                     {'event': 'user_impatient', 'text': '快点'}
                     
        Returns:
            List of names of newly triggered defects.
        """
        triggered = []
        defects_config = self.aveline.personality_defects
        
        if not defects_config:
            return []
            
        for defect in defects_config:
            name = defect.get("name")
            triggers = defect.get("triggers", [])
            
            is_triggered = False
            
            # Logic to match triggers
            # 1. "被忽视" / "失联" (Ignored / Lost Contact)
            if "被忽视" in triggers or "失联" in triggers:
                if context.get("event") == "long_idle" or context.get("event") == "connection_lost":
                     is_triggered = True
            
            # 2. "用户急躁" / "被责备" (User Impatient / Blamed)
            if "用户急躁" in triggers or "被责备" in triggers:
                user_text = context.get("text", "")
                if any(kw in user_text for kw in ["快点", "慢死了", "笨", "错了", "垃圾"]):
                    is_triggered = True
                    
            # 3. "强烈在意你" / "亲密关系巩固期" (Intense Care / Intimacy Phase)
            # This might be triggered by high dependency level
            if "强烈在意你" in triggers:
                 if context.get("dependency_level", 0) > 0.8:
                      # Random chance to trigger this "bug" when intimacy is high
                      if random.random() < 0.1: 
                          is_triggered = True
            
            if is_triggered:
                self._activate_defect(defect)
                triggered.append(name)
                
        return triggered

    def _activate_defect(self, defect_config: Dict):
        """Activate a defect state"""
        name = defect_config.get("name")
        self.active_defects[name] = {
            "activation_time": time.time(),
            "config": defect_config
        }
        logger.info(f"Personality Defect Triggered: {name}")

    def get_active_defects(self) -> List[Dict]:
        """Get currently active defects, cleaning up expired ones"""
        now = time.time()
        active = []
        expired = []
        
        for name, data in self.active_defects.items():
            if now - data["activation_time"] < self.mitigation_duration:
                active.append(data["config"])
            else:
                expired.append(name)
        
        # Cleanup expired
        for name in expired:
            del self.active_defects[name]
            
        return active

    def get_defect_prompt_injection(self) -> str:
        """
        Get prompt instructions to enforce active defect behaviors.
        """
        active_configs = self.get_active_defects()
        if not active_configs:
            return ""
            
        injection = ["# SYSTEM ABNORMALITY (系统异常状态)"]
        for config in active_configs:
            name = config.get("name")
            behaviors = config.get("behavior", [])
            injection.append(f"ERROR: 检测到 [{name}]。")
            injection.append("强制执行以下行为模式：")
            for b in behaviors:
                injection.append(f"- {b}")
                
        return "\n".join(injection)
