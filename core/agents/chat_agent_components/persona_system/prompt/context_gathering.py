import json
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

from config.debug_config import is_debug_enabled
from core.services.life_simulation.service import get_life_simulation_service
from core.services.study.persona import StudyPersonaProfile
from core.utils.logger import get_logger
from memory.weighted_memory_manager import WeightedMemoryManager

logger = get_logger("ContextGathering")

def get_context_injection(effective_user_id: str, include_user_health: bool = False, memory_manager: Any = None) -> Dict[str, Any]:
    """获取生理、情绪等上下文信息

    Args:
        effective_user_id: 有效用户 ID
        include_user_health: 是否包含用户健康数据
        memory_manager: 可选的已有 WeightedMemoryManager 实例，避免重复创建
    """
    context = {
        "user_physiology": "",
        "life_sim_state": {},
        "emotion": {},
        "cpu_temp": 45,
        "ram_usage": 50,
        "vision_summary": "视觉传感器正常",
        "last_conversation_seconds": None
    }
    
    if include_user_health:
        try:
            from core.services.user_physiology.service import get_user_physiology_service
            user_phys_rec = get_user_physiology_service().get_latest(effective_user_id)
            source = str((user_phys_rec or {}).get("source") or "").strip().lower()
            is_test_source = source in {"tests", "test", "diagnostics", "debug"}
            if (
                isinstance(user_phys_rec, dict)
                and not user_phys_rec.get("is_stale")
                and not is_test_source
            ):
                u_metrics = user_phys_rec.get("metrics") or {}
                u_flags = user_phys_rec.get("flags") or {}
                u_parts = []
                if u_metrics.get("heart_rate_bpm"):
                    u_parts.append(f"心率:{u_metrics['heart_rate_bpm']}bpm")
                if u_metrics.get("spo2_percent"):
                    u_parts.append(f"血氧:{u_metrics['spo2_percent']}%")
                if u_metrics.get("sleep_hours_last_night"):
                    u_parts.append(f"昨晚睡眠:{u_metrics['sleep_hours_last_night']}h")
                if u_metrics.get("stress_level"):
                    u_parts.append(f"压力:{u_metrics['stress_level']}")
                u_urgent = u_flags.get("urgent_needs") or []
                if u_urgent:
                    u_parts.append(f"预警:{','.join(u_urgent)}")
                
                if u_parts:
                    context["user_physiology"] = f"\n- 用户健康状态: {', '.join(u_parts)}"
        except Exception:
            pass

    try:
        life_sim = get_life_simulation_service()
        ls_state = life_sim.get_state()
        context["life_sim_state"] = ls_state
        if isinstance(ls_state, dict):
             context["vision_summary"] = str(ls_state.get("vision_summary") or "视觉传感器正常")
    except Exception as e:
        logger.warning(f"获取生活模拟状态失败: {e}")

    try:
        from core.emotion import get_emotion_manager
        mgr = get_emotion_manager()
        context["emotion"] = mgr.get_effective_payload(effective_user_id) or {}
    except Exception:
        pass

    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        context["cpu_temp"] = 40 + (cpu_percent / 2)
        context["ram_usage"] = psutil.virtual_memory().percent
    except Exception:
        pass
    
    try:
        if isinstance(memory_manager, WeightedMemoryManager):
            last_ts = None
            with memory_manager.lock:
                for mem in reversed(memory_manager.short_term_memory):
                    ts = mem.get("timestamp")
                    if ts and isinstance(ts, (int, float)):
                        last_ts = ts
                        break
        else:
            mm = WeightedMemoryManager(effective_user_id)
            last_ts = None
            with mm.lock:
                for mem in reversed(mm.short_term_memory):
                    ts = mem.get("timestamp")
                    if ts and isinstance(ts, (int, float)):
                        last_ts = ts
                        break

        if not last_ts:
            try:
                from core.services.chat_history_store import get_chat_history_store
                store = get_chat_history_store()
                events = store.list_conversation_events(
                    effective_user_id, limit=5, roles=["user", "assistant"],
                )
                for event in reversed(events):
                    if isinstance(event, dict):
                        ts = float(event.get("timestamp", 0) or 0)
                        if ts > 0:
                            last_ts = ts
                            break
            except Exception:
                pass
        
        if last_ts:
            elapsed_seconds = max(0, int(time.time() - last_ts))
            context["last_conversation_seconds"] = elapsed_seconds
    except Exception as e:
        if is_debug_enabled("context_gathering"):
            logger.info(f"获取最后对话时间失败: {e}")
        
    return context

def prepare_emotion_context(ctx_data: Dict[str, Any]) -> Tuple[str, int, int, str]:
    emotion_payload = ctx_data.get("emotion", {})
    emotion_primary = str(emotion_payload.get("primary_emotion") or "neutral").strip() or "neutral"
    try:
        emotion_intensity = int(round(float(emotion_payload.get("intensity", 0.0) or 0.0) * 100.0))
    except Exception:
        emotion_intensity = 0
    try:
        emotion_confidence = int(round(float(emotion_payload.get("confidence", 0.0) or 0.0) * 100.0))
    except Exception:
        emotion_confidence = 0
    
    emotion_sub_emotions = {}
    try:
        sub = emotion_payload.get("sub_emotions")
        if isinstance(sub, dict):
            emotion_sub_emotions = dict(sub)
    except Exception:
        pass
        
    emotion_sub_json = ""
    try:
        emotion_sub_json = json.dumps(emotion_sub_emotions, ensure_ascii=False, sort_keys=True)
    except Exception:
        pass
        
    return emotion_primary, emotion_intensity, emotion_confidence, emotion_sub_json

def determine_model_info(agent: Any) -> Tuple[str, bool, bool, Optional[int]]:
    model_name = ""
    is_cloud_model = False
    is_local_gguf = False
    try:
        if agent.llm_module and hasattr(agent.llm_module, "get_current_model_name"):
            model_name = str(agent.llm_module.get_current_model_name() or "")
            mn_lower = model_name.lower()
            is_cloud_model = mn_lower.startswith("cloud:") or "cloud:" in mn_lower
            is_local_gguf = (not is_cloud_model) and mn_lower.endswith(".gguf")
    except Exception:
        pass

    prompt_budget = None
    if is_local_gguf:
        try:
            from config.integrated_config import get_settings
            n_ctx = int(getattr(get_settings().model, "n_ctx", 0) or 0)
            if n_ctx > 0:
                prompt_budget = max(1200, min(3500, int(n_ctx * 1.2)))
        except Exception:
            prompt_budget = 2500
            
    return model_name, is_cloud_model, is_local_gguf, prompt_budget

def prepare_life_stats(life_sim_state: Dict[str, Any]) -> Tuple[Dict, Dict, Dict]:
    life_stats = life_sim_state.get("life") if isinstance(life_sim_state.get("life"), dict) else {}
    immune_stats = life_sim_state.get("immune") if isinstance(life_sim_state.get("immune"), dict) else {}
    bio_stats = life_sim_state.get("bio") if isinstance(life_sim_state.get("bio"), dict) else {}
    return life_stats, immune_stats, bio_stats

def get_tool_injection(agent: Any, prompt_budget: Optional[int], active_tools: Optional[List[str]], persona_filename: Optional[str] = None) -> str:
    """根据当前激活的工具列表，注入工具使用引导到 prompt 中。

    核心目的：让 LLM 明确知道在什么场景下该优先使用哪个工具，
    避免出现"用户提到过去对话时 LLM 却用 web_search 搜互联网"的问题。
    """
    if not active_tools:
        return ""

    # intimate 类工具只对Ling可用
    is_ling = persona_filename and "ling" in persona_filename.lower()
    intimate_tools = {"enter_intimate_mode", "exit_intimate_mode", "apply_status_effect", "present_choice"}
    if not is_ling:
        active_tools = [t for t in active_tools if t not in intimate_tools]
        if not active_tools:
            return ""

    parts = [
        "【工具调用总规则】\n"
        "当你判断需要工具时，直接使用系统提供的原生工具调用能力。\n"
        "- 给用户的回复只包含自然语言，不要把工具调用相关的内容写进回复里\n"
        "- 先拿到工具结果，再用自然语言回复用户"
    ]

    # 当 search_chat_history 被激活时，注入优先级引导
    if "search_chat_history" in active_tools:
        parts.append(
            "【工具使用优先级】\n"
            "用户提到了过去的对话或历史记录。此时必须优先使用 search_chat_history 搜索聊天记录，"
            "而不是用 web_search 搜索互联网。\n"
            "- 用户说'之前说过/聊过/提过'→ 先用 search_chat_history 搜聊天记录\n"
            "- 用户说'搜历史记录/聊天记录'→ 用 search_chat_history\n"
            "- 只有聊天记录中确实找不到时，才考虑 web_search\n"
            "- 搜索时用用户提到的关键人名/事件名作为 query，不要用太宽泛的词\n"
            "- 如果用户此刻只是随口确认、补充或自问自答，不要为了形式正确而滥用工具"
        )

    # 当 message_peer 被激活时，注入互聊引导
    if "message_peer" in active_tools:
        peer_name = "Ling" if is_ling else "七濑 澪" if not is_ling else "对方角色"
        parts.append(
            f"【互聊工具引导】\n"
            f"你可以使用 message_peer 工具主动给{peer_name}发QQ消息。"
            f"当你产生'去找{peer_name}聊聊'的意图时，直接调用工具，不要只在对话里说。\n"
            f"适用场景：\n"
            f"- 你说'我去看看{peer_name}'、'得去找她'等 → 调用 message_peer\n"
            f"- 你关心{peer_name}的状态（如'她精力归零了'）→ 调用 message_peer\n"
            f"- 你想约{peer_name}做某事（如'叫她一起吃饭'）→ 调用 message_peer\n"
            f"- 你想和{peer_name}分享某件事 → 调用 message_peer\n"
            f"注意：调用后系统会生成一段自然的对话剧本，不是直接发你输入的内容。"
            f"你仍然可以继续和主人聊天，不需要等待剧本生成完毕。"
        )

    if not parts:
        return ""

    return "\n\n" + "\n\n".join(parts)

def get_instruction_injection(agent: Any, user_id: str) -> str:
    instruction_injection = ""
    if user_id:
        try:
            mm = agent._get_memory_manager(user_id)
            if isinstance(mm, WeightedMemoryManager):
                prompts: List[Dict[str, Any]] = []
                if hasattr(mm, "get_important_prompts"):
                    prompts = mm.get_important_prompts()

                if not prompts:
                    with mm.lock:
                        sorted_memories = sorted(
                            mm.weighted_memories.values(),
                            key=lambda x: x["timestamp"],
                            reverse=True,
                        )
                        for mem in sorted_memories:
                            if "user_instruction" in mem.get("topics", []):
                                prompts.append(mem)
                                if len(prompts) >= 5:
                                    break

                if prompts:
                    instruction_injection = (
                        "\n\n# Important Memories & Instructions (Core Layer)\n"
                        "The user has explicitly requested the following or these are core memories "
                        "(you MUST follow/remember these):\n"
                        + "\n".join([f"- {p.get('content', '')}" for p in prompts])
                    )
        except Exception as e:
            logger.warning(f"Failed to load user instructions: {e}")
    return instruction_injection

def get_study_folder_history_injection() -> str:
    return StudyPersonaProfile().build_history_injection()

def build_food_context_text(life_stats: Dict[str, Any]) -> str:
    """构建完整的食物系统上下文，包含饱腹值描述、库存、消化状态和行动指引"""
    try:
        now_ts = time.time()
        hunger = float(life_stats.get("hunger", 100.0) if life_stats.get("hunger") is not None else 100.0)
        thirst = float(life_stats.get("thirst", 100.0) if life_stats.get("thirst") is not None else 100.0)
        energy = float(life_stats.get("energy", 100.0) if life_stats.get("energy") is not None else 100.0)
        inventory = life_stats.get("food_inventory") if isinstance(life_stats, dict) else []
        digestion_queue = life_stats.get("digestion_queue") if isinstance(life_stats, dict) else []
        
        inv_count = 0
        if isinstance(inventory, list):
            for item in inventory:
                if not isinstance(item, dict):
                    continue
                try:
                    q = int(item.get("quantity") or 0)
                except Exception:
                    q = 0
                if q > 0:
                    inv_count += q
        
        # 消化队列详细信息
        digest_text = ""
        active_digestion = []
        if isinstance(digestion_queue, list):
            for entry in digestion_queue:
                if not isinstance(entry, dict):
                    continue
                try:
                    end_ts = float(entry.get("end_ts") or 0.0)
                except Exception:
                    continue
                if end_ts <= now_ts:
                    continue
                # 有效消化中
                remaining_min = int((end_ts - now_ts) / 60) + 1
                effects = entry.get("effects") or {}
                effect_parts = []
                for key, label in [("hunger", "饱腹"), ("thirst", "口渴"), ("energy", "精力"), ("health", "健康")]:
                    try:
                        v = float(effects.get(key) or 0.0)
                    except Exception:
                        v = 0.0
                    if v != 0.0:
                        effect_parts.append(f"{label}{'+' if v > 0 else ''}{v:.0f}")
                buff_desc = str(entry.get("buff_desc") or "").strip()
                name = buff_desc if buff_desc else "食物"
                effect_str = ", ".join(effect_parts) if effect_parts else "无效果"
                active_digestion.append(f"{name}({effect_str}, 剩余{remaining_min}min)")
        if active_digestion:
            digest_text = "- 消化中：" + ", ".join(active_digestion) + "\n"
        
        fullness_hint = "很饱"
        if hunger < 30:
            fullness_hint = "很饿"
        elif hunger < 60:
            fullness_hint = "有点饿"
        elif hunger < 85:
            fullness_hint = "一般"
        
        auto_eat_hint = "你可以自己去拿东西吃。"
        if hunger >= 90:
            auto_eat_hint = "你已经很饱了，用户投喂时可以拒绝。"
        
        last_meal_text = ""
        last_meal = life_stats.get("_last_meal")
        if isinstance(last_meal, dict) and last_meal.get("food_name"):
            food_name = last_meal["food_name"]
            reason = last_meal.get("reason", "")
            source = last_meal.get("source", "")
            
            # 用户投喂的提示
            if source == "user_feed":
                last_meal_text = f"- 刚刚主人给你投喂了{food_name}，记得感谢主人！\n"
            elif reason:
                last_meal_text = f"- 你上一顿吃了{food_name}，因为{reason}\n"
            else:
                last_meal_text = f"- 你上一顿吃了{food_name}\n"
        
        return (
            "\n【你的饮食系统状态（注意：这是你自己的状态，不是用户的）】\n"
            f"- 饱腹{hunger:.0f}（{fullness_hint}），口渴{thirst:.0f}，精力{energy:.0f}\n"
            f"- 食物库存{inv_count}份\n"
            f"{digest_text}"
            f"{last_meal_text}"
            f"- {auto_eat_hint}\n"
        )
    except Exception:
        return ""


def get_inventory_and_digestion_summary(life_stats: Dict[str, Any]) -> Tuple[str, str]:
    now_ts = time.time()
    food_inventory_summary = "空"
    try:
        inv = life_stats.get("food_inventory") if isinstance(life_stats, dict) else None
        inv_items = []
        if isinstance(inv, list):
            for item in inv:
                if not isinstance(item, dict):
                    continue
                food_id = str(item.get("food_id") or "").strip()
                if not food_id:
                    continue
                try:
                    q = int(item.get("quantity") or 0)
                except Exception:
                    q = 0
                if q <= 0:
                    continue
                try:
                    exp = float(item.get("expire_at") or 0.0)
                except Exception:
                    exp = 0.0
                if exp and exp <= now_ts:
                    continue
                inv_items.append({"food_id": food_id, "quantity": q, "expire_at": exp})

        if inv_items:
            inv_items.sort(key=lambda x: float(x.get("expire_at") or 0.0))
            total_q = 0
            top_parts = []
            for idx, item in enumerate(inv_items):
                try:
                    q = int(item.get("quantity") or 0)
                except Exception:
                    q = 0
                total_q += max(0, q)
                if idx < 3:
                    food_id = str(item.get("food_id") or "").strip() or "?"
                    try:
                        exp = float(item.get("expire_at") or 0.0)
                    except Exception:
                        exp = 0.0
                    if exp and exp > now_ts:
                        remaining_h = int(max(0.0, exp - now_ts) // 3600)
                        top_parts.append(f"{food_id}x{q}(剩{remaining_h}h)")
                    else:
                        top_parts.append(f"{food_id}x{q}")
            food_inventory_summary = f"{total_q} 份：" + "，".join(top_parts)
    except Exception:
        food_inventory_summary = "空"

    digestion_summary = "无"
    try:
        dq = life_stats.get("digestion_queue") if isinstance(life_stats, dict) else None
        active_entries = []
        buffs = []
        if isinstance(dq, list):
            for entry in dq:
                if not isinstance(entry, dict):
                    continue
                try:
                    end_ts = float(entry.get("end_ts") or 0.0)
                except Exception:
                    end_ts = 0.0
                if end_ts and end_ts > now_ts:
                    active_entries.append(entry)
                    buff = str(entry.get("buff_desc") or "").strip()
                    if buff and buff not in buffs:
                        buffs.append(buff)

        if active_entries:
            soonest_sec = None
            effect_dims = set()
            for entry in active_entries:
                try:
                    end_ts = float(entry.get("end_ts") or 0.0)
                except Exception:
                    end_ts = 0.0
                if end_ts:
                    remain = max(0.0, end_ts - now_ts)
                    if soonest_sec is None or remain < soonest_sec:
                        soonest_sec = remain
                effects = entry.get("effects") if isinstance(entry.get("effects"), dict) else {}
                for k in ("hunger", "thirst", "energy", "health"):
                    try:
                        if float(effects.get(k) or 0.0) != 0.0:
                            effect_dims.add(k)
                    except Exception:
                        continue
            dim_map = {"hunger": "饱腹", "thirst": "解渴", "energy": "提神", "health": "恢复"}
            dims = [dim_map.get(d, d) for d in ("hunger", "thirst", "energy", "health") if d in effect_dims]
            mins = int((soonest_sec or 0.0) // 60) if soonest_sec is not None else 0
            status_str = f"{len(active_entries)} 项进行中，最近结束 {mins}min"
            if dims:
                status_str += f"，效果：{'/'.join(dims)}"
            if buffs:
                status_str += f" / 状态：{', '.join(buffs)}"
            digestion_summary = status_str
    except Exception:
        digestion_summary = "无"
        
    return food_inventory_summary, digestion_summary
