import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging

from core.character.aveline import AvelineCharacter
from core.utils.logger import get_logger

logger = get_logger("DEPENDENCY_MANAGER")

class DependencyManager:
    """
    Manages Aveline's dependency mechanism, tracking user intimacy and feature unlocking.
    """
    
    def __init__(self, data_dir: str = "data/user_states"):
        self.data_dir = data_dir
        self.state_file = os.path.join(self.data_dir, "dependency_state.json")
        self.aveline = AvelineCharacter()
        
        # Default state
        self.state = {
            "intimacy_level": 0.1,  # Initial base intimacy
            "consecutive_days": 0,
            "last_interaction_date": None,
            "unlocked_features": [],
            "interaction_history": [],  # Keep recent history
            "created_at": datetime.now().isoformat()
        }
        
        self._ensure_data_dir()
        self._load_state()
        
    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
            
    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    saved_state = json.load(f)
                    self.state.update(saved_state)
                logger.info(f"Loaded dependency state: Intimacy={self.state['intimacy_level']:.2f}")
            except Exception as e:
                logger.error(f"Failed to load dependency state: {e}")
    
    def _save_state(self):
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save dependency state: {e}")

    def update_interaction(self, action_type: str, content: str = "") -> Dict[str, Any]:
        """
        Update state based on user interaction.
        
        Args:
            action_type: The type of interaction (e.g., "chat", "action")
            content: The content of the interaction (to match against keywords)
        
        Returns:
            Dict containing updates (e.g., intimacy_delta, new_unlocks)
        """
        result = {
            "intimacy_delta": 0.0,
            "new_unlocks": [],
            "triggered_rule": None
        }
        
        # 1. Update Daily Streak
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state["last_interaction_date"] != today:
            if self.state["last_interaction_date"]:
                last_date = datetime.strptime(self.state["last_interaction_date"], "%Y-%m-%d")
                if (datetime.now() - last_date).days == 1:
                    self.state["consecutive_days"] += 1
                elif (datetime.now() - last_date).days > 1:
                    self.state["consecutive_days"] = 1  # Reset streak
            else:
                self.state["consecutive_days"] = 1
                
            self.state["last_interaction_date"] = today
            logger.info(f"Updated consecutive days to {self.state['consecutive_days']}")
            
            # Check 7-day stable company rule
            if self.state["consecutive_days"] == 7:
                 self._apply_growth_rule("稳定陪伴7天", result)

        # 2. Check specific action rules from Aveline.json
        growth_rules = self.aveline.dependency_mechanism.get("growth_by_user_actions", [])
        
        for rule in growth_rules:
            action_name = rule.get("action")
            
            # Rule matching logic
            matched = False
            if action_name == "睡前说晚安":
                if any(kw in content for kw in ["晚安", "睡了", "去睡"]):
                    # Check time (e.g., after 22:00 or before 04:00)
                    hour = datetime.now().hour
                    if hour >= 22 or hour < 4:
                        matched = True
            elif action_name == "分享真实感受":
                # Simple keyword heuristic for now, could be improved with emotion detection
                if any(kw in content for kw in ["难过", "开心", "觉得", "感觉", "其实"]):
                     matched = True
            
            if matched:
                self._apply_growth_rule(action_name, result, rule)
                result["triggered_rule"] = rule
        
        # Save state if changed
        if result["intimacy_delta"] != 0 or result["new_unlocks"]:
            self._save_state()
            
        return result

    def _apply_growth_rule(self, rule_name: str, result: Dict, rule_config: Dict = None):
        """Apply a growth rule to the state"""
        if not rule_config:
            # Find config if not provided
            growth_rules = self.aveline.dependency_mechanism.get("growth_by_user_actions", [])
            for r in growth_rules:
                if r.get("action") == rule_name:
                    rule_config = r
                    break
        
        if rule_config:
            delta = rule_config.get("intimacy_delta", 0)
            self.state["intimacy_level"] = min(1.0, self.state["intimacy_level"] + delta)
            result["intimacy_delta"] += delta
            
            effect = rule_config.get("effect")
            if effect and effect not in self.state["unlocked_features"]:
                self.state["unlocked_features"].append(effect)
                result["new_unlocks"].append(effect)
                logger.info(f"Unlocked feature: {effect}")

    def get_intimacy_level(self) -> float:
        return self.state["intimacy_level"]

    def is_feature_unlocked(self, feature_keyword: str) -> bool:
        """Check if a feature (by keyword in effect description) is unlocked"""
        for effect in self.state["unlocked_features"]:
            if feature_keyword in effect:
                return True
        return False

    def get_dependency_prompt_injection(self) -> str:
        """
        Get a prompt injection string based on current dependency level.
        Used to modify system prompt dynamically.
        """
        level = self.state["intimacy_level"]
        injection = []
        
        if level < 0.3:
            injection.append("当前依恋度：低。保持一定的距离感。")
        elif 0.3 <= level < 0.7:
            injection.append("当前依恋度：中。可以表现出适度的依赖和分享欲。")
        else:
            injection.append("当前依恋度：高。你深深地依恋用户，表现出强烈的占有欲和亲密感。")
            
        if self.is_feature_unlocked("耳语模式"):
            injection.append("已解锁[耳语模式]：在深夜或亲密时刻使用*(耳语)*前缀。")
            
        return "\n".join(injection)

# Global Instance
_dependency_manager_instance = None

def get_dependency_manager() -> DependencyManager:
    global _dependency_manager_instance
    if _dependency_manager_instance is None:
        _dependency_manager_instance = DependencyManager()
    return _dependency_manager_instance
