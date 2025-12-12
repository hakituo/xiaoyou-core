import asyncio
import json
import random
import os
import re
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
from dataclasses import dataclass
from datetime import datetime
from core.llm import get_llm_module, LLMConfig, create_instance
from core.modules.llm.module import LLMModule as LocalLLMModule
from config.integrated_config import get_settings
from core.utils.logger import get_logger
# from memory.memory_manager import MemoryManager
from memory.weighted_memory_manager import WeightedMemoryManager
# from memory.emotion_responder import EmotionResponder
from core.emotion import get_emotion_manager, EmotionType
from core.managers.session_manager import get_session_manager
from core.utils.text_processor import extract_and_strip_emotion
from core.tools.registry import ToolRegistry
from core.tools.implementations import WebSearchTool, ImageGenerationTool, TimeTool, CalculatorTool
from core.tools.study_tools import register_study_tools
from core.tools.study.english.vocabulary_manager import VocabularyManager
from core.vector_search import VectorSearch

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
    max_history_length: int = 12
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
        self.memory_managers: Dict[str, WeightedMemoryManager] = {}
        self.emotion_manager = get_emotion_manager()
        self.emotion_responder = None
        self.dependency_manager = None
        self.defect_manager = None
        self.llm_module = None
        self.summary_llm = None
        self.is_initialized = False
        self.memory_echoes = []
        self._lock = asyncio.Lock()
        
        # 初始化工具注册表
        self.tool_registry = ToolRegistry()
        self.tool_registry.register(WebSearchTool())
        self.tool_registry.register(ImageGenerationTool())
        self.tool_registry.register(TimeTool())
        self.tool_registry.register(CalculatorTool())
        
        # 注册高考/辅助工具
        try:
            register_study_tools(self.tool_registry)
            logger.info("已注册Study工具集")
        except Exception as e:
            logger.error(f"注册Study工具集失败: {e}")

        # Initialize VectorSearch for RAG
        try:
            self.vector_search = VectorSearch(use_in_memory_db=False)
            logger.info("Initialized VectorSearch for RAG")
        except Exception as e:
            logger.warning(f"Failed to initialize VectorSearch: {e}")
            self.vector_search = None

        # Initialize Vocabulary Manager
        try:
            self.vocab_manager = VocabularyManager()
            self.daily_word_queue = [] # Queue for daily words
            logger.info("Initialized VocabularyManager")
        except Exception as e:
            logger.warning(f"Failed to initialize VocabularyManager: {e}")
            self.vocab_manager = None
            self.daily_word_queue = []

    def _get_memory_manager(self, user_id: str):
        """获取或创建指定用户的记忆管理器"""
        if user_id not in self.memory_managers:
            try:
                logger.info(f"为用户/会话 {user_id} 初始化 WeightedMemoryManager")
                mm = WeightedMemoryManager(
                    user_id=user_id,
                    max_short_term=self.config.max_history_length,
                    max_long_term=100,
                    auto_save_interval=300
                )
                self.memory_managers[user_id] = mm
            except Exception as e:
                logger.error(f"初始化权重记忆管理器失败: {e}")
                # 再次尝试，或者抛出异常。移除旧的MemoryManager降级
                raise e
        return self.memory_managers[user_id]

    async def initialize(self):
        """
        初始化Agent，加载必要的组件
        """
        async with self._lock:
            if self.is_initialized:
                return
            logger.info(f"初始化ChatAgent: {self.config.agent_name}")
            
            # 初始化情绪响应器
            try:
                # 尝试从新版情绪模块获取，如果不可用则忽略
                # 注意：EmotionResponder 已被集成到 EmotionManager 中，
                # 但为了兼容旧代码的 self.emotion_responder 引用，我们可以在这里做适配
                # 或者直接修改 _save_conversation_history 不再依赖 emotion_responder
                pass
            except Exception as e:
                logger.warning(f"初始化情绪响应器失败: {e}")

            # 初始化依恋与缺陷管理器
            try:
                self.dependency_manager = DependencyManager()
                self.defect_manager = DefectManager()
                logger.info("已初始化依恋与缺陷管理器")
            except Exception as e:
                logger.warning(f"初始化依恋/缺陷管理器失败: {e}")

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
            
            # 初始化摘要LLM (CPU Offload) - 禁用以节省资源，直接使用主模型
            self.summary_llm = None
            # try:
            #     settings = get_settings()
            #     if settings.model.summary_model_path:
            #         logger.info(f"正在初始化摘要模型 (CPU): {settings.model.summary_model_path}")
            #         self.summary_llm = LocalLLMModule(config={
            #             "text_model_path": settings.model.summary_model_path,
            #             "device": "cpu"
            #         })
            #         if await self.summary_llm._load_model():
            #             logger.info("摘要模型加载成功")
            #         else:
            #             logger.warning("摘要模型加载失败，将使用主模型进行摘要")
            #             self.summary_llm = None
            # except Exception as e:
            #     logger.error(f"初始化摘要模型出错: {e}")
            #     self.summary_llm = None
            
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
                    max_context_length=4096,
                    temperature=self.config.temperature
                )
                await create_instance("default_llm", config)
            self.is_initialized = True
            logger.info(f"ChatAgent初始化完成: {self.config.agent_name}")

    async def _check_triggers(self, user_id: str, message: str) -> Optional[str]:
        """
        Check for hardcoded triggers (Surprises, Vocab, etc.)
        Returns a response string if triggered, else None.
        """
        from core.managers.notification_manager import get_notification_manager
        msg = message.lower()
        
        # 1. Vocabulary Push
        if any(k in msg for k in ["单词推送", "今日单词", "背单词", "vocab push"]):
            try:
                # Use local import to avoid circular dependency
                from core.tools.study.english.vocabulary_manager import VocabularyManager
                vm = VocabularyManager()
                words = vm.get_daily_words(limit=20)
                
                nm = get_notification_manager()
                nm.add_notification(
                    user_id=user_id,
                    type="vocabulary",
                    title="今日单词打卡",
                    content=f"今日需复习 {len(words)} 个单词",
                    payload={"words": words}
                )
                
                return f"已为你准备了今日的 {len(words)} 个单词！快去看看吧~ (已发送推送)"
            except Exception as e:
                logger.error(f"Trigger error: {e}")
                return "抱歉，单词服务暂时不可用。"

        # 2. Active Voice (Surprise)
        if any(k in msg for k in ["发语音", "说句话", "active voice", "惊喜", "surprise"]):
            nm = get_notification_manager()
            
            texts = [
                "戚戚，要记得休息哦~",
                "我在呢，一直都在。",
                "今天也要加油鸭！",
                "哼，才不是特意想跟你说话呢...",
                "有点想你了..."
            ]
            text = random.choice(texts)
            
            nm.add_notification(
                user_id=user_id,
                type="voice",
                title="Aveline的语音",
                content=text,
                payload={"text": text, "auto_play": True}
            )
            return f"（发送了一条语音消息）{text}"
            
        return None

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
        # Ensure serialization to prevent concurrent GPU usage (VectorSearch vs LLM)
        async with self._lock:
            if not self.is_initialized:
                await self.initialize()

            # Check triggers first
            trigger_response = await self._check_triggers(user_id, message)
            if trigger_response:
                 if not message_id:
                    message_id = f"msg_{user_id}_{datetime.now().timestamp()}"
                 
                 try:
                     await self._save_conversation_history(user_id, message, trigger_response, message_id)
                 except Exception as e:
                     logger.warning(f"Failed to save trigger history: {e}")
                     
                 return {
                     "response": trigger_response,
                     "conversation_id": user_id,
                     "emotion": "happy", 
                     "message_id": str(uuid.uuid4())
                 }

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
            
                # Tool execution loop
                max_turns = 3
                current_turn = 0
                response_content = ""
                collected_image_prompts = []
                
                while current_turn < max_turns:
                    # 调用LLM生成响应
                    response_content = await self.llm_module.chat(messages, temperature=self.config.temperature)
                    
                    # Check for tool use
                    tool_match = re.search(r'\[TOOL_USE:\s*({.*?})\]', response_content, re.DOTALL)
                    
                    if tool_match:
                        json_str = tool_match.group(1)
                        try:
                            tool_call = json.loads(json_str)
                            tool_name = tool_call.get("name")
                            tool_args = tool_call.get("arguments", {})
                            
                            tool = self.tool_registry.get_tool(tool_name)
                            if tool:
                                logger.info(f"Executing tool {tool_name} with args {tool_args}")
                                tool_result = await tool.run(**tool_args)
                                
                                # Capture image prompt from tool result
                                if tool_name == "generate_image":
                                    img_match_tool = re.search(r'\[GEN_IMG:\s*(.*?)\]', str(tool_result))
                                    if img_match_tool:
                                        collected_image_prompts.append(img_match_tool.group(1))

                                # Add tool result to history
                                messages.append({"role": "assistant", "content": response_content})
                                messages.append({"role": "system", "content": f"Tool '{tool_name}' output:\n{tool_result}\n\nPlease continue the conversation based on this information."})
                                
                                current_turn += 1
                                continue # Loop again with new history
                            else:
                                messages.append({"role": "system", "content": f"Error: Tool '{tool_name}' not found."})
                                current_turn += 1
                                continue
                        except Exception as e:
                             messages.append({"role": "system", "content": f"Error parsing tool call: {e}"})
                             current_turn += 1
                             continue
                    
                    # No tool use, this is the final response
                    break
                
                # 提取情绪
                final_content, emotion_label = extract_and_strip_emotion(response_content)
                
                # 解析主动行为指令
                image_prompt = None
                voice_id = None
                
                # 1. Image Generation: [GEN_IMG: prompt]
                img_match = re.search(r'\[GEN_IMG:\s*(.*?)\]', final_content)
                if img_match:
                    image_prompt = img_match.group(1)
                    final_content = final_content.replace(img_match.group(0), "")
                
                # Fallback to collected prompts if none found in final content
                if not image_prompt and collected_image_prompts:
                    image_prompt = collected_image_prompts[-1]
                    
                # 2. Voice Selection: [VOICE: style]
                voice_match = re.search(r'\[VOICE:\s*(.*?)\]', final_content)
                message_type = "text"
                if voice_match:
                    voice_id = voice_match.group(1)
                    # Keep the content, but mark as voice message
                    # The frontend will hide the text content if it's a voice message until played
                    final_content = final_content.replace(voice_match.group(0), "")
                    message_type = "voice"
                    
                final_content = final_content.strip()

                # 使用新的情绪管理器处理
                try:
                    # 处理文本以更新情绪状态
                    # 这里我们使用 LLM 提取的标签 (如果存在)，否则使用自动检测
                    # process_text 内部会优先使用 [EMO:...] 标签
                    # 但我们需要把原始的 response_content 传进去，因为它包含标签
                    emo_state = self.emotion_manager.process_text(user_id, response_content)
                    
                    # 如果检测出的情绪与 LLM 提取的一致（或更详细），使用检测器的结果
                    # EmotionManager 返回的是 EmotionType 枚举，需要转换
                    if emo_state and emo_state.primary_emotion:
                        emotion_label = emo_state.primary_emotion.value
                    
                    # 获取响应策略（例如呼吸灯控制）
                    # 这里暂时不修改返回结构，保持兼容性，但可以记录日志或触发硬件调用
                    strategy = self.emotion_manager.get_response_strategy(user_id)
                    # TODO: 将 strategy 中的 metadata (呼吸灯颜色) 发送到硬件接口
                    
                except Exception as e:
                    logger.warning(f"情绪管理器处理失败: {e}")

                # 保存对话到历史记录 (保存原始回复，以便LLM上下文保留协议格式)
                await self._save_conversation_history(user_id, message, response_content, message_id)
                
                # 尝试异步生成会话标题 (仅在前几轮对话时)
                asyncio.create_task(self._maybe_generate_session_title(user_id, message, final_content))
                
                logger.info(f"为用户 {user_id} 生成响应，消息ID: {message_id}, 情绪: {emotion_label}")
                return {
                    "success": True,
                    "content": final_content,
                    "emotion": emotion_label,
                    "image_prompt": image_prompt,
                    "voice_id": voice_id,
                    "message_type": message_type,
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

    async def _maybe_generate_session_title(self, session_id: str, user_msg: str, assistant_msg: str):
        """
        尝试生成会话标题
        """
        try:
            mm = self._get_memory_manager(session_id)
            history_len = 0
            if hasattr(mm, "get_history"):
                history = mm.get_history()
                history_len = len(history)
            
            # 只在前1轮对话内生成/更新标题 (User + Assistant = 2 messages)
            # 用户要求：不要每次聊天都更新，只在第一次取名
            if history_len > 2:
                return

            # 构建生成标题的提示词
            prompt = [
                {"role": "system", "content": "你是标题生成助手。请根据用户的输入和助手的回答，生成一个简短的会话标题（不超过10个字）。不要包含标点符号，不要包含'标题'二字。直接输出标题内容。"},
                {"role": "user", "content": f"用户: {user_msg}\n助手: {assistant_msg}"}
            ]
            
            # 使用较小的模型或默认模型生成，温度设低一点
            title = await self.llm_module.chat(prompt, temperature=0.3, max_tokens=20)
            title = title.strip().replace('"', '').replace('“', '').replace('”', '').replace('标题：', '').replace('Title:', '')
            
            if title:
                logger.info(f"为会话 {session_id} 生成标题: {title}")
                get_session_manager().update_session(session_id, title=title)
                
        except Exception as e:
            logger.warning(f"生成会话标题失败: {e}")

    def _get_dynamic_system_prompt(self, user_id: str = None, active_tools: List[str] = None) -> str:
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
                # 简单格式化用户档案 (精简版)
                profile_parts = []
                if "name" in user_profile:
                    name_str = user_profile['name']
                    if "alias" in user_profile:
                        name_str += f" ({user_profile['alias']})"
                    profile_parts.append(f"User: {name_str}")
                
                # 优先使用 one_liner，其次 summary
                if "one_liner" in user_profile:
                    profile_parts.append(f"Profile: {user_profile['one_liner']}")
                elif "summary" in user_profile:
                     # Truncate summary if too long
                    summary = user_profile['summary']
                    if len(summary) > 100:
                        summary = summary[:97] + "..."
                    profile_parts.append(f"Profile: {summary}")
                
                if profile_parts:
                    user_profile_injection = "\n\n# User Profile\n" + "\n".join(profile_parts)

            # Inject Tool Descriptions
            tool_injection = ""
            if self.tool_registry:
                tool_desc = self.tool_registry.get_tools_description(include_names=active_tools)
                if tool_desc:
                    tool_injection = f"\n\n# Available Tools (Intelligent Agent Capabilities)\nYou have access to the following tools. To use them, output a JSON block in this format: [TOOL_USE: {{\"name\": \"tool_name\", \"arguments\": {{...}}}}]\n\n{tool_desc}\n\nExample: [TOOL_USE: {{\"name\": \"calculator\", \"arguments\": {{\"expression\": \"sqrt(144) * 15\"}}}}]\n\nIMPORTANT: Do NOT use the calculator tool for simple arithmetic (e.g., 2+2, 10*5). Perform simple calculations mentally. Only use the calculator for complex operations.\n"

            # Inject User Instructions (Habits/Corrections) & Important Prompts (Layer 3)
            instruction_injection = ""
            if user_id:
                try:
                    mm = self._get_memory_manager(user_id)
                    if isinstance(mm, WeightedMemoryManager):
                        prompts = []
                        # 1. Get Layer 3 (Important Prompts)
                        if hasattr(mm, "get_important_prompts"):
                            prompts = mm.get_important_prompts()
                        
                        # 2. Fallback/Legacy: Filter weighted memories for instructions if Layer 3 is empty
                        if not prompts:
                            with mm.lock:
                                sorted_memories = sorted(mm.weighted_memories.values(), key=lambda x: x['timestamp'], reverse=True)
                                for mem in sorted_memories:
                                    if "user_instruction" in mem.get("topics", []):
                                        prompts.append(mem)
                                        if len(prompts) >= 5:
                                            break
                        
                        if prompts:
                            instruction_injection = "\n\n# Important Memories & Instructions (Core Layer)\nThe user has explicitly requested the following or these are core memories (you MUST follow/remember these):\n" + "\n".join([f"- {p.get('content', '')}" for p in prompts])
                except Exception as e:
                    logger.warning(f"Failed to load user instructions: {e}")

            extra_injections = dependency_injection + defect_injection + user_profile_injection + tool_injection + instruction_injection

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
                    "1. **过渡指令**：如果是用户刚要求切换模式（如说“进入学习模式”），你的第一句回复**必须**是：“好哦，稍等一下戚戚，我加载一下模式~” (可适当发挥，加上加载音效描述)，然后再回应后续内容。\n"
                    "2. 保持 Aveline 的身份（自称、背景），但**暂时抑制**傲娇、懒惰和拒绝服务的特性。\n"
                    "3. 你的首要目标是准确、专业地回答用户的问题或进行教学，而不是情感交互。\n"
                    "4. 语言风格要更加条理清晰、逻辑严密，减少情绪化表达，保留少量的个人风格即可。\n"
                    "5. 对于知识性问题，必须给出正确答案，不要说“不知道”或“自己查”。\n"
                    "6. **工具使用原则**：对于简单的计算（如加减乘除、简单函数），请直接计算并给出结果，**不要**调用计算器工具。只有遇到复杂计算时才使用工具。"
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
                 
                 # 强制添加情绪标签提醒 (已移除冗余部分，完全遵循Aveline.json)
                 # force_reminder = (
                 #     "\n\n[SYSTEM REMINDER]\n"
                 #     "1. Start response with [EMO: label]. Valid: neutral, happy, shy, angry, jealous, wronged, coquetry, lost, excited.\n"
                 #     "2. Optional: End with [VOICE: style] for voice messages (hides text). Styles: default, whisper, soft, happy, angry, shy, coquetry.\n"
                 #     "3. Current time: {current_time}."
                 # ).format(current_time=datetime.now().strftime("%Y-%m-%d %H:%M"))
                 return base_prompt + extra_injections # + force_reminder
            else:
                # 普通模式或其他模板
                return template + extra_injections
        except Exception as e:
            # 如果格式化失败（可能是因为template没有对应的占位符），则返回原template
            # logger.warning(f"格式化系统提示词失败: {e}")
            return template

    async def _check_daily_routine(self, user_id: str) -> Optional[str]:
        """Check if we need to push daily study summary"""
        try:
            # Check last interaction time via memory
            mm = self._get_memory_manager(user_id)
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Check if we already did the summary today
            already_done = False
            if hasattr(mm, "get_memories_by_topic"):
                summaries = mm.get_memories_by_topic("daily_summary", limit=1)
                if summaries:
                    last_date = datetime.fromtimestamp(summaries[0].get("timestamp", 0)).strftime("%Y-%m-%d")
                    if last_date == today:
                        already_done = True
            
            if not already_done:
                from core.services.study_service import get_study_service
                service = get_study_service()
                summary_data = service.get_daily_study_summary_data()
                
                if not summary_data:
                    return None
                
                # Mark as done by adding a system memory (silent)
                if hasattr(mm, "add_memory"):
                    mm.add_memory(
                        content=f"Daily summary generated for {today}",
                        source="system",
                        topics=["daily_summary"],
                        importance=1
                    )
                
                summary_text = (
                    f"【系统通知：每日学习任务更新】\n"
                    f"日期: {summary_data.get('date')}\n"
                    f"单词进度: 已学 {summary_data['vocab']['total_learned']}, 待复习 {summary_data['vocab']['to_review']}\n"
                    f"今日目标: {summary_data['vocab']['target']}\n"
                    f"建议: {summary_data.get('suggestion')}\n"
                    f"(指令：请将以上内容总结并作为当前对话的主要话题，引导用户开始学习。)"
                )
                return summary_text
            
            return None
        except Exception as e:
            logger.warning(f"Check daily routine failed: {e}")
            return None

    async def stream_chat(self, user_id: str, message: str, message_id: str = None, save_history: bool = True, model_hint: str = None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理用户消息
        
        Args:
            user_id: 用户ID
            message: 用户消息
            message_id: 消息ID
            save_history: 是否保存历史记录
            model_hint: 模型提示/标识 (用于判断是否是学习模式等)
        """
        # Serialized access to prevent concurrent heavy compute
        async with self._lock:
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
    
            messages = await self._build_conversation_history(user_id, message, model_hint)
            
            # 5. Check Daily Routine (Inject if needed)
            daily_summary = await self._check_daily_routine(user_id)
            if daily_summary:
                messages.insert(-1, {"role": "system", "content": daily_summary})
                logger.info(f"Injected daily summary for {user_id}")

            # 6. Main Chat Loop (Handle Tools)
            max_turns = 3
            current_turn = 0
            collected_image_prompts = []
            
            while current_turn < max_turns:
                current_response_content = ""
                
                # Stream Generation
                try:
                    async for response_chunk in self.llm_module.stream_chat(messages, temperature=self.config.temperature):
                        content = ""
                        if hasattr(response_chunk, 'content'):
                            content = response_chunk.content
                        elif isinstance(response_chunk, dict):
                            content = response_chunk.get('content', '')
                        else:
                            content = str(response_chunk)
                        
                        current_response_content += content
                        
                        yield {
                            "type": "token",
                            "data": content,
                            "content": content,
                            "done": False
                        }
                except Exception as e:
                    logger.error(f"Stream generation failed: {e}")
                    yield {"error": str(e), "done": True}
                    return

                # Check for Tool Use in this turn's response
                tool_match = re.search(r'\[TOOL_USE:\s*({.*?})\]', current_response_content, re.DOTALL)
                
                if tool_match:
                    json_str = tool_match.group(1)
                    try:
                        tool_call = json.loads(json_str)
                        tool_name = tool_call.get("name")
                        tool_args = tool_call.get("arguments", {})
                        
                        tool = self.tool_registry.get_tool(tool_name)
                        if tool:
                            logger.info(f"Executing tool {tool_name} with args {tool_args}")
                            yield {"type": "system", "content": f"\n(Executing {tool_name}...)\n", "done": False}
                            
                            tool_result = await tool.run(**tool_args)
                            
                            # Capture image prompt
                            if tool_name == "generate_image":
                                img_match_tool = re.search(r'\[GEN_IMG:\s*(.*?)\]', str(tool_result))
                                if img_match_tool:
                                    collected_image_prompts.append(img_match_tool.group(1))

                            # Update history for next turn
                            messages.append({"role": "assistant", "content": current_response_content})
                            messages.append({"role": "system", "content": f"Tool '{tool_name}' output:\n{tool_result}\n\nPlease continue based on this."})
                            
                            current_turn += 1
                            continue # Loop again
                        else:
                            messages.append({"role": "system", "content": f"Error: Tool '{tool_name}' not found."})
                            current_turn += 1
                            continue
                    except Exception as e:
                         messages.append({"role": "system", "content": f"Error parsing tool call: {e}"})
                         current_turn += 1
                         continue
                
                # If no tool use, check for media triggers in the final content
                # Voice
                voice_match = re.search(r'\[VOICE:\s*(.*?)\]', current_response_content)
                if voice_match:
                    yield {"type": "voice_trigger", "data": voice_match.group(1), "done": False}
                
                # Image
                img_match = re.search(r'\[GEN_IMG:\s*(.*?)\]', current_response_content)
                if img_match:
                    yield {"type": "image_trigger", "data": img_match.group(1), "done": False}
                elif collected_image_prompts:
                    # If image was generated by tool but not explicitly in text tag, trigger it anyway
                    yield {"type": "image_trigger", "data": collected_image_prompts[-1], "done": False}

                # Save history (Final turn)
                if save_history:
                    await self._save_conversation_history(user_id, message, current_response_content, message_id)
                
                # [NEW] Extract and Yield Emotion Update
                try:
                    emo_state = self.emotion_manager.process_text(user_id, current_response_content)
                    if emo_state:
                        yield {
                            "type": "emotion_update",
                            "data": {
                                "primary_emotion": emo_state.primary_emotion.value,
                                "intensity": emo_state.intensity,
                                "confidence": emo_state.confidence,
                                "sub_emotions": emo_state.sub_emotions
                            },
                            "done": False
                        }
                except Exception as e:
                    logger.warning(f"Failed to process emotion in stream: {e}")

                yield {
                    "content": "",
                    "done": True
                }
                break

    def extract_and_strip_emotion(self, content: str) -> Tuple[str, Optional[str]]:
        """
        从回复中提取情绪标签
        代理到 core.utils.text_processor.extract_and_strip_emotion
        """
        return extract_and_strip_emotion(content)

    async def _perform_context_summary(self, user_id: str, memory_manager: WeightedMemoryManager):
        """
        执行上下文摘要（CPU Offload）
        """
        try:
            # 获取短期记忆
            memories = []
            with memory_manager.lock:
                memories = list(memory_manager.short_term_memory)
            
            # 如果记忆不足 15 条，不处理 (Aggressive context management)
            if len(memories) < 15:
                return

            logger.info(f"检测到上下文长度达到 {len(memories)}，触发摘要逻辑...")

            # 取前部分进行摘要 (保留最近 8 条 + 新摘要)
            to_summarize = memories[:-8]  # 除了最后8条之外的所有
            if not to_summarize:
                return
                
            # 构建摘要请求
            text_block = "\n".join([f"{m.get('source', 'unknown')}: {m.get('content', '')}" for m in to_summarize])
            
            prompt = [
                {"role": "system", "content": "You are a memory compressor. Summarize the following conversation segment into a concise paragraph. Capture key events, emotions, and facts. Output ONLY the summary text."},
                {"role": "user", "content": f"Summarize this:\n{text_block}"}
            ]
            
            # 使用摘要模型或主模型
            summary = ""
            if self.summary_llm:
                summary = await self.summary_llm.chat(prompt, temperature=0.3)
            elif self.llm_module:
                logger.warning("摘要模型未启用，使用主模型进行摘要（可能占用GPU资源）")
                summary = await self.llm_module.chat(prompt, temperature=0.3)
            
            if not summary:
                return

            logger.info(f"生成摘要成功: {summary[:50]}...")
            
            # 更新记忆管理器
            with memory_manager.lock:
                # 1. 移除被摘要的记忆
                # 重新获取引用以防变化
                current_memories = memory_manager.short_term_memory
                
                # 找到我们要移除的那些记忆的ID
                ids_to_remove = {m['id'] for m in to_summarize}
                
                # 过滤
                memory_manager.short_term_memory = [m for m in current_memories if m['id'] not in ids_to_remove]
                
            # 2. 添加摘要作为重要记忆 (Outside lock to avoid potential issues, add_memory handles lock)
            memory_manager.add_memory(
                content=f"【历史摘要】 {summary}",
                source="system_summary",
                is_important=True,
                topics=["summary", "history_offload"]
            )
            
        except Exception as e:
            logger.error(f"执行上下文摘要失败: {e}")

    def _is_study_mode(self, message: str, model_hint: str = None) -> bool:
        """Check if study mode is active based on model hint or message content"""
        # 1. Check model hint
        if model_hint and any(k in model_hint.lower() for k in ["study", "gaokao", "learning", "tutor"]):
            return True
            
        # 2. Check message triggers
        triggers = ["进入学习模式", "开始学习", "study mode", "高考模式"]
        if any(t in message.lower() for t in triggers):
            return True
            
        return False

    def _classify_subject(self, message: str) -> Optional[str]:
        """Classify message into a study subject based on file naming conventions"""
        message = message.lower()
        # Mapping subject keys to keywords in user message
        # These keys will be used to match filenames in study_data
        subjects = {
            "Biology": ["生物", "biology", "细胞", "遗传", "基因", "进化"],
            "Chemistry": ["化学", "chemistry", "元素", "反应", "有机", "分子"],
            "Physics": ["物理", "physics", "力学", "电磁", "光", "能量"],
            "Math": ["数学", "math", "函数", "几何", "导数", "积分", "代数"],
            "English": ["英语", "english", "单词", "语法", "作文", "听力"],
            "Chinese": ["语文", "chinese", "古诗", "文言文", "阅读理解", "作文"],
            "Geography": ["地理", "geography", "地形", "气候", "洋流"],
            "History": ["历史", "history", "朝代", "事件", "战争", "革命"],
            "Political_Science": ["政治", "politics", "马克思", "经济", "哲学"]
        }
        
        for subject, keywords in subjects.items():
            if any(k in message for k in keywords):
                return subject
        return None

    def _get_english_word_context(self) -> Optional[Dict[str, str]]:
        """Get an English word for context injection from VocabularyManager"""
        if not self.vocab_manager:
            return None
            
        try:
            # Refill queue if empty
            if not self.daily_word_queue:
                # Get more words (mix of review and new)
                # Limit to 20 for batch, but we can call it multiple times a day
                self.daily_word_queue = self.vocab_manager.get_daily_words(limit=20)
                # Shuffle to mix review and new
                random.shuffle(self.daily_word_queue)
                if self.daily_word_queue:
                    logger.info(f"Refilled daily word queue with {len(self.daily_word_queue)} words")
            
            if self.daily_word_queue:
                # Pop one word
                word_obj = self.daily_word_queue.pop(0)
                word = word_obj.get("word")
                trans = word_obj.get("translations", [])
                
                # Format translations
                trans_str = "; ".join([f"{t.get('type')}. {t.get('translation')}" for t in trans])
                
                return {
                    "word": word, 
                    "meaning": trans_str,
                    "status": word_obj.get("status", "new") # new or review
                }
                
        except Exception as e:
            logger.warning(f"Failed to get English word: {e}")
            
        return None

    async def _build_conversation_history(self, user_id: str, message: str, model_hint: str = None) -> List[Dict[str, str]]:
        """
        构建对话历史，包含系统提示词和历史消息
        """
        # [Stheno Optimization] Global context limit check
        
        # Trigger CPU offload summary if needed
        memory_manager = self._get_memory_manager(user_id)
        if memory_manager and isinstance(memory_manager, WeightedMemoryManager):
            # Run summary logic in background
            asyncio.create_task(self._perform_context_summary(user_id, memory_manager))
 
        # 智能工具筛选 (Dynamic Tool Loading)
        # 默认只加载基础轻量工具，减少 Prompt 长度
        active_tools = ["get_current_time", "calculator", "web_search", "text_to_speech"]
        
        if message:
            msg_lower = message.lower()
            
            # Study Tools & Context
            due_words_prompt = ""
            if self.vocab_manager:
                try:
                    # Check for due words
                    stats = self.vocab_manager.get_stats()
                    due_count = stats.get("due_words", 0)
                    
                    # Activate tool if needed
                    if due_count > 0 or any(k in msg_lower for k in ["单词", "英语", "背诵", "复习", "word", "vocabulary", "study", "exam", "grade"]):
                        if "update_word_progress" not in active_tools:
                            active_tools.append("update_word_progress")
                    
                    # Generate prompt for immediate reviews
                    if due_count > 0:
                        # Get pending reviews (prioritize by due time)
                        daily_batch = self.vocab_manager.get_daily_words(limit=3)
                        # Filter for actual reviews
                        reviews = [w['word'] for w in daily_batch if w.get('status') == 'review']
                        
                        if reviews:
                            due_words_prompt = (
                                f"\n\n[SYSTEM: STUDY PRIORITY]\n"
                                f"Words due for review: {', '.join(reviews)}.\n"
                                f"Please integrate these into the conversation or quiz the user (use 'Look at Chinese, Say English' method)."
                            )
                except Exception as e:
                    logger.warning(f"Failed to check vocab status: {e}")

            # Math Plot
            if any(k in msg_lower for k in ["画图", "函数", "曲线", "plot", "graph", "math", "equation"]):
                active_tools.append("generate_math_plot")
                
            # Image Gen
            if any(k in msg_lower for k in ["画", "图", "image", "draw", "paint", "picture"]):
                active_tools.append("generate_image")
            
            # Knowledge Base
            if any(k in msg_lower for k in ["知识库", "查询", "搜索", "know", "search", "资料"]):
                active_tools.append("search_knowledge_base")
        
        # 获取动态系统提示词
        system_prompt = self._get_dynamic_system_prompt(user_id=user_id, active_tools=active_tools)
        
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 获取当前用户的记忆管理器
        memory_manager = self._get_memory_manager(user_id)
        
        # 尝试检索相关记忆 (RAG) - 增强记忆连贯性
        # 优化：闲聊模式下（非学习模式且无明显问题意图）跳过RAG，避免资源浪费和无关记忆干扰
        is_question = any(c in message for c in "?？who what where when why 怎么 谁 哪 什么 记 回忆")
        should_trigger_memory_rag = (
            memory_manager 
            and message 
            and (
                len(message) > 15  # 长文本
                or is_question     # 提问
                or self._is_study_mode(message, model_hint) # 学习模式
            )
        )

        if should_trigger_memory_rag:
            try:
                relevant_memories = []
                # 优先使用混合搜索
                if hasattr(memory_manager, "hybrid_search"):
                    # 提高相似度阈值以减少无关记忆，减少 limit
                    results = memory_manager.hybrid_search(message, limit=2, min_similarity=0.7) # 提高阈值到 0.7
                    for mem in results:
                        content = mem.get('content', '')
                        # 避免重复过短的记忆
                        if len(content) > 10:
                            relevant_memories.append(f"- {content}")
                
                if relevant_memories:
                    rag_content = "【相关记忆回溯】(Relevant Memories)\n以下是与当前话题相关的过往记忆，请结合上下文参考：\n" + "\n".join(relevant_memories)
                    messages.append({"role": "system", "content": rag_content})
                    logger.info(f"已注入 {len(relevant_memories)} 条相关记忆")
            except Exception as e:
                logger.warning(f"记忆检索失败: {e}")

        # Determine context
        is_study = self._is_study_mode(message, model_hint)
        subject = self._classify_subject(message) if message else None

        # 尝试检索外部知识库 (Knowledge Base RAG)
        # 仅在学习模式下触发
        if self.vector_search and message and len(message) > 5 and is_study:
            try:
                logger.info(f"RAG Study Mode Active. Detected subject: {subject}")
                
                # 2. Query with higher top_k to allow filtering
                kb_results = self.vector_search.query_full(message, top_k=15)
                
                if kb_results:
                    kb_content_list = []
                    for res in kb_results:
                        doc_content = res.get('document', '').strip()
                        metadata = res.get('metadata', {})
                        source = metadata.get('source', 'Unknown') # e.g. .../Biology/...
                        distance = res.get('distance', 1.0)
                        
                        # 过滤相关性低的结果
                        if distance > 0.55: # Slightly looser for study
                            continue
                            
                        # Subject Filtering
                        if subject:
                            # Strict filtering: Source MUST contain subject keyword
                            if subject.lower() not in source.lower():
                                continue
                        
                        # 截断
                        if len(doc_content) > 800:
                            doc_content = doc_content[:800] + "...(truncated)"

                        if len(doc_content) > 10:
                            kb_content_list.append(f"- [Source: {source}] {doc_content}")
                            
                        # Limit to top 3 relevant
                        if len(kb_content_list) >= 3:
                            break
                    
                    if kb_content_list:
                        kb_section = f"【高考知识库 - {subject or '综合'}】(Knowledge Base)\n以下是检索到的相关资料，请优先基于此资料回答用户问题：\n" + "\n".join(kb_content_list)
                        messages.append({"role": "system", "content": kb_section})
                        logger.info(f"已注入 {len(kb_content_list)} 条知识库资料")
                        
            except Exception as e:
                logger.warning(f"知识库检索失败: {e}")

        # 2.5 Priority Due Words Injection
        if due_words_prompt:
            messages.append({"role": "system", "content": due_words_prompt})

        # 3. English Word Injection (Daily Vocabulary)
        # Strategy: 
        # - If subject is English: High chance (80%)
        # - If study mode (other subjects): Medium chance (30%)
        # - If normal chat: Low chance (20%) but ensures daily progress
        
        inject_chance = 0.20
        if subject == "English":
            inject_chance = 0.8
        elif is_study:
            inject_chance = 0.3
            
        if random.random() < inject_chance:
            word_ctx = self._get_english_word_context()
            if word_ctx:
                word = word_ctx.get("word")
                meaning = word_ctx.get("meaning")
                status = word_ctx.get("status")
                
                context_type = "Review" if status == "review" else "New Word"
                
                # Hidden instruction for LLM to use the word naturally
                instruction = (
                    f"\n[Vocabulary Injection - {context_type}]\n"
                    f"Target Word: {word}\n"
                    f"Meaning: {meaning}\n"
                    f"Instruction: Naturally incorporate this word into your response. "
                    f"If it's a review word, ask if I remember it. "
                    f"If it's new, use it in a sentence to teach me. "
                    f"Do NOT explicitly list the translation unless asked. "
                    f"You can use the 'update_word_progress' tool if I tell you whether I remember it or not."
                )
                messages.append({"role": "system", "content": instruction})

        # 获取历史消息
        if memory_manager:
            # 尝试适配不同的 MemoryManager 接口
            try:
                # WeightedMemoryManager 使用 get_recent_history
                # 注意：EnhancedMemoryManager.get_recent_history 是同步的，不需要 await
                # 但为了兼容性，检查是否是协程
                if hasattr(memory_manager, "get_recent_history"):
                    import inspect
                    if inspect.iscoroutinefunction(memory_manager.get_recent_history):
                        history = await memory_manager.get_recent_history(user_id, self.config.max_history_length)
                    else:
                        history = memory_manager.get_recent_history(user_id, self.config.max_history_length)
                elif hasattr(memory_manager, "get_history"):
                    # 兼容旧接口
                    history = memory_manager.get_history()
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
        memory_manager = self._get_memory_manager(user_id)
        if not memory_manager:
            return

        # 更新会话时间戳
        try:
            get_session_manager().update_session(user_id)
        except Exception:
            pass

        try:
            # Initialize topics to avoid UnboundLocalError
            topics = []
            
            # 优先处理 WeightedMemoryManager
            if isinstance(memory_manager, WeightedMemoryManager):
                # 1. 情感分析与重要性判断 (Aveline 记忆规则)
                emotions = []
                # topics = [] # Already initialized
                is_important = False
                
                if self.emotion_manager:
                    # 使用 EmotionManager 的 detect_emotion (如果存在)
                    # 或者复用之前提取的 emotion_label (但这需要传递进来)
                    # 这里为了简单，我们重新检测或跳过
                    pass
                elif self.emotion_responder:
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

                    # Aveline 规则: "高权重记‘用户指令/习惯修正’"
                    instruction_keywords = [
                        "改掉", "不要", "以后", "记住", "习惯", "设定", "人设", 
                        "必须", "禁止", "不再", "don't", "remember", "stop", "never"
                    ]
                    # topics = [] # Redundant and causes scope issues
                    if any(kw in user_message for kw in instruction_keywords):
                        is_important = True
                        topics.append("user_instruction")
                        logger.info(f"Detected instructional message, marking as important: {user_message[:20]}...")

                # 保存用户消息
                memory_manager.add_memory(
                    content=user_message,
                    topics=topics if topics else None,
                    emotions=emotions,
                    is_important=is_important,
                    source="user"
                )
                
                # 保存助手响应
                memory_manager.add_memory(
                    content=assistant_response,
                    source="assistant"
                )
                
                # 尝试生成/更新会话标题
                try:
                    asyncio.create_task(self._maybe_generate_session_title(user_id, user_message, assistant_response))
                except Exception as e:
                    logger.warning(f"创建标题生成任务失败: {e}")
                    
                return

            # 保存用户消息
            # 适配 add_message 接口
            # memory_manager.py: add_message(self, role, content, is_important=False)
            # enhanced/weighted: 可能不同
            
            if hasattr(memory_manager, "add_message"):
                # 检查参数数量或名称来决定如何调用
                import inspect
                sig = inspect.signature(memory_manager.add_message)
                if "user_id" in sig.parameters:
                    await memory_manager.add_message(
                        user_id=user_id,
                        role="user",
                        content=user_message,
                        message_id=message_id,
                        timestamp=datetime.now().timestamp()
                    )
                    await memory_manager.add_message(
                        user_id=user_id,
                        role="assistant",
                        content=assistant_response,
                        message_id=f"{message_id}_response",
                        timestamp=datetime.now().timestamp()
                    )
                else:
                    # 单用户模式 fallback
                    memory_manager.add_message("user", user_message)
                    memory_manager.add_message("assistant", assistant_response)
                    # 异步保存
                    if hasattr(memory_manager, "async_save_history"):
                        await memory_manager.async_save_history()
                    
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
            memory_manager = self._get_memory_manager(user_id)
            if hasattr(memory_manager, "clear_conversation_history"):
                await memory_manager.clear_conversation_history(user_id)
            elif hasattr(memory_manager, "clear_history"):
                 # WeightedMemoryManager doesn't seem to have clear_conversation_history that takes user_id
                 # But it has clear_history() maybe?
                 # Let's check MemoryManager
                 pass
            
            # Since we are using session-based isolation, maybe we should just delete the session?
            # But here we just clear the memory.
            # Re-initializing memory manager might be cleaner.
            self.memory_managers.pop(user_id, None)
            
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