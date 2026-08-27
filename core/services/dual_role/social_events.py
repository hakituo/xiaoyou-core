import asyncio
import json
import math
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, Optional, Tuple

from core.utils.data_paths import get_dual_role_data_dir


def normalize_user_text(user_input: Any) -> str:
    """将不同形态的用户输入规范为纯文本。"""
    if isinstance(user_input, dict):
        for key in ("content", "text", "message"):
            value = user_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return str(user_input).strip()
    if isinstance(user_input, str):
        text = user_input.strip()
        if text.startswith("{") and "content" in text:
            match = re.search(r"['\"]content['\"]\s*:\s*['\"](.+?)['\"]", text)
            if match:
                return match.group(1).strip()
        return text
    return str(user_input or "").strip()


def cfg_float(settings: Any, key: str, default: float) -> float:
    """安全读取浮点配置。"""
    if settings is None:
        return float(default)
    try:
        return float(getattr(settings, key, default))
    except Exception:
        return float(default)


class SocialEventEngine:
    def __init__(self, project_root: str, settings: Any, logger: Any):
        # project_root 参数保留以兼容旧调用方，但实际路径改用规范函数 get_dual_role_data_dir()
        # 避免手搓 ../.. 层级导致路径错位（历史 bug：core/services/dual_role/ 是 3 级深，
        # 原代码只上溯 2 级到 core/，导致数据被错误写入 core/companion_data/）
        self._project_root = project_root
        self._settings = settings
        self._logger = logger
        self._social_events: Dict[str, list] = {}
        self._social_events_loaded = set()
        self._bert_runtime_available: Optional[bool] = None
        self._social_events_dir = str(get_dual_role_data_dir() / "social_events")

    def _clip_event_text(self, text: str, limit: int = 220) -> str:
        raw = str(text or "").strip()
        if len(raw) <= limit:
            return raw
        return raw[:limit] + "..."

    def _normalize_legacy_detail(self, detail: str) -> str:
        raw = str(detail or "").strip()
        if not raw:
            return ""
        m = re.search(r"\{['\"]content['\"]\s*:\s*['\"](.+?)['\"]\}", raw)
        if m:
            raw = raw.replace(m.group(0), m.group(1).strip())
        raw = raw.replace("只是同事", "是朋友").replace("后台同事", "后台朋友")
        return raw

    def _event_file_path(self, conversation_id: str) -> str:
        cid = str(conversation_id or "").strip() or "default"
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", cid)[:160]
        return os.path.join(self._social_events_dir, f"{safe}.json")

    def _ensure_events_loaded(self, conversation_id: str) -> None:
        cid = str(conversation_id or "").strip() or "default"
        if cid in self._social_events_loaded:
            return
        self._social_events_loaded.add(cid)
        path = self._event_file_path(cid)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            events = payload.get("events") if isinstance(payload, dict) else []
            if isinstance(events, list):
                normalized = []
                for x in events:
                    if not isinstance(x, dict):
                        continue
                    cloned = dict(x)
                    cloned["detail"] = self._normalize_legacy_detail(cloned.get("detail"))
                    normalized.append(cloned)
                self._social_events[cid] = normalized[-24:]
        except Exception as e:
            self._logger.warning(f"加载社交事件失败 {cid}: {e}")

    def _persist_events(self, conversation_id: str) -> None:
        cid = str(conversation_id or "").strip() or "default"
        events = list(self._social_events.get(cid) or [])
        try:
            os.makedirs(self._social_events_dir, exist_ok=True)
            path = self._event_file_path(cid)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"conversation_id": cid, "events": events[-24:]},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            self._logger.warning(f"持久化社交事件失败 {cid}: {e}")

    def _event_weight(self, event_type: str) -> float:
        et = str(event_type or "").strip().lower()
        if et in {"meal", "meal_status"}:
            return cfg_float(self._settings, "weight_meal", 1.1)
        if et in {"wake_up", "nap_wake", "awake_presence"}:
            return 0.7
        if et == "care":
            return cfg_float(self._settings, "weight_care", 1.4)
        if et == "switch":
            return cfg_float(self._settings, "weight_switch", 0.5)
        if et == "mention":
            return cfg_float(self._settings, "weight_mention", 0.4)
        return 0.2

    def _build_relationship_summary(self, conversation_id: str) -> Dict[str, Any]:
        cid = str(conversation_id or "").strip() or "default"
        self._ensure_events_loaded(cid)
        # 历史后台圈子事件由自动互聊产生，不能继续参与关系热度计算。
        events = [
            item
            for item in (self._social_events.get(cid) or [])
            if isinstance(item, dict)
            and str(item.get("type") or "").strip().lower() != "background_circle"
        ]
        if not events:
            return {
                "score": 0.0,
                "label": "轻微疏离",
                "summary": "近期互动较少，关系偏平稳。",
                "evidences": [],
            }
        now = time.time()
        half_life_hours = max(
            0.1, cfg_float(self._settings, "event_decay_half_life_hours", 24.0)
        )
        half_life_seconds = half_life_hours * 3600.0
        score = 0.0
        evidences = []
        for item in reversed(events[-24:]):
            ts = float(item.get("ts") or 0.0)
            detail = str(item.get("detail") or "").strip()
            evt_type = str(item.get("type") or "")
            age_seconds = max(0.0, now - ts)
            decay = math.exp(-math.log(2.0) * (age_seconds / half_life_seconds))
            score += self._event_weight(evt_type) * decay
            if detail and len(evidences) < 2:
                evidences.append(detail)
        score = round(float(score), 3)
        hot = cfg_float(self._settings, "summary_hot_threshold", 4.5)
        warm = cfg_float(self._settings, "summary_warm_threshold", 2.0)
        if score >= hot:
            label = "升温中"
            summary = f"你们近期互动密集，关系在升温。近况分={score:.2f}。"
        elif score >= warm:
            label = "稳定亲密"
            summary = f"你们保持稳定协作，关系较亲近。近况分={score:.2f}。"
        else:
            label = "轻微疏离"
            summary = f"你们近期互动偏少，关系略有疏离。近况分={score:.2f}。"
        return {
            "score": score,
            "label": label,
            "summary": summary,
            "evidences": evidences,
        }

    def _append_social_event(
        self,
        conversation_id: str,
        *,
        event_type: str,
        detail: str,
        role_runtime: Optional[Dict[str, str]] = None,
        full_content: str = "",
        source: str = "",
        learned_by: str = "",
        occurred_at: Optional[float] = None,
        certainty: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        cid = str(conversation_id or "").strip() or "default"
        self._ensure_events_loaded(cid)
        events = self._social_events.get(cid)
        if not isinstance(events, list):
            events = []
            self._social_events[cid] = events
        role_runtime = role_runtime or {}
        item = {
            "ts": float(occurred_at or time.time()),
            "type": str(event_type or "misc"),
            "detail": str(detail or "").strip(),
            "front": str(role_runtime.get("front_name") or ""),
            "back": str(role_runtime.get("back_name") or ""),
        }
        if source:
            item["source"] = str(source).strip()
        if learned_by:
            item["learned_by"] = str(learned_by).strip().lower()
        if certainty:
            item["certainty"] = str(certainty).strip().lower()
        if metadata:
            item["metadata"] = dict(metadata)
        if full_content:
            item["full_content"] = str(full_content).strip()
        if not item["detail"]:
            return
        if events:
            last = events[-1] if isinstance(events[-1], dict) else {}
            last_detail = str(last.get("detail") or "")
            last_type = str(last.get("type") or "")
            last_ts = float(last.get("ts") or 0.0)
            dedup_seconds = cfg_float(self._settings, "dedup_window_seconds", 30.0)
            if (
                last_detail == item["detail"]
                and last_type == item["type"]
                and (item["ts"] - last_ts) < dedup_seconds
            ):
                return
        events.append(item)
        if len(events) > 24:
            del events[:-24]
        self._persist_events(cid)

    def record_shared_life_event(
        self,
        *,
        event_type: str,
        detail: str,
        source: str,
        learned_by: str,
        occurred_at: Optional[float] = None,
        certainty: str = "reported",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录室友共享的生活事件，并保留事实来源与最先知情角色。"""
        role_names = {
            "aveline": "Aveline",
            "ling": "Ling",
        }
        observer = str(learned_by or "aveline").strip().lower() or "aveline"
        self._append_social_event(
            "default",
            event_type=event_type,
            detail=self._clip_event_text(detail),
            role_runtime={"front_name": role_names.get(observer, observer)},
            source=source,
            learned_by=observer,
            occurred_at=occurred_at,
            certainty=certainty,
            metadata=metadata,
        )

    async def record_user_life_event(self, text: str, *, learned_by: str) -> Optional[str]:
        """从聊天记录高置信生活近况；这些事件不作为正式健康作息。"""
        raw = normalize_user_text(text)
        if not raw:
            return None

        event_type = ""
        detail = ""
        if re.search(r"(午睡|午觉).{0,8}(醒|起来|睡醒)", raw):
            event_type = "nap_wake"
            detail = "主人说自己午睡醒了"
        elif re.search(r"^(我)?(刚)?(醒了|醒啦|起来了|起床了|刚起来)[啊呀嘛吧。！!]*$", raw):
            event_type = "awake_presence"
            detail = "主人说自己现在已经清醒；这不等于主睡眠的正式起床时间"
        elif re.search(r"(我|刚刚|刚才).{0,5}(还没|没|没有)(吃饭|吃东西|吃早餐|吃午饭|吃晚饭)", raw):
            event_type = "meal_status"
            detail = "主人说自己还没有吃饭"
        elif re.search(r"(我|刚刚|刚才).{0,8}(吃了|吃过|吃完|吃饭了|吃东西了)", raw):
            event_type = "meal"
            detail = f"主人说自己吃过东西了：{self._clip_event_text(raw, 80)}"

        if not event_type:
            return None
        self.record_shared_life_event(
            event_type=event_type,
            detail=detail,
            source="user_message",
            learned_by=learned_by,
            certainty="reported",
        )
        return event_type

    def record_health_events(
        self,
        events: Iterable[Dict[str, Any]],
        *,
        learned_by: str = "aveline",
        wake_sleep_kind: str = "",
    ) -> int:
        """把 Samsung Health 的可分享生活事件放入室友共享事件池。"""
        recorded = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "")
            if event_type == "meal":
                foods = [str(x) for x in (event.get("foods") or []) if str(x).strip()]
                detail = "Samsung Health 记录主人吃过东西"
                if foods:
                    detail += "：" + "、".join(foods[:4])
                elif event.get("delta_kcal"):
                    detail += f"（新增约 {event['delta_kcal']} 千卡）"
                self.record_shared_life_event(
                    event_type="meal",
                    detail=detail,
                    source="samsung_health",
                    learned_by=learned_by,
                    certainty="measured",
                    metadata=event,
                )
                recorded += 1
            elif event_type == "wake_up":
                kind = wake_sleep_kind or "main_sleep"
                event_name = "nap_wake" if kind == "nap" else "wake_up"
                label = "午睡/小憩结束" if kind == "nap" else "主睡眠结束"
                self.record_shared_life_event(
                    event_type=event_name,
                    detail=f"Samsung Health 记录主人{label}：{event.get('sleep_end') or '时间未知'}",
                    source="samsung_health",
                    learned_by=learned_by,
                    certainty="measured",
                    metadata=event,
                )
                recorded += 1
        return recorded

    def _classify_event_by_rule(self, text: str) -> Optional[Tuple[str, str]]:
        if not text:
            return None
        if re.search(
            r"(一起吃|请你吃|请她吃|请他吃|请.*(奶茶|咖啡|外卖|火锅|烤肉|烧烤|宵夜|午饭|晚饭)|"
            r"喝了.*(奶茶|咖啡)|点了.*(奶茶|咖啡|外卖)|投喂|喂了|吃了.*(饭|面|火锅|烤肉|烧烤|宵夜))",
            text,
        ):
            return ("meal", f"饮食互动：{self._clip_event_text(text)}")
        if re.search(r"(关心|照顾|担心|陪你|陪她|陪他|哄你|安慰)", text):
            return ("care", f"关怀互动：{self._clip_event_text(text)}")
        if re.search(r"(前台|主聊|切换|让.*到前台)", text):
            return ("switch", f"前台切换：{self._clip_event_text(text)}")
        if re.search(r"(你们|Ling|小澪|Aveline|七濑|澪)", text):
            return ("mention", f"关系提及：{self._clip_event_text(text)}")
        return None

    def _format_semantic_tail(self, analysis: Dict[str, Any]) -> str:
        category = str((analysis or {}).get("category") or "uncategorized")
        topics = (
            (analysis or {}).get("topics")
            if isinstance((analysis or {}).get("topics"), list)
            else []
        )
        topics_text = ",".join([str(x).strip() for x in topics[:2] if str(x).strip()])
        weight = float((analysis or {}).get("weight_delta") or 0.0)
        return (
            f"｜语义:{category}" + (f"/{topics_text}" if topics_text else "") + f"｜权重:{weight:+.2f}"
        )

    async def _classify_event_with_backend_semantics(
        self, text: str, fallback: Optional[Tuple[str, str]]
    ) -> Optional[Tuple[str, str]]:
        if self._bert_runtime_available is False:
            return fallback
        try:
            from core.services.data_ops.bert_analyzer import get_bert_analyzer

            analyzer = get_bert_analyzer()
            loop = asyncio.get_running_loop()

            def _run_semantic_pack() -> Dict[str, Any]:
                return {
                    "intent": analyzer.analyze_intent(
                        text,
                        [
                            "RECORD_MEAL",
                            "RECORD_DRINK",
                            "RECORD_HEALTH",
                            "RECORD_MOOD",
                            "SWITCH_PERSONA",
                            "NONE",
                        ],
                    ),
                    "analysis": analyzer.analyze(text),
                }

            result = await loop.run_in_executor(None, _run_semantic_pack)
            self._bert_runtime_available = True
            intent_result = (
                (result or {}).get("intent")
                if isinstance((result or {}).get("intent"), dict)
                else {}
            )
            analysis = (
                (result or {}).get("analysis")
                if isinstance((result or {}).get("analysis"), dict)
                else {}
            )
            intent = str(intent_result.get("intent") or "NONE").upper()
            conf = float(intent_result.get("confidence") or 0.0)
            category = str(analysis.get("category") or "uncategorized").lower()
            topics = [
                str(x).strip() for x in (analysis.get("topics") or []) if str(x).strip()
            ]
            semantic_tail = self._format_semantic_tail(analysis)
            meal_hint = (
                re.search(
                    r"(吃|喝|奶茶|咖啡|外卖|火锅|烤肉|烧烤|宵夜|午饭|晚饭|早餐)", text
                )
                is not None
            )
            care_hint = (
                re.search(r"(关心|照顾|担心|安慰|哄|不舒服|生病|难受)", text) is not None
            )
            threshold_meal = cfg_float(self._settings, "bert_intent_threshold_meal", 0.62)
            threshold_switch = cfg_float(
                self._settings, "bert_intent_threshold_switch", 0.72
            )
            threshold_care = cfg_float(self._settings, "bert_intent_threshold_care", 0.72)

            if intent in ("RECORD_MEAL", "RECORD_DRINK") and conf >= threshold_meal:
                return ("meal", f"饮食互动：{self._clip_event_text(text)}{semantic_tail}")
            if intent == "SWITCH_PERSONA" and conf >= threshold_switch:
                return ("switch", f"前台切换：{self._clip_event_text(text)}{semantic_tail}")
            if intent in ("RECORD_HEALTH", "RECORD_MOOD") and conf >= threshold_care:
                return ("care", f"关怀互动：{self._clip_event_text(text)}{semantic_tail}")
            if meal_hint and (
                category == "daily" or any(t in ("日常", "健康") for t in topics)
            ):
                return ("meal", f"饮食互动：{self._clip_event_text(text)}{semantic_tail}")
            if care_hint and (
                category in ("health", "emotion")
                or any(t in ("健康", "情绪", "关系") for t in topics)
            ):
                return ("care", f"关怀互动：{self._clip_event_text(text)}{semantic_tail}")
            if category in ("emotion", "health") and float(
                analysis.get("weight_delta") or 0.0
            ) >= 0.35:
                return ("care", f"关怀互动：{self._clip_event_text(text)}{semantic_tail}")
            return fallback
        except Exception:
            self._bert_runtime_available = False
            return fallback

    def build_recent_events_context(
        self,
        conversation_id: str,
        max_items: int = 4,
        viewer_role_id: str = "",
    ) -> str:
        cid = str(conversation_id or "").strip() or "default"
        self._ensure_events_loaded(cid)
        events = list(self._social_events.get(cid) or [])
        if not events:
            return ""
        lines = []
        rel = self._build_relationship_summary(cid)
        rel_summary = str(rel.get("summary") or "").strip()
        if rel_summary:
            lines.append(f"- 关系摘要：{rel_summary}")
        for item in events[-max_items:]:
            if not isinstance(item, dict):
                continue
            evt_type = str(item.get("type") or "").strip().lower()
            if evt_type == "background_circle":
                continue
            detail = str(item.get("detail") or "").strip()
            if detail:
                source = str(item.get("source") or "").strip()
                learned_by = str(item.get("learned_by") or "").strip().lower()
                source_label = {
                    "samsung_health": "Samsung Health 实测",
                    "user_message": "用户自述",
                    "user_input": "用户消息",
                }.get(source, source or "来源未标注")
                if learned_by and viewer_role_id and learned_by != viewer_role_id:
                    learned_label = "Aveline 转告" if learned_by == "aveline" else "Ling转告"
                elif learned_by:
                    learned_label = "最先告诉 Aveline" if learned_by == "aveline" else "最先告诉Ling"
                else:
                    learned_label = "共同知道"
                lines.append(f"- {detail}（{source_label}；{learned_label}）")
        if not lines:
            return ""
        return "最近你们的互动事件：\n" + "\n".join(lines)


_SOCIAL_EVENT_ENGINE_INSTANCE = None
# P0-23: 使用 threading.Lock + double-check 保护 get_social_event_engine 单例，
# 防止多线程并发导致重复创建 SocialEventEngine 实例（事件状态不一致、定时器重复注册）
_SOCIAL_EVENT_ENGINE_LOCK = threading.Lock()


def get_social_event_engine() -> "SocialEventEngine":
    global _SOCIAL_EVENT_ENGINE_INSTANCE
    if _SOCIAL_EVENT_ENGINE_INSTANCE is None:
        with _SOCIAL_EVENT_ENGINE_LOCK:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _SOCIAL_EVENT_ENGINE_INSTANCE is not None:
                return _SOCIAL_EVENT_ENGINE_INSTANCE
            from core.utils.logger import get_logger as _get_logger
            _logger = _get_logger("SocialEventEngine")
            # project_root 不再使用：路径解析交给 SocialEventEngine 内部的 get_dual_role_data_dir()
            _project_root = ""
            _settings = None
            try:
                from config.integrated_config import get_settings
                _settings = get_settings().dual_role
            except Exception:
                pass
            _SOCIAL_EVENT_ENGINE_INSTANCE = SocialEventEngine(
                project_root=_project_root,
                settings=_settings,
                logger=_logger,
            )
    return _SOCIAL_EVENT_ENGINE_INSTANCE
