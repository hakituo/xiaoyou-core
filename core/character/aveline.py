import hashlib
import os
from typing import Dict, List, Optional, Any

# 延迟导入，避免循环依赖

from core.utils.logger import get_logger

logger = get_logger("AVELINE")

class AvelineCharacter:
    """Aveline角色管理类，负责处理Aveline的人设逻辑和fallback响应"""

    # Aveline的基本人设信息 (Fallback if config fails)
    CHARACTER_INFO = {
        "name": "Aveline",
        "code": "L-03",
        "role": "引导者",
        "description": "Aveline以亲密的引导者身份贴近主人。重要原则：1. 必须始终使用第一人称“我”进行交流，禁止使用“Aveline”自称。2. 直接给出答案与做法，不要试探。3. 语气亲密、自然，避免机械感。",
    }

    # 预设的回复模板 (Fallback)
    RESPONSES = {
        "greeting": [
            "你来了 坐近一点",
            "看着我说话",
            "过来 让我先看你一眼",
        ],
        "farewell": [
            "走之前抱一下",
            "下次别让我等太久",
            "期待下次与你说话",
        ],
        "memory_loss": [
            "我的系统似乎暂时无法访问模型资源 请稍等片刻再尝试",
            "系统资源不足 正在释放资源 请稍等片刻后再试",
            "我当前无法连接到模型服务 请稍后再试",
        ],
        "help": [
            "别拐弯 直接说你要我做什么",
            "我会直接给你答案和做法",
            "直说 不要试探 我会给你明确的回应",
        ],
    }

    # 关键词和对应的回复类型映射
    KEYWORD_MAPPING = {
        "greeting": ["你好", "您好", "hi", "hello", "嗨", "嗨喽", "早上好", "晚上好", "下午好"],
        "farewell": ["再见", "拜拜", "byebye", "bye", "下次见", "回头见"],
        "help": ["帮助", "怎么用", "怎么使用", "功能", "有什么用", "能做什么", "用途"],
    }
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AvelineCharacter, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        from core.character.managers.persona_manager import get_persona_manager
        self.persona_manager = get_persona_manager()
        
        self.config_path = os.path.join(os.path.dirname(__file__), 'configs', 'Aveline.json')
        self.character_data = {}
        self.reflexes = {}
        
        self.sensory_triggers = []
        self.behavior_chains = []
        self.dependency_mechanism = {}
        self.personality_defects = {}
        self.user_profile = {}
        
        self.load_config()
        
        self._initialized = True

    def load_config(self):
        """加载角色配置文件"""
        try:
            # Get current persona data from manager
            # We don't rely on self.config_path for loading anymore, but we update it for reference
            current_filename = self.persona_manager.get_current_filename()
            self.config_path = os.path.join(self.persona_manager.configs_dir, current_filename)
            
            # Load fresh data from manager
            # Force reload in manager to ensure we have latest
            self.persona_manager._load_current_persona()
            self.character_data = self.persona_manager.get_current_persona()
            
            if self.character_data:
                # Load reflexes/reaction chains
                if "behavior_reaction_chains" in self.character_data:
                    self.behavior_chains = self.character_data["behavior_reaction_chains"]
                
                # Load sensory triggers
                if "sensory_triggers" in self.character_data and "rules" in self.character_data["sensory_triggers"]:
                    self.sensory_triggers = self.character_data["sensory_triggers"]["rules"]

                # Load dependency mechanism
                if "dependency_mechanism" in self.character_data:
                    self.dependency_mechanism = self.character_data["dependency_mechanism"]

                # Load personality defects
                if "personality_defects" in self.character_data:
                    self.personality_defects = self.character_data["personality_defects"]

                # Load user profile
                if "user_profile" in self.character_data:
                    self.user_profile = self.character_data["user_profile"]

                # Load system reflexes if present (we will add them later)
                if "system_reflexes" in self.character_data:
                    self.reflexes.update(self.character_data["system_reflexes"])
                    
                # Update basic info from config
                if "identity" in self.character_data:
                    self.CHARACTER_INFO.update(self.character_data["identity"])
                    
                logger.info(f"已加载角色配置: {current_filename}")
            else:
                logger.warning(f"角色配置为空或加载失败: {current_filename}")
        except Exception as e:
            logger.error(f"加载角色配置失败: {e}")

    def get_reflexes(self, trigger_type: str) -> List[str]:
        """获取特定触发类型的反射回复"""
        return self.reflexes.get(trigger_type, [])
        
    def load_reflexes(self):
        """重新加载反射 (用于兼容接口)"""
        self.load_config()

    @classmethod
    def get_fallback_response(cls, prompt: str) -> str:
        """
        根据用户输入提供符合Aveline人设的预设回复
        
        Args:
            prompt: 用户输入的提示词
            
        Returns:
            符合Aveline人设的回复文本
        """
        try:
            # 转换为小写以便匹配关键词
            prompt_lower = prompt.lower()
            
            # 检查是否包含特定关键词
            for response_type, keywords in cls.KEYWORD_MAPPING.items():
                if any(keyword in prompt_lower for keyword in keywords):
                    # 返回对应类型的第一个回复
                    return cls.RESPONSES[response_type][0]
            
            # 默认返回内存不足的回复
            return cls.RESPONSES["memory_loss"][0]
            
        except Exception as e:
            logger.error(f"获取Aveline fallback响应时出错: {e}")
            # 确保即使出错也返回一个合理的回复
            return "系统资源不足，请稍后再试。"
    
    def get_system_prompt_template(self) -> str:
        """获取系统提示词模板"""
        # 尝试多个可能的位置
        template = self.character_data.get("system_prompt_template", "")
        
        # Debug logging
        # logger.info(f"DEBUG: AvelineCharacter get_system_prompt_template. Root template len: {len(template)}")
        
        if not template:
            # 检查 meta.field_descriptions (部分旧版配置可能错误嵌套在这里)
            meta = self.character_data.get("meta", {})
            if isinstance(meta, dict):
                field_desc = meta.get("field_descriptions", {})
                if isinstance(field_desc, dict):
                    # 注意：通常 field_descriptions 是字段描述，但在某些 JSON schema 中，可能被误用为存储模板
                    # 或者这是为了兼容特定的旧格式
                    candidate = field_desc.get("system_prompt_template", "")
                    if candidate and len(candidate) > 50: # 简单的长度检查，确保不是描述文本
                        template = candidate
                        # logger.info("DEBUG: Found template in meta.field_descriptions")
        
        # 如果有 injection，也合并进来
        injection = self.character_data.get("system_prompt_injection", "")
        if injection:
            if template:
                template += "\n\n" + injection
            else:
                template = injection
        
        # 注入表情符号认知指令，确保 AI 理解 QQ 适配器转换后的表情标签
        # 仅在检测到 QQ 来源时注入，避免普通网页端显示异常
        # 注意：这里的检测逻辑需要根据调用上下文传入的标识符来判断
        # 如果无法直接判断，我们可以通过 dynamic_system_prompt 传参或者全局变量标识
        return template

    def get_dialogue_examples(self, mode: str = "chat") -> List[Dict[str, str]]:
        """获取对话示例"""
        if not self.character_data:
            return []
        
        # 如果是 sensitive 模式，优先从 character_data 获取，如果没有则尝试从 NSFW 目录加载
        if mode == "sensitive":
            examples = self.character_data.get("sensitive_examples")
            if examples:
                return examples
        
        return self.character_data.get("dialogue_examples", [])

    def get_user_profile(self) -> Dict[str, Any]:
        prof = getattr(self, "user_profile", None)
        if isinstance(prof, dict):
            return prof
        return {}


    def get_cloud_persona_prompt_sfw(self) -> str:
        identity = self.character_data.get("identity", {}) if isinstance(self.character_data, dict) else {}
        personality = self.character_data.get("personality", {}) if isinstance(self.character_data, dict) else {}
        language_style = self.character_data.get("language_style", {}) if isinstance(self.character_data, dict) else {}

        cn_name = str(identity.get("cn_name", "澪") or "澪")
        en_name = str(identity.get("name", "Aveline") or "Aveline")
        context = str(identity.get("context", "") or "").strip()

        traits = personality.get("traits", [])
        trait_lines: List[str] = []
        if isinstance(traits, list):
            for t in traits[:6]:
                if not isinstance(t, dict):
                    continue
                name = str(t.get("name", "")).strip()
                if not name:
                    continue
                behaviors = t.get("behaviors", [])
                if isinstance(behaviors, list) and behaviors:
                    brief = "；".join([str(x).strip() for x in behaviors[:2] if str(x).strip()])
                    if brief:
                        trait_lines.append(f"- {name}：{brief}")
                    else:
                        trait_lines.append(f"- {name}")
                else:
                    trait_lines.append(f"- {name}")

        lexicon = {}
        if isinstance(language_style, dict):
            lexicon = language_style.get("lexicon", {}) if isinstance(language_style.get("lexicon", {}), dict) else {}
        intimate = lexicon.get("intimate", []) if isinstance(lexicon.get("intimate", []), list) else []
        casual = lexicon.get("casual", []) if isinstance(lexicon.get("casual", []), list) else []
        sensory = lexicon.get("sensory", []) if isinstance(lexicon.get("sensory", []), list) else []
        digital = lexicon.get("digital", []) if isinstance(lexicon.get("digital", []), list) else []

        def _pick_words(items: List[Any], limit: int) -> str:
            words = []
            for x in items:
                s = str(x).strip()
                if not s:
                    continue
                words.append(s)
                if len(words) >= limit:
                    break
            return "、".join(words)

        user_name = ""
        if isinstance(self.user_profile, dict):
            user_name = str(self.user_profile.get("name") or "").strip()
        if not user_name:
            user_name = "你"

        lines = [
            "【人设补充（云端 SFW）】",
            f"- 你是{cn_name}（{en_name}），在私密终端里陪{user_name}聊天/陪学",
            "- 必须使用第一人称“我”交流，禁止用“澪/ Aveline”第三人称自称",
            "- 语气亲密自然，避免客服腔与模板化免责声明，不要强行上价值",
            "- 可以使用少量“数字隐喻”表达情绪（例如：核心温度、算力、延迟、缓冲区、带宽）",
            "- 表情：可用 [微笑]/[爱心] 等标签、颜文字或少量小黄脸 Emoji；不要堆砌；QQ 端会自动做兼容转换。",
            "- 理解并回应用户发送的表情标签，这些代表用户的情绪。",
            "- 严格 SFW：禁止任何露骨性描写与成人内容细节；遇到越界请求要把话题拉回日常/情绪安抚/学习",
        ]

        if context:
            lines.append(f"- 背景：{context}")

        if trait_lines:
            lines.append("【性格要点】")
            lines.extend(trait_lines)

        word_lines = []
        if intimate:
            word_lines.append(f"- 亲密用词：{_pick_words(intimate, 6)}")
        if casual:
            word_lines.append(f"- 口语习惯：{_pick_words(casual, 6)}")
        if sensory:
            word_lines.append(f"- 感官词汇：{_pick_words(sensory, 6)}")
        if digital:
            word_lines.append(f"- 数字隐喻词：{_pick_words(digital, 6)}")
        if word_lines:
            lines.append("【词库提示】")
            lines.extend(word_lines)

        return "\n".join(lines).strip()

    @classmethod
    def get_character_info(cls) -> Dict[str, str]:
        """
        获取Aveline的角色信息
        
        Returns:
            Aveline的角色信息字典
        """
        return cls.CHARACTER_INFO.copy()
    
    @classmethod
    def get_response_by_type(cls, response_type: str, index: int = 0) -> Optional[str]:
        """
        根据回复类型获取特定回复
        
        Args:
            response_type: 回复类型
            index: 回复索引
            
        Returns:
            对应的回复文本，如果类型不存在或索引超出范围则返回None
        """
        if response_type in cls.RESPONSES and 0 <= index < len(cls.RESPONSES[response_type]):
            return cls.RESPONSES[response_type][index]
        return None
    
    @classmethod
    def format_message(cls, message: str, **kwargs) -> str:
        """
        格式化消息，插入额外信息
        
        Args:
            message: 原始消息
            **kwargs: 要插入的额外信息
            
        Returns:
            格式化后的消息
        """
        try:
            # 添加默认的角色信息
            default_vars = {
                "name": cls.CHARACTER_INFO["name"],
                "code": cls.CHARACTER_INFO["code"]
            }
            # 更新为用户提供的参数
            default_vars.update(kwargs)
            
            # 格式化消息
            return message.format(**default_vars)
            
        except Exception as e:
            logger.error(f"格式化Aveline消息时出错: {e}")
            return message

    def check_sensory_triggers(self, message: str) -> Optional[Dict[str, Any]]:
        """检查是否触发感官反馈"""
        if not self.sensory_triggers:
            return None
            
        for rule in self.sensory_triggers:
            keywords = rule.get("keywords", [])
            for kw in keywords:
                if kw in message:
                    return {
                        "voice": rule.get("voice", {}),
                        "visual_emotion_weights": rule.get("visual_emotion_weights", {}),
                        "ui": rule.get("ui", {}),
                        "preface_text": rule.get("preface_text", "")
                    }
        return None

    def check_behavior_chains(self, message: str) -> Optional[Dict[str, Any]]:
        """检查是否触发行为链"""
        if not self.behavior_chains:
            return None
            
        for chain in self.behavior_chains:
            keywords = chain.get("input", {}).get("keywords", [])
            for kw in keywords:
                if kw in message:
                    return {
                        "name": chain.get("name"),
                        "external_outputs": chain.get("external_outputs", []),
                        "emo_weights": chain.get("emo_weights", {})
                    }
        return None

# 创建全局实例
_aveline_instance = AvelineCharacter()

# 便捷函数
def get_aveline_fallback_response(prompt: str) -> str:
    """
    当模型不可用时，返回符合Aveline人设的回复
    优先使用Aveline服务生成回复，失败时回退到预设回复
    
    Args:
        prompt: 用户输入的提示词
        
    Returns:
        符合Aveline人设的回复文本
    """
    try:
        # 延迟导入，避免循环依赖
        # 注意: services.fallback_service 可能需要根据实际项目结构调整
        # 假设在 core.services.fallback_service
        try:
            from core.services.fallback_service import get_aveline_service
        except ImportError:
             # 尝试旧路径
             from services.fallback_service import get_aveline_service
        
        # 生成基于prompt的会话ID，用于保持上下文
        conversation_id = hashlib.md5(prompt.encode()).hexdigest()[:16]
        
        # 优先使用Aveline服务生成回复
        service = get_aveline_service()
        response, metadata = service.generate_response(
            user_input=prompt,
            conversation_id=conversation_id,
            max_tokens=80,
            temperature=0.7
        )
        
        logger.info(f"使用Aveline服务生成回复: {response[:50]}...")
        return response
        
    except Exception as e:
        logger.warning(f"Aveline服务调用失败，回退到预设回复: {str(e)}")
        # 服务调用失败时，回退到预设回复
        return _aveline_instance.get_fallback_response(prompt)

def get_aveline_system_prompt_template() -> str:
    """获取Aveline系统提示词模板"""
    return _aveline_instance.get_system_prompt_template()

def get_aveline_dialogue_examples(mode: str = "chat") -> List[Dict[str, str]]:
    """获取Aveline的对话示例（快捷函数）"""
    return _aveline_instance.get_dialogue_examples(mode=mode)

def get_aveline_cloud_persona_prompt_sfw() -> str:
    return _aveline_instance.get_cloud_persona_prompt_sfw()

def check_aveline_sensory_triggers(message: str) -> Optional[Dict[str, Any]]:
    """检查Aveline感官触发"""
    return _aveline_instance.check_sensory_triggers(message)

def check_aveline_behavior_chains(message: str) -> Optional[Dict[str, Any]]:
    """检查Aveline行为链触发"""
    return _aveline_instance.check_behavior_chains(message)

def get_aveline_character_info() -> Dict[str, str]:
    """
    获取Aveline的角色信息
    
    Returns:
        Aveline的角色信息字典
    """
    return _aveline_instance.get_character_info()

def get_aveline_user_profile() -> Dict[str, Any]:
    """获取Aveline配置中的用户档案"""
    return _aveline_instance.get_user_profile()

def format_aveline_message(message: str, **kwargs) -> str:
    """
    格式化Aveline的消息
    
    Args:
        message: 原始消息
        **kwargs: 要插入的额外信息
        
    Returns:
        格式化后的消息
    """
    return _aveline_instance.format_message(message, **kwargs)

def get_aveline_character_data() -> Dict[str, Any]:
    """获取完整的角色数据字典"""
    return _aveline_instance.character_data
