"""自动进食逻辑模块"""

import json
import random
import time
import traceback
from typing import Any, Dict, List, TYPE_CHECKING

from config.debug_config import is_debug_enabled
from core.utils.json_utils import extract_json_object
from core.utils.logger import get_logger
from .meal_chat import trigger_meal_chat_check
from .meal_policy import resolve_food_decision, is_scheduled_meal_due
from .sleep_food_effects import (
    evaluate_auto_eat_gate,
    apply_late_snack_penalty,
    record_food_event,
    role_can_late_snack,
    resolve_role_auto_eat_context,
)

if TYPE_CHECKING:
    from .actor_manager import ActorManager

logger = get_logger("AUTO_EAT")

class AutoEatManager:
    """管理自动进食逻辑"""

    def __init__(self, life_stats: Dict[str, Any], actor_manager: "ActorManager"):
        self.life_stats = life_stats
        self.actor_manager = actor_manager
        self._last_auto_eat_ts: float = 0.0
        self._last_auto_eat_food_id: str = ""
        self._last_auto_eat_reason: str = ""

    async def maybe_auto_eat(self, now_ts: float):
        """检查并执行自动进食"""
        # 检查 Aveline 的状态
        hunger = float(self.life_stats.get("hunger", 100.0) if self.life_stats.get("hunger") is not None else 100.0)
        thirst = float(self.life_stats.get("thirst", 100.0) if self.life_stats.get("thirst") is not None else 100.0)
        
        # 也检查Ling的状态
        ling_state = self.actor_manager.get_actor_life_state("ling")
        ling_hunger = float(ling_state.get("hunger", 100.0) if ling_state.get("hunger") is not None else 100.0)
        ling_thirst = float(ling_state.get("thirst", 100.0) if ling_state.get("thirst") is not None else 100.0)

        # 如果双方都不饿不渴，跳过
        # 按时吃饭：饭点到了（当天该餐窗未吃正餐）即使不饿也应触发，与饥饿阈值解耦
        aveline_meal_due = is_scheduled_meal_due(now_ts, self.life_stats.get("_last_meal"))
        ling_meal_due = is_scheduled_meal_due(now_ts, ling_state.get("_last_meal"))
        aveline_needs_food = hunger < 65.0 or thirst < 55.0 or aveline_meal_due
        ling_needs_food = ling_hunger < 65.0 or ling_thirst < 55.0 or ling_meal_due
        if not aveline_needs_food and not ling_needs_food:
            return

        if is_debug_enabled("auto_eat"):
            logger.info(
                f"自动进食检查: Aveline hunger={hunger:.1f} thirst={thirst:.1f}, "
                f"Ling hunger={ling_hunger:.1f} thirst={ling_thirst:.1f}"
            )

        # 根据紧急程度调整冷却时间
        any_critical = (hunger < 40.0 or thirst < 35.0 or 
                       ling_hunger < 40.0 or ling_thirst < 35.0)
        cooldown = 1200.0 if any_critical else 2400.0
        elapsed = now_ts - float(self._last_auto_eat_ts or 0.0)
        if elapsed < cooldown:
            if is_debug_enabled("auto_eat"):
                logger.info(f"自动进食冷却中: {elapsed:.0f}s/{cooldown:.0f}s")
            return

        # 判断双方紧急程度，决定喂谁
        aveline_critical = hunger < 25.0 or thirst < 20.0
        ling_critical = ling_hunger < 25.0 or ling_thirst < 20.0

        # 双方都紧急时，两个都喂（Aveline 优先）
        fed_any = False
        if aveline_needs_food and (aveline_critical or not ling_critical or hunger <= ling_hunger):
            aveline_context = resolve_role_auto_eat_context(
                "aveline",
                fallback_activity=str(self.life_stats.get("activity") or "idle"),
            )
            # 先喂 Aveline
            meal_meta = self._determine_food_type(
                now_ts, hunger, thirst, self.life_stats.get("_last_meal"), role_id="aveline"
            )
            gate = evaluate_auto_eat_gate(
                "aveline",
                now_ts=now_ts,
                hunger=hunger,
                thirst=thirst,
                target_type=str(meal_meta.get("target_type") or "snack"),
                fallback_activity=str(self.life_stats.get("activity") or "idle"),
                sleep_summary=aveline_context.get("sleep_summary"),
                current_activity=str(aveline_context.get("current_activity") or "idle"),
            )
            if not gate.allowed:
                if is_debug_enabled("auto_eat"):
                    logger.info("自动进食跳过 Aveline: %s", gate.reason)
            else:
                target_type = gate.target_type or str(meal_meta.get("target_type") or "snack")
                meal_meta["target_type"] = target_type
                meal_meta["gate_reason"] = gate.reason
                food_id, reason, share_with_ling, chat_while_eating = await self._select_food(target_type, hunger, thirst)
                if food_id:
                    if share_with_ling:
                        await self._share_food_with_ling(food_id, meal_meta)
                        logger.info(
                            f"LLM决策: 和Ling分享 {food_id}"
                            f"{', 边聊边吃' if chat_while_eating else ''}"
                        )
                    else:
                        await self._eat_food(food_id, meal_meta)
                    # 边聊边吃：触发 peer chat
                    if chat_while_eating:
                        trigger_meal_chat_check(
                            logger=logger,
                            debug_enabled=is_debug_enabled("auto_eat"),
                        )
                    self._last_auto_eat_ts = now_ts
                    self._last_auto_eat_food_id = food_id
                    fed_any = True
                else:
                    logger.warning(f"自动进食: 为Aveline选食物失败, target_type={target_type}, hunger={hunger:.1f}, thirst={thirst:.1f}")

        if ling_needs_food and (ling_critical or not aveline_critical or ling_hunger < hunger):
            ling_context = resolve_role_auto_eat_context(
                "ling",
                fallback_activity=str(ling_state.get("activity") or "idle"),
            )
            # 喂Ling
            ling_meal_meta = self._determine_food_type(
                now_ts, ling_hunger, ling_thirst, ling_state.get("_last_meal"), role_id="ling"
            )
            gate = evaluate_auto_eat_gate(
                "ling",
                now_ts=now_ts,
                hunger=ling_hunger,
                thirst=ling_thirst,
                target_type=str(ling_meal_meta.get("target_type") or "snack"),
                fallback_activity=str(ling_state.get("activity") or "idle"),
                sleep_summary=ling_context.get("sleep_summary"),
                current_activity=str(ling_context.get("current_activity") or "idle"),
            )
            if not gate.allowed:
                if is_debug_enabled("auto_eat"):
                    logger.info("自动进食跳过 Ling: %s", gate.reason)
            else:
                target_type = gate.target_type or str(ling_meal_meta.get("target_type") or "snack")
                ling_meal_meta["target_type"] = target_type
                ling_meal_meta["gate_reason"] = gate.reason
                food_id, reason, _, _ = await self._select_food(target_type, ling_hunger, ling_thirst)
                if food_id:
                    await self._feed_ling(food_id, target_type, ling_meal_meta)
                    if not fed_any:
                        self._last_auto_eat_ts = now_ts
                        self._last_auto_eat_food_id = food_id
                else:
                    logger.warning(f"自动进食: 为Ling选食物失败, target_type={target_type}")

    def _determine_food_type(
        self,
        now_ts: float,
        hunger: float,
        thirst: float,
        last_meal: Any,
        role_id: str,
    ) -> Dict[str, Any]:
        """根据餐窗、上次进食和睡眠状态确定食物类型。"""
        return resolve_food_decision(
            now_ts=now_ts,
            hunger=hunger,
            thirst=thirst,
            last_meal=last_meal if isinstance(last_meal, dict) else None,
            allow_late_snack=role_can_late_snack(role_id),
        )

    async def _select_food(
        self, target_type: str, hunger: float, thirst: float
    ) -> tuple:
        """选择要吃的食物：优先用 LLM 选（带理由），失败时 fallback 到随机。
        返回 (food_id, reason, share_with_ling, chat_while_eating)"""
        try:
            from core.food.manager import get_food_manager
            from core.food.data import get_food

            manager = get_food_manager()

            # 优先从库存选
            inventory = manager.get_inventory()
            inventory_candidates: List[str] = []
            for item in inventory:
                if not isinstance(item, dict):
                    continue
                fid = str(item.get("food_id") or "").strip()
                if not fid:
                    continue
                food = get_food(fid)
                if food and food.type == target_type:
                    inventory_candidates.append(fid)

            if inventory_candidates:
                picked, reason, share, chat = await self._choose_food_by_llm(
                    target_type=target_type,
                    candidate_ids=inventory_candidates,
                    hunger=hunger,
                    thirst=thirst,
                )
                if picked:
                    self._last_auto_eat_reason = reason
                    logger.info(f"从库存选了 {target_type}: {picked}，理由: {reason}")
                    return picked, reason, share, chat

            # 库存没有就从菜单选
            menu = manager.get_menu(food_type=target_type)
            if not menu:
                menu = manager.get_menu()
            if menu:
                menu_ids = [
                    str(item.id or "").strip()
                    for item in menu
                    if str(item.id or "").strip()
                ]
                if menu_ids:
                    picked, reason, share, chat = await self._choose_food_by_llm(
                        target_type=target_type,
                        candidate_ids=menu_ids,
                        hunger=hunger,
                        thirst=thirst,
                    )
                    if picked:
                        self._last_auto_eat_reason = reason
                        logger.info(f"从菜单选了 {target_type}: {picked}，理由: {reason}")
                        return picked, reason, share, chat
        except ImportError:
            logger.warning("food 模块不可用，跳过自动进食")
        except Exception as e:
            logger.warning(f"选择食物失败: {e}")

        return "", "", False, False

    async def _choose_food_by_llm(
        self,
        *,
        target_type: str,
        candidate_ids: List[str],
        hunger: float,
        thirst: float,
    ) -> tuple:
        """使用 LLM 选择食物，返回 (food_id, reason, share_with_ling, chat_while_eating)。
        失败时 fallback 到随机，share/chat 默认 False。"""
        deduped = list(dict.fromkeys(
            str(fid or "").strip()
            for fid in candidate_ids
            if str(fid or "").strip()
        ))
        if not deduped:
            return "", "", False, False
        # 避免连续吃同一种
        if (
            len(deduped) > 1
            and self._last_auto_eat_food_id
            and self._last_auto_eat_food_id in deduped
        ):
            deduped = [fid for fid in deduped if fid != self._last_auto_eat_food_id]
        if not deduped:
            return "", "", False, False

        try:
            from core.food.data import get_food
            from core.services.scheduler.task.task_scheduler import get_global_scheduler

            items = []
            for fid in deduped:
                food = get_food(fid)
                if not food:
                    continue
                items.append({
                    "food_id": fid,
                    "name": str(food.name or ""),
                    "type": str(food.type or ""),
                    "nutrition": {
                        "hunger": float(food.nutrition.hunger),
                        "thirst": float(food.nutrition.thirst),
                        "energy": float(food.nutrition.energy),
                        "health": float(food.nutrition.health),
                    },
                })
            if not items:
                fallback = random.choice(deduped)
                return fallback, "随机选的", False, False

            # ---- 收集上下文 ----
            mood_score = float(self.life_stats.get("mood_score") or 70.0)
            activity = str(self.life_stats.get("activity") or "idle")
            if mood_score >= 80:
                mood_desc = "开心"
            elif mood_score >= 60:
                mood_desc = "平静"
            elif mood_score >= 40:
                mood_desc = "低落"
            else:
                mood_desc = "郁闷"

            digestion_queue = list(self.life_stats.get("digestion_queue") or [])
            digestion_desc = f"{len(digestion_queue)}件" if digestion_queue else "无"

            last_meal = self.life_stats.get("_last_meal")
            meal_history = ""
            if isinstance(last_meal, dict) and last_meal.get("food_name"):
                meal_history = f"上一餐: {last_meal['food_name']}\n"

            ling_state = self.actor_manager.get_actor_life_state("ling")
            ling_h = float(ling_state.get("hunger") or 50.0)
            ling_t = float(ling_state.get("thirst") or 50.0)
            ling_m = float(ling_state.get("mood_score") or 60.0)
            ling_context = (
                f"同伴Ling: hunger={ling_h:.0f}, thirst={ling_t:.0f}, "
                f"mood={ling_m:.0f}/100\n"
            )

            # ---- 构建 prompt ----
            from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
                AUTO_EAT_DECISION_PROMPT,
            )
            candidates_text = (
                f"上一餐food_id:{self._last_auto_eat_food_id or 'none'}\n"
                f"候选:{json.dumps(items, ensure_ascii=False)}"
            )
            prompt = AUTO_EAT_DECISION_PROMPT.format(
                target_type=target_type,
                hunger=hunger,
                thirst=thirst,
                mood_score=mood_score,
                mood_desc=mood_desc,
                activity=activity,
                digestion_desc=digestion_desc,
                meal_history=meal_history,
                ling_context=ling_context,
                candidates_text=candidates_text,
            )

            scheduler = get_global_scheduler()
            model_path = "cloud:siliconflow:deepseek-ai/DeepSeek-V3.2"
            try:
                from config.model_config import get_auto_eat_model
                preferred = get_auto_eat_model()
                if preferred:
                    model_path = preferred
            except ImportError:
                pass

            raw_out = ""
            async for chunk in scheduler.submit_llm_task(
                prompt,
                max_tokens=512,
                temperature=0.6,
                model_path=model_path,
            ):
                if isinstance(chunk, str):
                    raw_out += chunk
                elif isinstance(chunk, dict) and chunk.get("content"):
                    raw_out += str(chunk.get("content") or "")

            if is_debug_enabled("auto_eat"):
                logger.info(f"LLM原始返回: {raw_out!r}")

            # raw_out 为空说明 LLM 未返回有效 content，直接走 fallback
            if not raw_out.strip():
                logger.warning(
                    f"LLM选食: 模型返回空内容, fallback随机。"
                    f"model={model_path}, target={target_type}"
                )
                fallback = random.choice(deduped)
                return fallback, "随机选的", False, False

            obj = extract_json_object(raw_out)

            if is_debug_enabled("auto_eat"):
                logger.info(f"extract_json_object结果: type={type(obj).__name__}, value={obj!r}")

            picked = str((obj or {}).get("food_id") or "").strip()
            reason = str((obj or {}).get("reason") or "").strip()
            share_with_ling = bool((obj or {}).get("share_with_ling", False))
            chat_while_eating = bool((obj or {}).get("chat_while_eating", False))
            if picked and picked in deduped:
                return picked, reason or "没给理由", share_with_ling, chat_while_eating

            # JSON 解析失败或 food_id 无效，记录详细日志便于排查
            logger.warning(
                f"LLM选食: food_id无效或JSON解析失败, fallback随机。"
                f"picked={picked!r}, raw_out={raw_out[:200]!r}"
            )
        except Exception as e:
            logger.warning(f"LLM选食失败: [{type(e).__name__}] {e}\n{traceback.format_exc()}")

        # fallback：随机选择
        fallback = random.choice(deduped)
        return fallback, "随机选的", False, False

    async def _share_food_with_ling(self, food_id: str, meal_meta: Dict[str, Any]):
        """和Ling分享食物"""
        try:
            from core.food.data import get_food

            food = get_food(food_id)
            hunger_amount = float(food.nutrition.hunger) if food else 10.0
            self.actor_manager.share_food_between_actors(
                "aveline", "ling", hunger_amount=hunger_amount
            )
            if meal_meta.get("is_late_snack"):
                self.life_stats["activity"] = "late_snack"
                apply_late_snack_penalty("aveline")
                apply_late_snack_penalty("ling")
            logger.info(f"Aveline 和Ling一起吃了 {food.name if food else food_id}")
        except Exception as e:
            logger.warning(f"分享食物失败: {e}")

    async def _feed_ling(self, food_id: str, food_type: str, meal_meta: Dict[str, Any]):
        """单独喂食Ling（直接应用效果，无需购买）"""
        try:
            from core.food.data import get_food

            food = get_food(food_id)
            if not food:
                return

            # 应用食物效果到Ling的状态
            hunger_amount = float(food.nutrition.hunger) if food else 30.0
            thirst_amount = float(food.nutrition.thirst) if food else 0.0
            mood_boost = 5.0
            
            ling_state = self.actor_manager._get_actor_state_mut("ling")
            
            # 恢复饱腹
            ling_state["hunger"] = min(100.0, float(ling_state.get("hunger", 0.0) or 0.0) + hunger_amount)
            
            # 恢复口渴（饮料或有口渴恢复效果）
            if food_type == "drink" or thirst_amount > 0:
                ling_state["thirst"] = min(100.0, float(ling_state.get("thirst", 0.0) or 0.0) + (thirst_amount or 30.0))
            
            # 恢复心情
            ling_state["mood_score"] = min(100.0, float(ling_state.get("mood_score", 0.0) or 0.0) + mood_boost)
            
            # 记录Ling的进食信息，供对话上下文注入
            ling_state["_last_meal"] = {
                "food_name": food.name,
                "food_id": food_id,
                "food_type": food_type,
                "eaten_at_ts": time.time(),
                "meal_window": str(meal_meta.get("meal_window") or "off_hours"),
                "is_late_snack": bool(meal_meta.get("is_late_snack")),
                "reason": self._last_auto_eat_reason or "",
            }
            record_food_event("ling", dict(ling_state["_last_meal"]))
            if meal_meta.get("is_late_snack"):
                ling_state["activity"] = "late_snack"
                apply_late_snack_penalty("ling")
            
            logger.info(f"Ling吃了 {food.name}，恢复 hunger={hunger_amount}, thirst={thirst_amount or 30.0}")
        except Exception as e:
            logger.warning(f"喂食Ling失败: {e}")

    async def _eat_food(self, food_id: str, meal_meta: Dict[str, Any]):
        """吃食物"""
        try:
            from core.food.manager import get_food_manager
            from core.food.data import get_food

            food = get_food(food_id)
            food_name = food.name if food else food_id

            manager = get_food_manager()
            result = await manager.eat(
                food_id,
                from_inventory=True,
                eater="self",
            )
            if result.get("success"):
                hunger_after = float(self.life_stats.get("hunger", 0.0) or 0.0)
                logger.info(
                    f"Aveline 吃了 {food_name}（{self._last_auto_eat_reason}）"
                    f"，hunger 恢复至 {hunger_after:.1f}"
                )
                # 存入 life_stats 供对话 prompt 引用
                self.life_stats["_last_meal"] = {
                    "food_id": food_id,
                    "food_name": food_name,
                    "food_type": food.type if food else str(meal_meta.get("target_type") or "snack"),
                    "eaten_at_ts": time.time(),
                    "meal_window": str(meal_meta.get("meal_window") or "off_hours"),
                    "is_late_snack": bool(meal_meta.get("is_late_snack")),
                    "reason": self._last_auto_eat_reason,
                }
                record_food_event("aveline", dict(self.life_stats["_last_meal"]))
                if meal_meta.get("is_late_snack"):
                    self.life_stats["activity"] = "late_snack"
                    apply_late_snack_penalty("aveline")
            else:
                logger.warning(f"进食未成功: {result.get('message', '未知原因')}")
        except Exception as e:
            logger.warning(f"进食失败: {e}")
