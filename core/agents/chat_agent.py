import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
from dataclasses import dataclass
from core.llm import get_llm_module, LLMConfig, create_instance
from core.utils.logger import get_logger
from core.utils.async_locks import LazyAsyncLock
from memory.weighted_memory_manager import WeightedMemoryManager, get_weighted_memory_manager
from core.emotion import get_emotion_manager
from core.tools.registry import ToolRegistry
from core.agents.chat_agent_components.vocab_compat import create_vocab_manager
from core.agents.chat_agent_components.context import (
    perform_context_summary,
    build_conversation_history,
)
from core.agents.chat_agent_components.triggers import (
    async_check_triggers,
    sync_check_daily_routine_logic,
    async_check_daily_routine,
)
from core.agents.chat_agent_components.streaming import stream_chat_impl
from core.agents.chat_agent_components.persona import (
    determine_mode,
    get_dynamic_system_prompt,
)
from config.integrated_config import get_settings
from core.agents.chat_agent_components.study import (
    is_study_mode,
    classify_subject,
    get_english_word_context,
)
from core.agents.chat_agent_components.handler import handle_message_impl
from core.agents.chat_agent_components.history import (
    maybe_generate_session_title,
    save_conversation_history,
    clear_history as history_clear_history,
)
from core.utils.text_processor import extract_and_strip_emotion

# 修正导入路径，不再使用已不存在的 aveline_manager
# 使用 core.character.aveline 中的 AvelineCharacter 获取信息
from core.character.aveline import get_aveline_character_info, get_aveline_system_prompt_template
from core.character.managers.persona_manager import get_persona_manager
from core.character.managers.dependency_manager import DependencyManager
from core.character.managers.defect_manager import DefectManager

logger = get_logger("ChatAgent")

@dataclass
class AgentConfig:
    """
    Agent配置类
    """
    agent_name: str = "default_chat_agent"
    system_prompt: str = ""
    max_history_length: int = 500 # Increased from 12 to support Cloud models (Local models will be sliced)
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
        self._memory_manager_init_locks: Dict[str, asyncio.Lock] = {}
        self.emotion_manager = get_emotion_manager()
        self.emotion_responder = None
        self.dependency_manager = None
        self.defect_manager = None
        self.llm_module = None
        self.summary_llm = None
        self.is_initialized = False
        self.memory_echoes = []
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        
        # 初始化工具注册表（统一注册所有工具）
        self.tool_registry = ToolRegistry()
        from core.tools.registry import register_all_tools
        register_all_tools(self.tool_registry)
        logger.info(f"已注册 {len(self.tool_registry.list_tools())} 个工具")

        self.vector_search = None

        # 词汇模块缺失时不影响主对话启动
        self.vocab_manager = create_vocab_manager()
        self.daily_word_queue = []

        self.dialogue_search_sfw = None
        self.dialogue_search_sfw_daily = None
        self.dialogue_search_sfw_study = None
        self.dialogue_search_sfw_legacy = None
        self.dialogue_search_nsfw = None
        self.dialogue_search_sensitive = None

    def _get_memory_manager(self, user_id: str):
        """获取或创建指定用户的记忆管理器

        重启后首次调用时，会阻塞等待后台数据加载完成（最多 30 秒），
        避免在 short_term_memory 未就绪时返回空上下文。
        """
        if user_id not in self.memory_managers:
            try:
                logger.info(f"为用户/会话 {user_id} 初始化 WeightedMemoryManager")
                # [FIX] 使用全局单例工厂，确保与 Active Care 等服务共享同一个实例
                mm = get_weighted_memory_manager(user_id)
                # 同步 max_short_term 配置
                if self.config.max_history_length and hasattr(mm, 'max_short_term'):
                    if mm.max_short_term < self.config.max_history_length:
                        mm.max_short_term = self.config.max_history_length
                self.memory_managers[user_id] = mm
            except Exception as e:
                logger.error(f"初始化权重记忆管理器失败: {e}")
                # 再次尝试，或者抛出异常。移除旧的MemoryManager降级
                raise e
        mm = self.memory_managers[user_id]
        # 等待后台数据加载完成，避免重启后上下文丢失
        if hasattr(mm, 'ensure_data_loaded'):
            mm.ensure_data_loaded(timeout=30.0)
        return mm

    async def get_memory_manager_async(self, user_id: str) -> WeightedMemoryManager:
        uid = str(user_id or "").strip() or "default"
        mm = self.memory_managers.get(uid)
        if mm is not None:
            return mm

        lock = self._memory_manager_init_locks.get(uid)
        if lock is None:
            lock = asyncio.Lock()
            self._memory_manager_init_locks[uid] = lock

        async with lock:
            mm = self.memory_managers.get(uid)
            if mm is not None:
                return mm

            def _create() -> WeightedMemoryManager:
                logger.info(f"为用户/会话 {uid} 初始化 WeightedMemoryManager")
                # [FIX] 使用全局单例工厂，确保与 Active Care 等服务共享同一个实例
                mm = get_weighted_memory_manager(uid)
                # 同步 max_short_term 配置
                if self.config.max_history_length and hasattr(mm, 'max_short_term'):
                    if mm.max_short_term < self.config.max_history_length:
                        mm.max_short_term = self.config.max_history_length
                return mm

            mm = await asyncio.to_thread(_create)
            self.memory_managers[uid] = mm
            return mm

    async def initialize(self):
        """
        初始化Agent，加载必要的组件
        """
        async with self._lock:
            if self.is_initialized:
                return
            _init_t0 = time.perf_counter()
            logger.info(f"初始化ChatAgent: {self.config.agent_name}")

            try:
                self.dependency_manager = DependencyManager()
                self.defect_manager = DefectManager()
                logger.info("已初始化依恋与缺陷管理器 (%.3fs)", time.perf_counter() - _init_t0)
            except Exception as e:
                logger.warning(f"初始化依恋/缺陷管理器失败: {e}")

            self.memory_echoes = []

            _t_llm = time.perf_counter()
            self.llm_module = await asyncio.to_thread(get_llm_module)
            await self.llm_module.initialize()
            logger.info("LLM 模块初始化完成 (%.3fs)", time.perf_counter() - _t_llm)

            self.summary_llm = None

            _t_persona = time.perf_counter()
            try:
                current_persona_filename = str(get_persona_manager().get_current_filename() or "").strip()
                prompt_template = ""
                if current_persona_filename:
                    from core.agents.chat_agent_components.persona_system import build_expanded_persona_prompt

                    prompt_template = build_expanded_persona_prompt(
                        persona_filename=current_persona_filename
                    )
                if prompt_template:
                    self.config.system_prompt = prompt_template
                    logger.info(f"已加载当前人格完整系统提示词模板: {current_persona_filename}")
                else:
                    prompt_template = get_aveline_system_prompt_template()
                    if prompt_template:
                        self.config.system_prompt = prompt_template
                        logger.info("未获取到当前人格模板，回退到 Aveline 完整系统提示词模板")
                    else:
                        character_info = get_aveline_character_info()
                        if character_info:
                            prompt_template = f"你的名字是{character_info.get('name')}，代号{character_info.get('code')}。你的角色是{character_info.get('role')}。{character_info.get('description')}"
                            self.config.system_prompt = prompt_template
                            logger.info("已使用Aveline基础信息更新系统提示词")
            except Exception as e:
                logger.warning(f"获取当前人格角色配置失败: {str(e)}")
            logger.info("人格提示词加载完成 (%.3fs)", time.perf_counter() - _t_persona)

            _t_vs = time.perf_counter()
            try:
                from core.vector_search import VectorSearch

                project_root = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "..", "..")
                )
                generated_dir = os.path.join(project_root, "generated_data")
                settings = get_settings()
                auto_ingest = bool(
                    getattr(
                        settings.vector_search,
                        "dialogue_examples_auto_ingest_on_startup",
                        False,
                    )
                )

                def _collect_ai_studio_doc_ids() -> List[str]:
                    doc_ids: List[str] = []
                    if not os.path.isdir(generated_dir):
                        return doc_ids
                    try:
                        for fn in os.listdir(generated_dir):
                            low = fn.lower()
                            if not low.endswith(".jsonl"):
                                continue
                            path = os.path.join(generated_dir, fn)
                            try:
                                with open(path, "r", encoding="utf-8") as f:
                                    for line in f:
                                        raw = (line or "").strip()
                                        if not raw or "ai_studio" not in raw.lower():
                                            continue
                                        try:
                                            obj = json.loads(raw)
                                        except Exception:
                                            continue
                                        if not isinstance(obj, dict):
                                            continue
                                        did = str(obj.get("id") or "").strip()
                                        if "ai_studio" not in did.lower():
                                            continue
                                        turns = obj.get("dialogue")
                                        if not isinstance(turns, list):
                                            continue
                                        for i in range(len(turns)):
                                            doc_ids.append(f"{did}_{i}")
                            except Exception:
                                continue
                    except Exception:
                        return doc_ids
                    return doc_ids

                def _purge_ai_studio_docs(vs: Any, blocked_ids: List[str]) -> None:
                    col = getattr(vs, "collection", None)
                    if not col:
                        return
                    purge_ids = list(blocked_ids or [])
                    if not purge_ids:
                        try:
                            data = col.get()
                            ids = data.get("ids") or []
                            purge_ids = [i for i in ids if "ai_studio" in str(i).lower()]
                        except Exception:
                            return
                    if not purge_ids:
                        return
                    try:
                        col.delete(ids=purge_ids)
                    except Exception:
                        return

                self.dialogue_search_sfw_daily = VectorSearch(
                    use_in_memory_db=False, collection_name="dialogue_examples_sfw_daily"
                )
                self.dialogue_search_sfw_study = VectorSearch(
                    use_in_memory_db=False, collection_name="dialogue_examples_sfw_study"
                )
                self.dialogue_search_nsfw = VectorSearch(
                    use_in_memory_db=False, collection_name="dialogue_examples_nsfw"
                )
                self.dialogue_search_sensitive = self.dialogue_search_nsfw

                def _deferred_vector_ingest():
                    try:
                        ai_studio_doc_ids = _collect_ai_studio_doc_ids()
                        _purge_ai_studio_docs(self.dialogue_search_sfw_daily, ai_studio_doc_ids)
                        _purge_ai_studio_docs(self.dialogue_search_sfw_study, ai_studio_doc_ids)
                        _purge_ai_studio_docs(self.dialogue_search_nsfw, ai_studio_doc_ids)

                        if os.path.isdir(generated_dir):
                            def _maybe_ingest(vs: Any, jsonl_filename_keywords: List[str]):
                                if not auto_ingest:
                                    return
                                try:
                                    col = getattr(vs, "collection", None)
                                    if col is not None and callable(getattr(col, "count", None)):
                                        if int(col.count() or 0) > 0:
                                            return
                                except Exception:
                                    pass

                                try:
                                    files = []
                                    for fn in os.listdir(generated_dir):
                                        low = fn.lower()
                                        if not low.endswith(".jsonl"):
                                            continue
                                        if any(k in low for k in jsonl_filename_keywords):
                                            files.append(os.path.join(generated_dir, fn))
                                    for p in sorted(files):
                                        with open(p, "r", encoding="utf-8") as f:
                                            for line in f:
                                                raw = (line or "").strip()
                                                if not raw:
                                                    continue
                                                try:
                                                    obj = json.loads(raw)
                                                except Exception:
                                                    continue
                                                if not isinstance(obj, dict):
                                                    continue
                                                did = str(obj.get("id") or "").strip()
                                                if "ai_studio" in did.lower():
                                                    continue
                                                scenario = str(obj.get("scenario") or "").strip()
                                                mode = str(obj.get("mode") or "").strip()
                                                turns = obj.get("dialogue")
                                                if not did or not isinstance(turns, list):
                                                    continue

                                                for i, t in enumerate(turns):
                                                    if not isinstance(t, dict):
                                                        continue
                                                    user_text = str(t.get("user") or "").strip()
                                                    resp_text = str(t.get("response") or "").strip()
                                                    if not user_text or not resp_text:
                                                        continue
                                                    doc_id = f"{did}_{i}"
                                                    doc_text = (
                                                        f"场景：{scenario}\n"
                                                        f"User: {user_text}\n"
                                                        f"Aveline: {resp_text}"
                                                    ).strip()
                                                    meta = {
                                                        "mode": mode,
                                                        "scenario": scenario,
                                                        "source": os.path.basename(p),
                                                    }
                                                    try:
                                                        vs.add_document(doc_id, doc_text, metadata=meta)
                                                    except Exception:
                                                        continue
                                except Exception:
                                    return

                            _maybe_ingest(self.dialogue_search_sfw_daily, ["sfw", "daily"])
                            _maybe_ingest(self.dialogue_search_sfw_study, ["sfw", "study"])
                            _maybe_ingest(self.dialogue_search_nsfw, ["nsfw"])
                        logger.info("VectorSearch 后台数据导入完成")
                    except Exception as e:
                        logger.warning(f"VectorSearch 后台数据导入失败: {e}")

                import threading
                threading.Thread(target=_deferred_vector_ingest, daemon=True).start()
                logger.info("VectorSearch 实例创建完成 (%.3fs)", time.perf_counter() - _t_vs)
            except Exception as e:
                logger.warning(f"初始化对话示例检索失败: {e}")

            # 后台预热嵌入模型（延后到此处启动，避免与 register_all_tools / VectorSearch 创建抢 GIL）
            # 放在 try/except 外，确保即使 VectorSearch 初始化失败也会预加载（add_memory 仍需要嵌入）
            def _bg_preload_embedding():
                try:
                    from memory.embedding_generator import get_embedding_generator
                    gen = get_embedding_generator()
                    gen.ensure_model_loaded()
                    logger.info("嵌入模型后台预热完成")
                except Exception as e:
                    logger.warning(f"嵌入模型后台预热失败: {e}")

            import threading
            threading.Thread(target=_bg_preload_embedding, daemon=True, name="embedding-preload").start()

            _t_inst = time.perf_counter()
            llm_status = self.llm_module.get_status()
            if llm_status.get("llm_status", {}).get("instances_count", 0) == 0:
                logger.info("未找到LLM实例，创建默认LLM实例...")
                config = LLMConfig(
                    model_name="default",
                    device="auto",
                    max_context_length=4096,
                    temperature=self.config.temperature
                )
                create_instance("default_llm", config)
            logger.info("默认LLM实例检查完成 (%.3fs)", time.perf_counter() - _t_inst)
            self.is_initialized = True
            logger.info(f"ChatAgent初始化完成: {self.config.agent_name} (总耗时 %.3fs)", time.perf_counter() - _init_t0)

    async def _check_triggers(self, user_id: str, message: str) -> Optional[str]:
        return await async_check_triggers(self, user_id, message)

    async def handle_message(
        self,
        user_id: str,
        message: str,
        message_id: str = None,
        system_prompt_override: str = None,
        save_history: bool = True,
    ):
        return await handle_message_impl(
            self,
            user_id,
            message,
            message_id,
            system_prompt_override=system_prompt_override,
            save_history=save_history,
        )

    async def _maybe_generate_session_title(self, session_id: str, user_msg: str, assistant_msg: str):
        await maybe_generate_session_title(self, session_id, user_msg, assistant_msg)

    def _determine_mode(self, message: str = "") -> str:
        return determine_mode(self, message)

    def _get_dynamic_system_prompt(self, user_id: str = None, active_tools: List[str] = None, mode: str = None, message: str = None, user_name: str = None, persona_filename: str = None) -> str:
        return get_dynamic_system_prompt(self, user_id, active_tools, mode, message, user_name, persona_filename=persona_filename)

    def _sync_check_daily_routine_logic(self, user_id: str) -> Optional[str]:
        return sync_check_daily_routine_logic(self, user_id)

    async def _check_daily_routine(self, user_id: str) -> Optional[str]:
        return await async_check_daily_routine(self, user_id)

    async def stream_chat(
        self,
        user_id: str,
        message: Any,
        message_id: str = None,
        save_history: bool = True,
        model_hint: str = None,
        system_prompt: str = None,
        max_tokens: int = None,
        temperature: float = None,
        user_name: str = None,
        persona_filename: str = None,
        service_dynamic_context: str = None,
        api_key: str = None,
        platform: str = None,
        history_override: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        pending: List[Dict[str, Any]] = []
        saw_content = False
        async for chunk in stream_chat_impl(
            self,
            user_id=user_id,
            message=message,
            message_id=message_id,
            save_history=save_history,
            model_hint=model_hint,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            user_name=user_name,
            persona_filename=persona_filename,
            service_dynamic_context=service_dynamic_context,
            api_key=api_key,
            platform=platform,
            history_override=history_override,
        ):
            if isinstance(chunk, dict) and chunk.get("error"):
                if not saw_content:
                    yield {"error": str(chunk.get("error")), "done": True}
                    return
                yield chunk
                return

            if not saw_content:
                has_content = False
                if isinstance(chunk, dict):
                    if chunk.get("type") == "token" and chunk.get("content"):
                        has_content = True
                    elif chunk.get("content"):
                        has_content = True
                    elif chunk.get("done") is True:
                        has_content = True

                if has_content:
                    saw_content = True
                    for item in pending:
                        yield item
                    pending.clear()
                    yield chunk
                else:
                    pending.append(chunk)
                continue

            yield chunk

    def extract_and_strip_emotion(self, content: str) -> Tuple[str, Optional[str]]:
        """
        从回复中提取情绪标签
        代理到 core.utils.text_processor.extract_and_strip_emotion
        """
        return extract_and_strip_emotion(content)

    async def _perform_context_summary(
        self, user_id: str, memory_manager: WeightedMemoryManager
    ):
        await perform_context_summary(self, user_id, memory_manager)

    def _is_study_mode(self, message: str, model_hint: str = None) -> bool:
        return is_study_mode(message, model_hint)

    def _classify_subject(self, message: str) -> Optional[str]:
        return classify_subject(message)

    def _get_english_word_context(self) -> Optional[Dict[str, str]]:
        return get_english_word_context(self)

    async def _build_conversation_history(
        self,
        user_id: str,
        message: str,
        model_hint: str = None,
        system_prompt: str = None,
        user_name: str = None,
        persona_filename: str = None,
        active_tools: List[str] = None,
    ) -> List[Dict[str, str]]:
        return await build_conversation_history(
            self,
            user_id,
            message,
            model_hint,
            system_prompt_override=system_prompt,
            user_name=user_name,
            persona_filename=persona_filename,
            active_tools_override=active_tools,
        )

    async def clear_history(self, user_id: str, mode: str = 'all'):
        await history_clear_history(self, user_id, mode)

    async def _save_conversation_history(
        self,
        user_id: str,
        user_msg: str,
        assistant_msg: str,
        message_id: str,
        model_hint: str = None,
        extracted_topics: List[str] = None,
        thought: str = None,
        persona_filename: str = None,
        platform: str = None,
    ):
        await save_conversation_history(
            self,
            user_id,
            user_msg,
            assistant_msg,
            message_id,
            model_hint=model_hint,
            extracted_topics=extracted_topics,
            thought=thought,
            persona_filename=persona_filename,
            platform=platform,
        )

_default_agent = None

def get_default_chat_agent() -> ChatAgent:
    """
    获取默认的ChatAgent实例（单例模式）
    """
    global _default_agent
    if _default_agent is None:
        _default_agent = ChatAgent()
    return _default_agent

# Alias for backward compatibility and convenience
get_chat_agent = get_default_chat_agent
