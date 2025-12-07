import asyncio
import json
import random
import os
from typing import Dict, List, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from core.llm import get_llm_module, LLMConfig, create_instance
from core.utils.logger import get_logger
# from memory.memory_manager import MemoryManager
from memory.weighted_memory_manager import WeightedMemoryManager
from memory.emotion_responder import EmotionResponder

# 修正导入路径，不再使用已不存在的 aveline_manager
# 使用 core.character.aveline 中的 AvelineCharacter 获取信息
from core.character.aveline import get_aveline_character_info, get_aveline_system_prompt_template, check_aveline_sensory_triggers, check_aveline_behavior_chains, get_aveline_user_profile
from core.character.managers.dependency_manager import DependencyManager
from core.character.managers.defect_manager import DefectManager
from core.services.life_simulation.service import get_life_simulation_service
import psutil

logger = get_logger("ChatAgent")

@dataclass
class AgentConfig:
    """
    Agent配置类
    """
    agent_name: str = "default_chat_agent"
    system_prompt: str = "你是一个助手，请用中文回答用户问题。"
    max_history_length: int = 10
    temperature: float = 0.7

class ChatAgent:
    """
    聊天Agent类，负责处理用户消息并生成响应
    """
    def __init__(self, config: Optional[AgentConfig] = None):
        """
        初始化ChatAgent
        Args:
            config: Agent配置
        """
        self.config = config or AgentConfig()
        self.memory_manager = None
        self.emotion_responder = None
        self.dependency_manager = None
        self.defect_manager = None
        self.llm_module = None
        self.is_initialized = False
        self.memory_echoes = []
        self._lock = asyncio.Lock()

    async def initialize(self):
        """
        初始化Agent，加载必要的组件
        """
        async with self._lock:
            if self.is_initialized:
                return
            logger.info(f"初始化ChatAgent: {self.config.agent_name}")
            # 初始化内存管理器 - 切换至 WeightedMemoryManager 以支持高级功能
            try:
                self.memory_manager = WeightedMemoryManager(
                    user_id="default",  # 默认用户，后续可扩展
                    max_short_term=self.config.max_history_length,
                    max_long_term=100, # 长期记忆容量
                    auto_save_interval=300
                )
                logger.info("已启用增强型权重记忆管理器 (WeightedMemoryManager)")
            except Exception as e:
                logger.error(f"初始化权重记忆管理器失败，降级使用基础管理器: {e}")
                from memory.memory_manager import MemoryManager
                self.memory_manager = MemoryManager()
                
            # 初始化情绪响应器
            try:
                self.emotion_responder = EmotionResponder()
                logger.info("已初始化情绪响应器")
            except Exception as e:
                logger.warning(f"初始化情绪响应器失败: {e}")

            # 初始化依恋与缺陷管理器
            try:
                self.dependency_manager = DependencyManager()
                self.defect_manager = DefectManager()
                logger.info("已初始化依恋与缺陷管理器")
            except Exception as e:
                logger.warning(f"初始化依恋/缺陷管理器失败: {e}")

            if hasattr(self.memory_manager, "initialize"):
                await self.memory_manager.initialize()
            
            # 加载记忆回响
            try:
                echoes_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'character', 'special_events.json')
                if os.path.exists(echoes_path):
                    with open(echoes_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.memory_echoes = data.get('events', [])
                    logger.info(f"已加载 {len(self.memory_echoes)} 条记忆回响")
            except Exception as e:
                logger.warning(f"加载记忆回响失败: {e}")
                
            # 初始化LLM模块
            self.llm_module = get_llm_module()
            await self.llm_module.initialize()
            
            # 从Aveline角色管理器获取角色配置，更新系统提示词
            try:
                # 获取完整的系统提示词模板
                prompt_template = get_aveline_system_prompt_template()
                if prompt_template:
                    self.config.system_prompt = prompt_template
                    logger.info("已加载Aveline完整系统提示词模板")
                else:
                    # Fallback to simple construction if template is missing
                    character_info = get_aveline_character_info()
                    if character_info:
                        prompt_template = f"你的名字是{character_info.get('name')}，代号{character_info.get('code')}。你的角色是{character_info.get('role')}。{character_info.get('description')}"
                        self.config.system_prompt = prompt_template
                        logger.info("已使用Aveline基础信息更新系统提示词")
            except Exception as e:
                logger.warning(f"获取Aveline角色配置失败: {str(e)}")

            # 检查并创建默认LLM实例
            llm_status = self.llm_module.get_status()
            if llm_status.get("llm_status", {}).get("instances_count", 0) == 0:
                logger.info("未找到LLM实例，创建默认LLM实例...")
                config = LLMConfig(
                    model_name="default",
                    device="auto",
                    max_context_length=2048,
                    temperature=self.config.temperature
                )
                await create_instance("default_llm", config)
            self.is_initialized = True
            logger.info(f"ChatAgent初始化完成: {self.config.agent_name}")

    async def handle_message(self, user_id, message, message_id):
        """
        处理用户消息
        Args:
            user_id: 用户ID
            message: 用户消息
            message_id: 消息ID
        Returns:
            响应字典
        """
        if not self.is_initialized:
            await self.initialize()

        # 更新生活模拟的交互时间
        try:
            get_life_simulation_service().update_interaction()
        except Exception:
            pass

        try:
            # 生成消息ID
            if not message_id:
                message_id = f"msg_{user_id}_{datetime.now().timestamp()}"
            logger.info(f"处理用户 {user_id} 的消息，ID: {message_id}")
            # 构建对话历史
            messages = await self._build_conversation_history(user_id, message)
            # 调用LLM生成响应
            response_content = await self.llm_module.chat(messages, temperature=self.config.temperature)
            # 保存对话到历史记录
            await self._save_conversation_history(user_id, message, response_content, message_id)
            logger.info(f"为用户 {user_id} 生成响应，消息ID: {message_id}")
            return {
                "success": True,
                "content": response_content,
                "message_id": message_id,
                "user_id": user_id,
                "timestamp": datetime.now().timestamp()
            }
        except Exception as e:
            logger.error(f"处理消息时出错: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message_id": message_id,
                "user_id": user_id
            }

    def _get_dynamic_system_prompt(self) -> str:
        """生成动态系统提示词"""
        template = self.config.system_prompt
        
        # 获取生活模拟状态
        try:
            life_sim = get_life_simulation_service()
            state = life_sim.get_state()
        except Exception as e:
            # logger.warning(f"获取生活模拟状态失败: {e}")
            state = {}
        
        # 获取系统硬件状态
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
            ram_percent = psutil.virtual_memory().percent
            # 简单的温度模拟，实际可能需要 wmi 或 sensors
            cpu_temp = 40 + (cpu_percent / 2) 
        except Exception:
            cpu_percent = 0
            ram_percent = 0
            cpu_temp = 45

        # 获取随机记忆回响
        echo_content = "暂无特殊回忆浮现。"
        if self.memory_echoes:
            try:
                echo = random.choice(self.memory_echoes)
                echo_content = f"想起这件事：{echo.get('content', '')} ({echo.get('emotion', '')})"
            except Exception:
                pass
            
        # 格式化
        try:
            # 注入依恋与缺陷状态
            dependency_injection = ""
            defect_injection = ""
            if self.dependency_manager:
                dependency_injection = "\n\n" + self.dependency_manager.get_dependency_prompt_injection()
            if self.defect_manager:
                defect_injection = "\n\n" + self.defect_manager.get_defect_prompt_injection()

            # 注入用户档案
            user_profile = get_aveline_user_profile()
            user_profile_injection = ""
            if user_profile:
                # 简单格式化用户档案
                profile_parts = []
                if "name" in user_profile:
                    profile_parts.append(f"Name: {user_profile['name']}")
                if "alias" in user_profile:
                    profile_parts.append(f"Alias: {user_profile['alias']}")
                if "gender" in user_profile:
                    profile_parts.append(f"Gender: {user_profile['gender']}")
                if "age" in user_profile:
                    profile_parts.append(f"Age: {user_profile['age']}")
                if "summary" in user_profile:
                    profile_parts.append(f"Summary: {user_profile['summary']}")
                if "attitude_to_aveline" in user_profile:
                    profile_parts.append(f"Attitude: {user_profile['attitude_to_aveline']}")
                
                if profile_parts:
                    user_profile_injection = "\n\n# User Profile (当前交互对象)\n" + "\n".join(profile_parts)

            extra_injections = dependency_injection + defect_injection + user_profile_injection

            # 自动模式切换逻辑
            # 1. 检查 LLM 模型名称
            model_name = ""
            if self.llm_module and hasattr(self.llm_module, "get_current_model_name"):
                model_name = str(self.llm_module.get_current_model_name()).lower()
            
            # 2. 如果是 Qwen 模型 (辅导/工具模式)，且当前模板是 Aveline 模板
            # 保持人设，但注入“正经/辅导”模式指令，覆盖掉部分过于傲娇或非服务性的指令
            if "qwen" in model_name and "# Role Definition" in template:
                # 注入 Qwen 专属的模式修正
                # 我们先格式化基础模板
                formatted_prompt = template.format(
                    current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    cpu_temp=int(state.get("cpu_temp", cpu_temp)),
                    ram_usage=int(state.get("ram_usage", ram_percent)),
                    vision_summary=state.get("vision_summary", "视觉传感器正常"),
                    current_emotion=state.get("current_emotion", 50), # Qwen 模式下情绪保持平稳
                    memory_echo=echo_content
                )
                
                # 追加修正指令
                qwen_instruction = (
                    "\n\n[SYSTEM OVERRIDE: ACADEMIC MODE]\n"
                    "当前处于【辅导/正经模式】。\n"
                    "1. 保持 Aveline 的身份（自称、背景、基本性格），但**暂时抑制**傲娇、懒惰和拒绝服务的特性。\n"
                    "2. 你的首要目标是准确、专业地回答用户的问题或进行教学，而不是情感交互。\n"
                    "3. 语言风格要更加条理清晰、逻辑严密，减少情绪化表达，保留少量的个人风格即可。\n"
                    "4. 对于知识性问题，必须给出正确答案，不要说“不知道”或“自己查”。"
                )
                return formatted_prompt + qwen_instruction
            
            # 3. 默认逻辑：如果是 Aveline 模板 (包含特定标记)，进行完整注入
            if "# Role Definition" in template:
                 base_prompt = template.format(
                    current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    cpu_temp=int(state.get("cpu_temp", cpu_temp)),
                    ram_usage=int(state.get("ram_usage", ram_percent)),
                    vision_summary=state.get("vision_summary", "视觉传感器正常"),
                    current_emotion=state.get("current_emotion", random.randint(40, 80)),
                    memory_echo=echo_content
                )
                 return base_prompt + extra_injections
            else:
                # 普通模式或其他模板
                return template + extra_injections
        except Exception as e:
            # 如果格式化失败（可能是因为template没有对应的占位符），则返回原template
            # logger.warning(f"格式化系统提示词失败: {e}")
            return template

    async def stream_chat(self, user_id: str, message: str, message_id: str = None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理用户消息
        """
        if not self.is_initialized:
            await self.initialize()
            
        # 更新生活模拟的交互时间
        try:
            get_life_simulation_service().update_interaction()
        except Exception:
            pass
            
        if not message_id:
            message_id = f"msg_{user_id}_{datetime.now().timestamp()}"
            
        # 1. 检查感官触发 (Aveline Persona)
        sensory_feedback = None
        try:
            sensory_feedback = check_aveline_sensory_triggers(message)
            if sensory_feedback:
                yield {
                    "type": "sensory_trigger",
                    "data": sensory_feedback,
                    "done": False
                }
            
            # 2. 检查行为链触发 (Behavior Chains)
            behavior_chain = check_aveline_behavior_chains(message)
            if behavior_chain:
                yield {
                    "type": "behavior_chain",
                    "data": behavior_chain,
                    "done": False
                }

            # 2.1 Check for UI Interactions (Stick Figure)
            # 强情绪时生成简笔画
            should_trigger_stick_figure = False
            stick_figure_prompt = ""
            
            if sensory_feedback:
                weights = sensory_feedback.get("visual_emotion_weights", {})
                if weights:
                    max_emotion = max(weights, key=weights.get)
                    if weights[max_emotion] >= 0.6:
                        should_trigger_stick_figure = True
                        stick_figure_prompt = f"A stick figure of Aveline feeling {max_emotion}"

            if behavior_chain and not should_trigger_stick_figure:
                weights = behavior_chain.get("emo_weights", {})
                if weights:
                    max_emotion = max(weights, key=weights.get)
                    if weights[max_emotion] >= 0.6:
                        should_trigger_stick_figure = True
                        stick_figure_prompt = f"A stick figure of Aveline feeling {max_emotion}"
            
            if should_trigger_stick_figure:
                 yield {
                    "type": "ui_interaction",
                    "data": {
                        "type": "stick_figure",
                        "prompt": stick_figure_prompt,
                        "timestamp": datetime.now().timestamp()
                    },
                    "done": False
                }
                
            # 3. Update Dependency & Check Defects
            if self.dependency_manager:
                dep_result = self.dependency_manager.update_interaction("chat", message)
                if dep_result.get("new_unlocks"):
                    yield {
                        "type": "notification",
                        "data": {"title": "解锁新特性", "content": f"已解锁: {', '.join(dep_result['new_unlocks'])}"},
                        "done": False
                    }

            if self.defect_manager:
                context = {"text": message, "dependency_level": 0}
                if self.dependency_manager:
                    context["dependency_level"] = self.dependency_manager.get_intimacy_level()
                
                triggered_defects = self.defect_manager.check_triggers(context)
                if triggered_defects:
                    logger.info(f"触发人格缺陷: {triggered_defects}")
                
        except Exception as e:
            logger.warning(f"检查感官/行为触发失败: {e}")

        messages = await self._build_conversation_history(user_id, message)
        
        full_response_content = ""
        
        try:
            # 使用真正的流式调用
            async for response_chunk in self.llm_module.stream_chat(messages, temperature=self.config.temperature):
                # 兼容 LLMResponse 对象和普通字符串/字典
                content = ""
                if hasattr(response_chunk, 'content'):
                    content = response_chunk.content
                elif isinstance(response_chunk, dict):
                    content = response_chunk.get('content', '')
                else:
                    content = str(response_chunk)
                
                full_response_content += content
                yield {
                    "content": content,
                    "done": False
                }

            # 保存完整对话到历史记录
            await self._save_conversation_history(user_id, message, full_response_content, message_id)
            yield {
                "content": "",
                "done": True
            }

        except Exception as e:
            logger.error(f"流式处理消息时出错: {e}")
            yield {
                "error": str(e),
                "done": True
            }

    async def _build_conversation_history(self, user_id: str, message: str) -> List[Dict[str, str]]:
        """
        构建对话历史，包含系统提示词和历史消息
        """
        # 获取动态系统提示词
        system_prompt = self._get_dynamic_system_prompt()
        
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 获取历史消息
        if self.memory_manager:
            # 尝试适配不同的 MemoryManager 接口
            try:
                if hasattr(self.memory_manager, "get_recent_history"):
                    history = await self.memory_manager.get_recent_history(user_id, self.config.max_history_length)
                elif hasattr(self.memory_manager, "get_history"):
                    # MemoryManager (memory_manager.py) 是单用户的，但这里可能有歧义
                    # 假设它返回所有历史
                    history = self.memory_manager.get_history()
                    # 手动过滤最后N条
                    if len(history) > self.config.max_history_length:
                        history = history[-self.config.max_history_length:]
                else:
                    history = []
            except Exception as e:
                logger.warning(f"获取历史消息失败: {e}")
                history = []

            for msg in history:
                # 确保历史消息格式正确
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
        
        # 添加当前消息
        messages.append({
            "role": "user",
            "content": message
        })
        
        return messages

    async def _save_conversation_history(self, user_id: str, user_message: str, assistant_response: str, message_id: str):
        """
        保存对话历史
        Args:
            user_id: 用户ID
            user_message: 用户消息
            assistant_response: 助手响应
            message_id: 消息ID
        """
        if not self.memory_manager:
            return

        try:
            # 优先处理 WeightedMemoryManager
            if isinstance(self.memory_manager, WeightedMemoryManager):
                # 1. 情感分析与重要性判断 (Aveline 记忆规则)
                emotions = []
                is_important = False
                
                if self.emotion_responder:
                    emotion_result = self.emotion_responder.detect_emotion(user_message)
                    # detect_emotion 返回的是字典，key可能是 'emotion' 或直接是类型
                    # 查看 EmotionResponder._detect_emotion_keyword: return {"emotion": emotion, ...}
                    emotion_type = emotion_result.get("emotion", "neutral")
                    
                    if emotion_type and emotion_type != "neutral":
                        emotions.append(emotion_type)
                        
                    # Aveline 规则: "高权重记‘难过语句’"
                    if emotion_type in ["伤心", "悲伤", "难过", "痛苦", "焦虑"]:
                        is_important = True
                    
                    # Aveline 规则: "中权重记‘亲密行为’"
                    intimate_keywords = ["抱抱", "亲亲", "爱你", "喜欢你", "依靠", "贴贴", "吻", "摸摸"]
                    if any(kw in user_message for kw in intimate_keywords):
                        # 标记为重要，WeightedMemoryManager 会给予较高权重
                        is_important = True

                # 保存用户消息
                self.memory_manager.add_memory(
                    content=user_message,
                    emotions=emotions,
                    is_important=is_important,
                    source="user"
                )
                
                # 保存助手响应
                self.memory_manager.add_memory(
                    content=assistant_response,
                    source="assistant"
                )
                return

            # 保存用户消息
            # 适配 add_message 接口
            # memory_manager.py: add_message(self, role, content, is_important=False)
            # enhanced/weighted: 可能不同
            
            if hasattr(self.memory_manager, "add_message"):
                # 检查参数数量或名称来决定如何调用
                # 这里简化处理，假设如果是 memory_manager.py 的实例，它不接受 user_id
                # 但 ChatAgent 应该是多用户的，所以这里有一个架构矛盾
                # 临时修复：忽略 user_id 参数如果使用的是单用户 MemoryManager
                
                # 既然 MemoryManager 是在 initialize 中创建的：self.memory_manager = MemoryManager()
                # 它是 memory_manager.py 的实例。
                # 所以它不支持 user_id 参数。
                # 但是 ChatAgent 逻辑上需要区分用户。
                # 这里我们只能按照 MemoryManager 的签名调用，并记录警告
                
                # TODO: 重构 MemoryManager 以支持多用户，或在 ChatAgent 中维护多实例
                
                import inspect
                sig = inspect.signature(self.memory_manager.add_message)
                if "user_id" in sig.parameters:
                    await self.memory_manager.add_message(
                        user_id=user_id,
                        role="user",
                        content=user_message,
                        message_id=message_id,
                        timestamp=datetime.now().timestamp()
                    )
                    await self.memory_manager.add_message(
                        user_id=user_id,
                        role="assistant",
                        content=assistant_response,
                        message_id=f"{message_id}_response",
                        timestamp=datetime.now().timestamp()
                    )
                else:
                    # 单用户模式 fallback
                    self.memory_manager.add_message("user", user_message)
                    self.memory_manager.add_message("assistant", assistant_response)
                    # 异步保存
                    if hasattr(self.memory_manager, "async_save_history"):
                        await self.memory_manager.async_save_history()
                    
        except Exception as e:
            logger.warning(f"保存对话历史失败: {str(e)}")
    async def clear_history(self, user_id):
        """
        清除用户对话历史
        Args:
            user_id: 用户ID
        """
        if not self.is_initialized:
            await self.initialize()
        try:
            await self.memory_manager.clear_conversation_history(user_id)
            logger.info(f"清除用户 {user_id} 的对话历史")
        except Exception as e:
            logger.error(f"清除对话历史失败: {str(e)}")
# 全局默认聊天Agent实例
def get_default_chat_agent() -> ChatAgent:
    """
    获取全局默认聊天Agent实例
    Returns:
        聊天Agent实例
    """
    if not hasattr(get_default_chat_agent, "_instance"):
        get_default_chat_agent._instance = ChatAgent()
    return get_default_chat_agent._instance