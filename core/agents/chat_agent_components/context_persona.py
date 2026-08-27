import asyncio
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger
from memory.weighted_memory_manager import WeightedMemoryManager

logger = get_logger("ChatAgent")


_BASE_TOOL_NAMES = (
    "search_tools",
    "get_current_time",
    "calculator",
    "text_to_speech",
)

# 工具仍全部保留在注册表中；这里只决定本轮需要把哪些 schema 发给模型。
# 路由词宁可覆盖常见自然表达，也不要把 80+ 个工具定义恒定塞进上下文。
_MESSAGE_TOOL_ROUTES = (
    (("天气", "气温", "下雨", "降雨", "台风", "weather", "temperature"), ("get_weather",)),
    (("提醒", "闹钟", "喊我", "叫我", "分钟后", "小时后", "remind", "alarm"), ("set_reminder",)),
    (("计划", "todo", "待办", "安排", "日程"), (
        "get_plan", "add_plan_item", "update_plan_item", "remove_plan_item",
        "mark_plan_item_status", "generate_today_plan", "generate_tomorrow_plan",
    )),
    ((
        "做完", "写完", "背完", "搞完", "完成了", "搞定", "弄好了",
        "开始做", "不做了", "跳过",
    ), ("mark_plan_item_status",)),
    (("日记", "每日总结", "今日总结", "月度总结", "月总结"), (
        "write_diary", "read_diary", "read_daily_summary", "read_monthly_summary",
    )),
    (("今日生活", "今日画像", "今天做了什么", "今天干了什么"), ("get_daily_summary",)),
    ((
        "起床", "睡觉", "睡了", "醒了", "吃饭", "吃了", "喝了", "学习了",
        "玩了", "我刚", "刚刚", "刚才", "我今天", "今天我",
    ), ("record_daily_activity",)),
    (("作息记录", "睡眠记录", "睡觉时间", "起床时间", "记错了"), ("update_sleep_record",)),
    (("体重", "体脂", "肌肉量", "身体数据"), ("record_body_metrics", "query_health_data")),
    (("心率", "步数", "健康数据", "手表", "睡眠数据", "饮水"), ("query_health_data",)),
    (("生病", "不舒服", "忙碌", "状态好了", "病好了", "持续状态"), (
        "add_user_status", "remove_user_status", "get_user_status",
    )),
    (("买吃", "买点吃", "投喂", "喂你", "菜单", "库存", "想吃", "嘴馋"), (
        "buy_food", "feed_food", "list_food", "show_inventory", "crave_food",
        "list_food_cravings", "get_aveline_meals",
    )),
    (("商城", "礼物", "商品", "购物", "买个", "送给"), (
        "browse_shop", "buy_shop_item", "show_gift_inventory", "use_gift_item",
    )),
    (("专注", "番茄钟", "分心率", "focus session"), (
        "get_current_focus_session", "get_focus_session_summary",
    )),
    (("进入学习模式", "开始学习", "学习模式"), ("enter_study_mode",)),
    (("退出学习模式", "学完了", "不学了", "休息一下"), ("exit_study_mode",)),
    (("知识库", "学习资料", "公式", "知识点"), ("search_knowledge_base",)),
    (("单词", "背词", "词汇", "word", "vocabulary"), ("update_word_progress", "word_quiz")),
    (("创建文件", "生成文件", "导出文件", "excel", "word文档", "pdf"), ("create_file",)),
    (("学习文件", "学习笔记", "学习记录"), ("study_data_management",)),
    (("companion_data", "角色文件", "数据文件"), ("aveline_daily_data",)),
    ((
        "之前说", "上次说", "以前说", "之前聊", "上次聊", "历史记录",
        "聊天记录", "说过", "你之前", "你上次", "我之前", "我上次",
        "跟你说过", "搜记录", "搜聊天", "查历史", "翻记录",
    ), ("search_chat_history",)),
    (("回忆", "记得我", "我的偏好", "我喜欢", "我讨厌", "我习惯"), ("search_memory", "record_preference")),
    (("人物档案", "这个人", "他是谁", "她是谁", "认识的人"), ("query_person_profile",)),
    (("记住这个偏好", "长期偏好", "以后都", "我一直"), ("record_preference",)),
    (("活跃任务", "任务搁置", "以后继续", "任务完成"), ("record_active_task", "complete_active_task")),
    (("总结这段", "记录摘要", "重要节点"), ("record_summary",)),
    (("经验", "最佳实践", "以后应该"), ("record_experience",)),
    (("Ling怎么样", "澪怎么样", "她在干嘛", "她吃饭了吗"), ("check_peer_status",)),
    (("你今天干嘛", "你今天做什么", "她今天干嘛", "角色计划"), ("get_character_daily_plan",)),
    (("运行程序", "运行进程", "电脑在干嘛", "屏幕上", "看屏幕"), ("check_running_processes", "look_at_screen")),
    (("手机应用", "已安装应用", "打开应用", "启动应用", "强制停止", "使用时长", "应用限额"), (
        "list_installed_apps", "start_app", "force_stop_app", "get_app_usage_time", "set_app_limit",
    )),
    (("手机屏幕", "手机截图"), ("capture_phone_screen",)),
    (("位置", "定位", "经纬度", "我在哪"), ("get_device_location",)),
    (("蓝牙", "耳机", "配对设备"), (
        "list_paired_bluetooth_devices", "scan_bluetooth_devices",
        "pair_bluetooth_device", "unpair_bluetooth_device",
    )),
    (("壁纸",), ("set_wallpaper",)),
    (("玩法", "换个玩法", "不玩了"), ("list_playsets", "enable_playset", "disable_playset")),
    (("仿生体状态", "你的状态", "你饿吗", "你渴吗", "你累吗"), ("get_bionic_state",)),
)


def select_message_tools(
    message: str,
    *,
    mode: str = "chat",
    include_web_search: bool = True,
) -> List[str]:
    """根据本轮文本选择候选工具，保持顺序稳定以利于 prompt cache。"""
    selected = list(_BASE_TOOL_NAMES)
    if include_web_search:
        selected.append("web_search")

    message_lower = str(message or "").lower()
    for keywords, tool_names in _MESSAGE_TOOL_ROUTES:
        if any(keyword in message_lower for keyword in keywords):
            selected.extend(tool_names)

    if mode == "study":
        selected.extend(("get_study_profile", "enter_study_mode", "exit_study_mode"))

    return list(dict.fromkeys(selected))


async def prepare_active_tools(
    agent: Any, message: str, model_hint: Optional[str]
) -> List[str]:
    # 判断是否使用服务端web_search（智谱等厂商的原生搜索）
    use_server_side_search = False
    try:
        from config.model_config import should_use_server_side_web_search, is_web_search_enabled
        if is_web_search_enabled() and hasattr(agent, "llm_module"):
            current_model = agent.llm_module.get_current_model_name()
            current_provider = ""
            if current_model and current_model.startswith("cloud:"):
                parts = current_model.split(":", 2)
                if len(parts) >= 2:
                    current_provider = parts[1]
            model_name = current_model.split(":")[-1] if ":" in current_model else current_model
            use_server_side_search = should_use_server_side_web_search(current_provider, model_name)
    except Exception:
        pass

    mode = "chat"
    if hasattr(agent, "_is_study_mode") and agent._is_study_mode(message, model_hint):
        mode = "study"

    # 服务端搜索时不在本地工具列表中添加 web_search；其余工具按本轮意图注入。
    web_search_enabled = False
    if not use_server_side_search:
        try:
            from config.model_config import is_web_search_enabled
            web_search_enabled = bool(is_web_search_enabled())
        except Exception:
            web_search_enabled = True
    active_tools = select_message_tools(
        message,
        mode=mode,
        include_web_search=web_search_enabled,
    )

    if not message:
        return active_tools

    msg_lower = message.lower()
    vocab_keywords = [
        "单词",
        "英语",
        "背诵",
        "复习",
        "word",
        "vocabulary",
        "study",
        "exam",
        "grade",
    ]
    should_check_vocab = mode == "study" or any(k in msg_lower for k in vocab_keywords)

    if should_check_vocab and getattr(agent, "vocab_manager", None):
        try:
            stats = await asyncio.to_thread(agent.vocab_manager.get_stats)
            due_count = stats.get("due_words", 0)
            if due_count > 0 or should_check_vocab:
                if "update_word_progress" not in active_tools:
                    active_tools.append("update_word_progress")
            if due_count > 0:
                await asyncio.to_thread(agent.vocab_manager.get_daily_words, limit=3)
        except Exception as e:
            logger.warning(f"Failed to check vocab status: {e}")

    # 学习画像工具：学习相关话题时激活
    study_profile_keywords = [
        "学习", "考试", "错题", "易错", "进度", "掌握", "不会", "没学会",
        "数学", "英语", "物理", "化学", "语文", "生物", "历史", "地理",
        "高考", "中考", "刷题", "练习", "作业", "成绩", "分数",
        "知识", "公式", "定理", "考点", "重点",
    ]
    if mode == "study" or any(k in msg_lower for k in study_profile_keywords):
        if "get_study_profile" not in active_tools:
            active_tools.append("get_study_profile")

    active_care_keywords = [
        "主动关怀", "active care", "关怀", "打扰", "烦我", "别来", "别发",
        "少发", "多发", "发少", "发多", "频率", "间隔", "多久发",
        "暂停关怀", "恢复关怀", "关闭关怀", "开启关怀",
        "安静", "别吵", "别打扰", "静一静", "别烦",
        "一会儿再", "晚点再", "过会儿", "过一会",
        "小时后", "分钟后",
        "定时", "定时发", "定时找",
    ]
    if any(k in msg_lower for k in active_care_keywords):
        for t in [
            "adjust_active_care_frequency",
            "pause_active_care",
            "schedule_active_care_message",
            "toggle_active_care",
            "get_active_care_status",
        ]:
            if t not in active_tools:
                active_tools.append(t)

    # 双QQ模式下，始终启用 message_peer 工具
    try:
        from clients.bots.qq_adapter_main import QQAdapter
        active_instances = QQAdapter.get_active_instances()
        if len(active_instances) >= 2:
            if "message_peer" not in active_tools:
                active_tools.append("message_peer")
    except Exception:
        pass

    return list(dict.fromkeys(active_tools))


async def resolve_persona_prompt(
    agent: Any,
    memory_manager: Any,
    user_id: str,
    message: str,
    active_tools: List[str],
    user_name: Optional[str],
    persona_filename: Optional[str] = None,
) -> str:
    persona_system_prompt = ""
    persona_signature = ""
    effective_persona_filename = str(persona_filename or "").strip()
    try:
        from core.character.managers.persona_manager import get_persona_manager
        pm = get_persona_manager()
        sig_filename = effective_persona_filename or str(pm.get_current_filename() or "").strip()
        sig_revision = int(getattr(pm, 'get_revision', lambda: 0)() or 0)
        persona_signature = f"{sig_filename}@{sig_revision}"
    except Exception:
        if effective_persona_filename:
            persona_signature = f"{effective_persona_filename}@0"
        else:
            persona_signature = ""

    existing_persona_ids: List[str] = []
    if isinstance(memory_manager, WeightedMemoryManager):
        try:
            def _get_persona_cache():
                return memory_manager.get_memories_by_topic("persona_base_prompt", limit=5)

            existing = await asyncio.to_thread(_get_persona_cache)
            for item in existing or []:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if item_id:
                    existing_persona_ids.append(str(item_id))
        except Exception:
            existing_persona_ids = []

    if not persona_system_prompt and hasattr(agent, "_get_dynamic_system_prompt"):
        try:
            mode = None
            if hasattr(agent, "_determine_mode"):
                mode = str(agent._determine_mode(message) or "").strip() or None
            try:
                persona_system_prompt = await asyncio.to_thread(
                    agent._get_dynamic_system_prompt,
                    user_id=user_id,
                    active_tools=active_tools,
                    mode=mode,
                    message=message,
                    user_name=user_name,
                    persona_filename=effective_persona_filename or None,
                )
                persona_system_prompt = str(persona_system_prompt or "").strip()
            except TypeError:
                persona_system_prompt = await asyncio.to_thread(
                    agent._get_dynamic_system_prompt,
                    user_id=user_id,
                    active_tools=active_tools,
                    mode=mode,
                    message=message,
                )
                persona_system_prompt = str(persona_system_prompt or "").strip()
        except Exception:
            persona_system_prompt = ""

    if not persona_system_prompt:
        try:
            from core.character.managers.persona_manager import get_persona_manager

            pm = get_persona_manager()
            if effective_persona_filename:
                persona_data = pm.get_persona_by_filename(effective_persona_filename)
            else:
                persona_data = pm.get_current_persona()
            if isinstance(persona_data, dict):
                persona_system_prompt = str(persona_data.get("system_prompt_template") or "").strip()
        except Exception:
            persona_system_prompt = ""

    if not persona_system_prompt:
        try:
            from core.character.aveline import get_aveline_system_prompt_template

            persona_system_prompt = str(get_aveline_system_prompt_template() or "").strip()
        except Exception:
            persona_system_prompt = ""

    if not persona_system_prompt:
        persona_system_prompt = str(getattr(agent.config, "system_prompt", "") or "").strip()

    if persona_system_prompt and isinstance(memory_manager, WeightedMemoryManager):
        # [OPTIMIZATION] 不要每次都去存/删 persona_prompt，只在签名改变时存一次，极大减少 I/O 阻塞
        try:
            def _write_persona_prompt_if_needed() -> None:
                # Check if we already have the latest signature
                needs_update = True
                for mid in list(existing_persona_ids):
                    try:
                        mem = memory_manager.weighted_memories.get(mid)
                        if mem and mem.get("metadata", {}).get("persona_signature") == persona_signature:
                            needs_update = False
                            break
                        else:
                            memory_manager.delete_message(mid)
                    except Exception:
                        pass
                
                if not needs_update:
                    return

                memory_manager.add_memory(
                    content=persona_system_prompt,
                    source="system",
                    topics=["persona_base_prompt"],
                    category="persona_prompt",
                    weight=1.0,
                    is_important=False,
                    metadata={
                        "hidden": True,
                        "persona_signature": persona_signature,
                        "user_name": user_name,
                        "conversation_id": user_id,
                        "is_system_cache": True,
                    },
                )
                # persona_prompt 已通过 _NON_DIALOGUE_CATEGORIES 过滤,
                # 不会进入 short_term_memory,无需再调整位置

            # fire and forget，不要阻塞主流程
            asyncio.create_task(asyncio.to_thread(_write_persona_prompt_if_needed))
        except Exception:
            pass

    return persona_system_prompt


def detect_cloud_mode(agent: Any, model_hint: Optional[str]) -> bool:
    is_cloud = False
    if model_hint:
        mh_lower = model_hint.lower()
        if mh_lower.startswith("cloud:") or "cloud:" in mh_lower:
            is_cloud = True
        elif any(k in mh_lower for k in ["siliconflow", "dashscope", "openai"]):
            is_cloud = True
        elif "deepseek" in mh_lower and not mh_lower.endswith(".gguf"):
            is_cloud = True
    if (
        not is_cloud
        and getattr(agent, "llm_module", None)
        and hasattr(agent.llm_module, "get_current_model_name")
    ):
        model_name = str(agent.llm_module.get_current_model_name())
        mn_lower = model_name.lower()
        if mn_lower.startswith("cloud:") or "cloud:" in mn_lower:
            is_cloud = True
    return is_cloud


async def resolve_scope_and_sensitive_mode(
    memory_manager: Any,
    user_id: str,
    scope_override: Optional[str],
    is_cloud: bool,
    messages: List[Dict[str, str]],
    persona_filename: Optional[str] = None,
) -> Tuple[str, bool]:
    is_sensitive_mode = False
    
    # 优先使用传入的 persona_filename 判断（per-conversation）
    if persona_filename:
        pf_lower = str(persona_filename).replace("\\", "/").lower()
        if pf_lower.startswith("sensitive/") or "/sensitive/" in pf_lower:
            is_sensitive_mode = True
    
    # 回退：检查全局 PersonaManager
    if not is_sensitive_mode:
        try:
            from core.character.managers.persona_manager import get_persona_manager
            pm = get_persona_manager()
            current_persona = str(pm.get_current_filename() or "").replace("\\", "/", -1).lower()
            if current_persona.startswith("sensitive/") or "/sensitive/" in current_persona:
                is_sensitive_mode = True
        except Exception:
            pass
        
    # Check PreferenceManager
    if not is_sensitive_mode:
        try:
            from core.managers.preference_manager import get_preference_manager
            prefs = get_preference_manager()
            if prefs.get_mode() == "privacy":
                is_sensitive_mode = True
        except Exception:
            pass

    try:
        mm = memory_manager
        if not is_sensitive_mode and mm is not None and hasattr(mm, "get_memories_by_topic"):
            def _get_sensitive_mode():
                return mm.get_memories_by_topic("sensitive_mode_control", limit=1)

            logger.info("[Context Build] Acquiring sensitive mode from mm (via to_thread)...")
            try:
                mode_memories = await asyncio.wait_for(
                    asyncio.to_thread(_get_sensitive_mode), timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.error("[Context Build] TIMEOUT: get_memories_by_topic took >10s! Lock contention?")
                mode_memories = None
            if mode_memories and "SENSITIVE_MODE_ON" in mode_memories[0].get("content", ""):
                is_sensitive_mode = True
                logger.info(f"User {user_id} is in SENSITIVE_MODE")
    except Exception as e:
        logger.warning(f"Failed to check Sensitive mode: {e}")

    scope = scope_override or ("cloud" if is_cloud else "local")
    if is_sensitive_mode:
        scope = "local"
    return scope, is_sensitive_mode
