import asyncio
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.services.journal.models import DailySummary, JournalEntry
from core.services.journal.storage import JournalStorage
from core.services.dual_role.constants import (
    DEFAULT_PERSONAS,
    LING_PERSONAS,
    MIN_FRAGMENT_LEN,
    LOW_SIGNAL_FRAGMENTS,
    get_persona_scope,
    infer_persona_name as _infer_persona_name_impl,
    normalize_fragment as _normalize_fragment_impl,
)
from core.utils.data_paths import get_aveline_persona_data_dir, get_ling_persona_data_dir
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_iso

logger = get_logger("PersonaJournalExport")
_LLM_DIARY_ENABLED = False
_LLM_MAX_FRAGMENTS = 15

_BERT_ANALYZER_INSTANCE = None


def _safe_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "default"
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip("._ ") or "default"


def _normalize_date(date: Optional[Any]) -> datetime:
    if isinstance(date, datetime):
        return date
    raw = str(date or "").strip()
    if raw:
        try:
            return datetime.strptime(raw.split(" ")[0], "%Y-%m-%d")
        except Exception:
            pass
    return get_current_time()


def _entry_to_dict(entry: JournalEntry) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "timestamp": entry.timestamp,
        "time_str": entry.time_str,
        "type": entry.type,
        "content": entry.content,
        "mood": entry.mood,
        "thought": entry.thought,
        "tags": list(entry.tags or []),
        "source": entry.source,
    }


def _infer_persona_name(entry: JournalEntry) -> Optional[str]:
    content = str(entry.content or "")
    tags = [str(tag).strip() for tag in (entry.tags or []) if str(tag).strip()]
    source = str(entry.source or "").strip().lower()
    return _infer_persona_name_impl(content, tags, source)


def _is_legacy_background_circle_entry(entry: JournalEntry) -> bool:
    """过滤历史圈子条目；新版本不再读取或生成这类数据。"""
    thought = str(entry.thought or "").strip()
    tags = {str(tag).strip() for tag in (entry.tags or []) if str(tag).strip()}
    return thought == "dual_role_background_circle" or "后台圈子" in tags


def _is_diary_like_entry(entry: JournalEntry) -> bool:
    if str(entry.type or "").strip() == "daily_summary":
        return False
    # 排除纯系统内部条目（非 persona 产生的）
    source = str(entry.source or "").strip().lower()
    if source == "system" and str(entry.thought or "").strip().lower() == "auto_generated_daily_summary":
        return False
    if _is_legacy_background_circle_entry(entry):
        return False
    return True


def _entry_mentions_persona(entry: JournalEntry, persona_name: str) -> bool:
    content = str(entry.content or "")
    return f"{persona_name}：" in content


def _get_persona_dir_name(persona_name: str) -> str:
    scope = get_persona_scope(persona_name)
    return "ling" if scope == "ling" else "aveline"


def _split_fragment_lines(persona_name: str, text: str) -> List[str]:
    lines = [str(row).strip() for row in str(text or "").splitlines()]
    cleaned: List[str] = []
    for line in lines:
        if not line:
            continue
        candidate = line
        if "：" in candidate:
            speaker, speech = candidate.split("：", 1)
            speaker = speaker.strip()
            if speaker in DEFAULT_PERSONAS and speaker != persona_name:
                continue
            candidate = speech.strip() if speaker == persona_name else candidate
        candidate = _normalize_fragment_impl(candidate)
        if len(candidate) < MIN_FRAGMENT_LEN:
            continue
        if candidate.endswith(("因为今", "因为", "我才", "我就")):
            continue
        cleaned.append(candidate)
    return cleaned


def _collect_fragments(
    persona_name: str, diary_entries: List[Dict[str, Any]]
) -> List[str]:
    raw: List[str] = []
    for entry in diary_entries:
        raw.extend(_split_fragment_lines(persona_name, str(entry.get("content") or "")))
    unique: List[str] = []
    low_signal: List[str] = []
    seen = set()
    for item in raw:
        norm = item.lower()
        if norm in seen:
            continue
        seen.add(norm)
        if item in LOW_SIGNAL_FRAGMENTS:
            low_signal.append(item)
            continue
        unique.append(item)
    return unique or low_signal


def _build_study_sentence(study_summary: Dict[str, Any]) -> str:
    if not isinstance(study_summary, dict) or not study_summary:
        return ""
    sentences: List[str] = []
    session = study_summary.get("session") if isinstance(study_summary.get("session"), dict) else {}
    vocab = study_summary.get("vocab") if isinstance(study_summary.get("vocab"), dict) else {}
    duration = session.get("study_duration_minutes")
    sessions = session.get("study_session_count")
    if duration or sessions:
        parts = []
        if duration:
            parts.append(f"学习时长约{duration}分钟")
        if sessions:
            parts.append(f"完成{sessions}次学习记录")
        sentences.append("，".join(parts))
    new_words = vocab.get("new_words")
    reviewed = vocab.get("reviewed_words")
    if new_words or reviewed:
        parts = []
        if new_words:
            parts.append(f"新增词汇{new_words}个")
        if reviewed:
            parts.append(f"复习词汇{reviewed}个")
        sentences.append("，".join(parts))
    return "；".join(sentences)


def _get_bert_analyzer():
    global _BERT_ANALYZER_INSTANCE
    if _BERT_ANALYZER_INSTANCE is not None:
        return _BERT_ANALYZER_INSTANCE
    try:
        from core.services.data_ops.bert_analyzer import BertAnalyzer
        _BERT_ANALYZER_INSTANCE = BertAnalyzer()
        return _BERT_ANALYZER_INSTANCE
    except Exception as e:
        logger.warning(f"获取 BertAnalyzer 失败: {e}")
        return None


def _analyze_fragment_sync(text: str) -> Dict[str, Any]:
    analyzer = _get_bert_analyzer()
    if not analyzer:
        return {"category": "uncategorized", "topics": [], "importance": 0.0, "state_event": "NONE", "discourse": "GENERIC_CHAT"}
    try:
        result = analyzer.analyze(text)
        return {
            "category": result.get("category", "uncategorized"),
            "topics": result.get("topics", []),
            "importance": result.get("weight_delta", 0.0),
            "state_event": result.get("state_event", "NONE"),
            "discourse": result.get("discourse", {}).get("discourse_label", "GENERIC_CHAT"),
        }
    except Exception as e:
        logger.debug(f"BERT 分析片段失败: {e}")
        return {"category": "uncategorized", "topics": [], "importance": 0.0, "state_event": "NONE", "discourse": "GENERIC_CHAT"}


async def _analyze_fragments_batch(fragments: List[str], max_count: int = 12) -> List[Dict[str, Any]]:
    if not fragments:
        return []
    targets = fragments[:max_count]

    def _analyze_all() -> List[Dict[str, Any]]:
        results = []
        for frag in targets:
            analysis = _analyze_fragment_sync(frag)
            analysis["text"] = frag
            results.append(analysis)
        results.sort(key=lambda x: -x.get("importance", 0.0))
        return results

    return await asyncio.to_thread(_analyze_all)


def _build_daily_portrait_text(daily_record: Dict[str, Any]) -> str:
    if not isinstance(daily_record, dict) or not daily_record:
        return ""
    parts: List[str] = []
    # 兼容新旧格式
    sc = daily_record.get("sleep_cycle") or daily_record.get("schedule") or {}
    if sc.get("wakeup"):
        parts.append(f"起床于{sc['wakeup']}")
    if sc.get("sleep"):
        parts.append(f"入睡于{sc['sleep']}")
    meals = daily_record.get("meals", [])
    if meals:
        meal_types = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "零食", "drink": "饮水"}
        for m in meals:
            m_type = str(m.get("type", "meal")).lower()
            m_content = str(m.get("content", ""))
            type_name = meal_types.get(m_type, m_type)
            if m_content:
                parts.append(f"{type_name}吃了{m_content}")
    study_sessions = daily_record.get("study", {}).get("sessions", [])
    if study_sessions:
        topics = list({str(s.get("topic", "")).strip() for s in study_sessions if str(s.get("topic", "")).strip()})
        if topics:
            parts.append(f"学习了{', '.join(topics[:3])}")
    activities = daily_record.get("activities", [])
    if activities:
        activity_contents = [str(a.get("content", "")).strip() for a in activities if str(a.get("content", "")).strip()]
        if activity_contents:
            parts.append(f"活动：{', '.join(activity_contents[:3])}")
    health = daily_record.get("health", [])
    if health:
        symptoms = [str(h.get("symptom", "")).strip() for h in health if str(h.get("symptom", "")).strip()]
        if symptoms:
            parts.append(f"健康状态：{', '.join(symptoms)}")
    mood = daily_record.get("mood")
    if mood:
        if isinstance(mood, dict):
            mood_name = mood.get("mood", "")
            if mood_name:
                parts.append(f"心情：{mood_name}")
        else:
            parts.append(f"心情：{mood}")
    return "；".join(parts)


def _build_structured_events(
    daily_record: Dict[str, Any],
    analyzed_fragments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    # 兼容新旧格式
    sc = daily_record.get("sleep_cycle") or daily_record.get("schedule") or {}
    if sc.get("wakeup"):
        events.append({"type": "wakeup", "time": sc["wakeup"], "content": "起床", "importance": 0.3})
    if sc.get("sleep"):
        events.append({"type": "sleep", "time": sc["sleep"], "content": "入睡", "importance": 0.3})
    meals = daily_record.get("meals", [])
    meal_types = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "零食", "drink": "饮水"}
    for m in meals:
        m_type = str(m.get("type", "meal")).lower()
        m_content = str(m.get("content", ""))
        m_time = str(m.get("time", ""))
        type_name = meal_types.get(m_type, m_type)
        events.append({
            "type": "meal",
            "time": m_time,
            "content": f"{type_name}吃了{m_content}" if m_content else f"吃了{type_name}",
            "importance": 0.2,
        })
    study_sessions = daily_record.get("study", {}).get("sessions", [])
    for s in study_sessions:
        topic = str(s.get("topic", "")).strip()
        content = str(s.get("content", "")).strip()
        s_time = str(s.get("time", ""))
        if topic or content:
            events.append({
                "type": "study",
                "time": s_time,
                "content": f"学习{topic}" if topic else content,
                "importance": 0.4,
            })
    for frag in analyzed_fragments:
        state_event = frag.get("state_event", "NONE")
        if state_event != "NONE":
            events.append({
                "type": state_event.lower(),
                "time": "",
                "content": frag.get("text", ""),
                "importance": max(0.3, frag.get("importance", 0.0) + 0.3),
                "category": frag.get("category", "uncategorized"),
            })
        elif frag.get("importance", 0.0) > 0.2:
            events.append({
                "type": "chat",
                "time": "",
                "content": frag.get("text", ""),
                "importance": frag.get("importance", 0.0),
                "category": frag.get("category", "uncategorized"),
                "topics": frag.get("topics", []),
            })
    events.sort(key=lambda x: (x.get("time", "") or "", -x.get("importance", 0.0)))
    return events


async def _generate_diary_with_llm(
    *,
    dt: datetime,
    persona_name: str,
    portrait_text: str,
    events: List[Dict[str, Any]],
    fragments: List[str],
    highlights: List[str],
    study_text: str,
) -> Optional[str]:
    if not _LLM_DIARY_ENABLED:
        return None
    try:
        from core.llm import get_llm_module
        llm = get_llm_module()
        if not llm:
            logger.warning("LLM 模块不可用")
            return None
        events_text = "；".join([e.get("content", "") for e in events[:6] if e.get("content")])
        fragments_text = "\n".join([f"- {f}" for f in fragments[:_LLM_MAX_FRAGMENTS]])
        highlights_text = "、".join(highlights[:3]) if highlights else "无"
        from core.agents.chat_agent_components.persona_system.prompt.components import JOURNAL_LLM_DIARY_PROMPT_TEMPLATE
        prompt = JOURNAL_LLM_DIARY_PROMPT_TEMPLATE.format(
            persona_name=persona_name,
            date=dt.strftime("%Y-%m-%d"),
            portrait_text=portrait_text or "无记录",
            events_text=events_text or "无特殊事件",
            fragments_text=fragments_text or "无",
            highlights_text=highlights_text,
            study_text=study_text or "无学习记录",
        )
        from config.integrated_config import get_settings
        settings = get_settings()
        try:
            from config.model_config import get_journal_model
            journal_model_hint = get_journal_model()
            if not journal_model_hint:
                journal_model_hint = str(getattr(settings.model, "journal_model_hint", "")) or ""
        except Exception:
            journal_model_hint = ""
        messages = [{"role": "user", "content": prompt}]
        response = await llm.chat(
            messages, max_tokens=600, temperature=0.7, model_hint=journal_model_hint
        )
        if isinstance(response, dict):
            if response.get("status") == "success":
                response = str(response.get("response") or "")
            else:
                response = None
        if response and isinstance(response, str):
            return response.strip()
        return None
    except Exception as e:
        logger.warning(f"LLM 生成日记失败: {e}")
        return None


async def _build_final_diary(
    *,
    dt: datetime,
    persona_name: str,
    diary_entries: List[Dict[str, Any]],
    daily_summary: Optional[DailySummary],
    study_summary: Dict[str, Any],
    daily_record: Optional[Dict[str, Any]] = None,
    use_bert_analysis: bool = True,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    fragments = _collect_fragments(persona_name, diary_entries)
    if not fragments:
        return None, []
    summary_text = str(daily_summary.summary).strip() if daily_summary and daily_summary.summary else ""
    daily_record = daily_record or {}
    portrait_text = _build_daily_portrait_text(daily_record)

    analyzed_fragments: List[Dict[str, Any]] = []
    if use_bert_analysis and fragments:
        analyzed_fragments = await _analyze_fragments_batch(fragments, max_count=12)

    structured_events = _build_structured_events(daily_record, analyzed_fragments)

    if not summary_text and not portrait_text and not structured_events:
        return None, []

    used_fragments = fragments[:8]
    study_sentence = _build_study_sentence(study_summary)

    sections: List[str] = []
    sections.append(f"{dt.strftime('%Y-%m-%d')}，{persona_name}。")
    if summary_text:
        sections.append(f"今天整体回顾：{summary_text.rstrip('。')}。")
    if portrait_text:
        sections.append(f"今日生活画像：{portrait_text}。")
    if structured_events:
        event_contents = []
        seen_contents = set()
        for event in structured_events[:6]:
            content_item = event.get("content", "")
            if content_item and content_item not in seen_contents:
                seen_contents.add(content_item)
                event_type = event.get("type", "")
                if event_type in ("wakeup", "sleep", "meal", "study"):
                    event_contents.append(content_item)
                elif event.get("importance", 0) > 0.25:
                    event_contents.append(content_item)
        if event_contents:
            sections.append(f"今日事件：{'；'.join(event_contents)}。")
    if analyzed_fragments:
        important_frags = [f for f in analyzed_fragments if f.get("importance", 0) > 0.15][:4]
        if important_frags:
            frag_texts = [f.get("text", "") for f in important_frags if f.get("text")]
            if frag_texts:
                frag_str = "；".join(['"' + t + '"' for t in frag_texts[:4]])
                sections.append(f"重要片段：{frag_str}。")
    elif used_fragments:
        frag_str = "；".join(['"' + frag + '"' for frag in used_fragments[:4]])
        sections.append(f"今天记录下来的关键片段：{frag_str}。")
    if study_sentence:
        sections.append(f"学习方面：{study_sentence}。")
    sections.append("明天继续把节奏稳住，先把最重要的一件事做完。")

    content = "\n\n".join(section for section in sections if section).strip()
    generation_method = "merged_daily_summary_template"

    if not content:
        return None, used_fragments

    final_entry = {
        "id": f"final_{dt.strftime('%Y%m%d')}_{_safe_segment(persona_name)}",
        "type": "final_daily_diary",
        "title": f"{dt.strftime('%Y-%m-%d')} {persona_name}日记",
        "content": content,
        "generated_at": now_iso(),
        "structured_events": structured_events[:10],
        "generation_method": generation_method,
        "analysis_source": "bert_enhanced" if use_bert_analysis else "legacy",
    }
    return final_entry, used_fragments


class _ExportContext:
    """一次导出操作共享的数据上下文"""

    def __init__(self, dt: datetime, storage: JournalStorage):
        self.dt = dt
        self.date_key = dt.strftime("%Y-%m-%d")
        self._storage = storage
        self._entries: Optional[List[JournalEntry]] = None
        self._daily_summary: Optional[DailySummary] = None
        self._study_summary: Optional[Dict[str, Any]] = None
        self._daily_record: Optional[Dict[str, Any]] = None

    async def entries(self) -> List[JournalEntry]:
        if self._entries is None:
            self._entries = await self._storage.get_entries(self.dt)
        return self._entries

    async def daily_summary(self) -> Optional[DailySummary]:
        if self._daily_summary is None:
            self._daily_summary = await self._storage.get_daily_summary(self.dt)
        return self._daily_summary

    async def daily_summary_for_scope(self, scope: str) -> Optional[DailySummary]:
        """加载指定 scope 的 daily_summary（aveline/ling 各自独立）"""
        return await self._storage.get_daily_summary(self.dt, scope=scope)

    async def study_summary(self) -> Dict[str, Any]:
        if self._study_summary is None:
            self._study_summary = await asyncio.to_thread(_load_study_summary, self.dt)
        return self._study_summary or {}

    async def daily_record(self) -> Dict[str, Any]:
        if self._daily_record is None:
            self._daily_record = await asyncio.to_thread(_load_daily_record, self.date_key)
        return self._daily_record or {}


def _load_study_summary(dt: datetime) -> Dict[str, Any]:
    try:
        from core.services.study.service import get_study_service
        return get_study_service().get_study_daily_digest(dt.strftime("%Y-%m-%d")) or {}
    except Exception as e:
        logger.debug(f"加载学习总结失败: {e}")
        return {}


def _load_daily_record(date_key: str) -> Dict[str, Any]:
    try:
        from core.services.daily.manager import get_daily_manager
        return get_daily_manager().get_record(date_key) or {}
    except Exception as e:
        logger.debug(f"获取 DailyActivityManager 记录失败: {e}")
        return {}


class PersonaJournalExportService:
    def __init__(self) -> None:
        self._scope_roots = {
            "aveline": get_aveline_persona_data_dir(),
            "ling": get_ling_persona_data_dir(),
        }
        for path in self._scope_roots.values():
            path.mkdir(parents=True, exist_ok=True)
        self._migrated = False
        self._storage = JournalStorage()

    def _ensure_migration(self) -> None:
        if self._migrated:
            return
        self._migrated = True
        for scope, base_dir in self._scope_roots.items():
            canonical = "ling" if scope == "ling" else "aveline"
            candidates = ["Ling", canonical] if scope == "ling" else ["七濑 澪", canonical]
            canonical_dir = base_dir / canonical
            canonical_dir.mkdir(parents=True, exist_ok=True)
            for name in candidates:
                src = base_dir / name
                if src == canonical_dir or not src.exists():
                    continue
                if not src.is_dir():
                    continue
                for child in list(src.iterdir()):
                    target = canonical_dir / child.name
                    if target.exists():
                        continue
                    try:
                        child.replace(target)
                    except Exception:
                        continue
                try:
                    src.rmdir()
                except Exception:
                    continue

    async def export_date(self, date: Optional[Any]) -> Dict[str, Any]:
        dt = _normalize_date(date)
        ctx = _ExportContext(dt, self._storage)
        return await self._write_exports(
            dt=dt,
            entries=await ctx.entries(),
            daily_summary=await ctx.daily_summary(),
            study_summary=await ctx.study_summary(),
            daily_record=await ctx.daily_record(),
        )

    async def export_after_entry(
        self, entry: JournalEntry, date: Optional[Any]
    ) -> Dict[str, Any]:
        dt = _normalize_date(date)
        ctx = _ExportContext(dt, self._storage)
        persona_hint = _infer_persona_name(entry)
        return await self._write_exports(
            dt=dt,
            entries=await ctx.entries(),
            daily_summary=await ctx.daily_summary(),
            study_summary=await ctx.study_summary(),
            daily_record=await ctx.daily_record(),
            persona_hint=persona_hint,
        )

    async def export_learning_summary(
        self, date: Optional[Any], summary_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        dt = _normalize_date(date)
        ctx = _ExportContext(dt, self._storage)
        return await self._write_exports(
            dt=dt,
            entries=await ctx.entries(),
            daily_summary=await ctx.daily_summary(),
            study_summary=summary_data or {},
            daily_record=await ctx.daily_record(),
        )

    async def _write_exports(
        self,
        *,
        dt: datetime,
        entries: List[JournalEntry],
        daily_summary: Optional[DailySummary],
        study_summary: Dict[str, Any],
        daily_record: Optional[Dict[str, Any]] = None,
        persona_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_migration()

        persona_names = {
            name for name in (_infer_persona_name(entry) for entry in entries) if name
        }
        if persona_hint:
            persona_names.add(persona_hint)
        for default_persona in DEFAULT_PERSONAS:
            persona_names.add(default_persona)

        date_key = dt.strftime("%Y-%m-%d")
        result: Dict[str, Any] = {"date": date_key, "personas": {}}
        scope_indexes: Dict[str, Dict[str, Any]] = {
            "aveline": {"date": date_key, "personas": {}},
            "ling": {"date": date_key, "personas": {}},
        }

        # 预加载各 scope 专属的 daily_summary，避免所有 persona 共享同一个
        aveline_daily_summary = await self._storage.get_daily_summary(dt, scope="aveline")
        ling_daily_summary = await self._storage.get_daily_summary(dt, scope="ling")

        write_tasks = []
        for persona_name in sorted(persona_names):
            scope = get_persona_scope(persona_name)
            persona_specific_summary = (
                ling_daily_summary if scope == "ling" else aveline_daily_summary
            )
            task = self._export_persona(
                dt=dt,
                persona_name=persona_name,
                entries=entries,
                daily_summary=persona_specific_summary,
                aveline_daily_summary=aveline_daily_summary,
                study_summary=study_summary,
                daily_record=daily_record,
                date_key=date_key,
            )
            write_tasks.append(task)

        persona_results = await asyncio.gather(*write_tasks, return_exceptions=True)

        for persona_name, persona_result in zip(sorted(persona_names), persona_results):
            if isinstance(persona_result, Exception):
                logger.warning(f"导出 {persona_name} 日记失败: {persona_result}")
                continue
            scope = persona_result["scope"]
            result["personas"][persona_name] = persona_result
            scope_indexes[scope]["personas"][persona_name] = persona_result

        for scope, index_payload in scope_indexes.items():
            base_dir = self._scope_roots.get(scope)
            if base_dir is None:
                continue
            await asyncio.to_thread(
                (base_dir / "index.json").write_text,
                json.dumps(index_payload, ensure_ascii=False, indent=2),
                "utf-8",
            )
        return result

    async def _export_persona(
        self,
        *,
        dt: datetime,
        persona_name: str,
        entries: List[JournalEntry],
        daily_summary: Optional[DailySummary],
        aveline_daily_summary: Optional[DailySummary],
        study_summary: Dict[str, Any],
        daily_record: Optional[Dict[str, Any]],
        date_key: str,
    ) -> Dict[str, Any]:
        is_ling_persona = persona_name in LING_PERSONAS
        persona_entries = [
            entry for entry in entries
            if _infer_persona_name(entry) == persona_name
            or _entry_mentions_persona(entry, persona_name)
            or (is_ling_persona and _infer_persona_name(entry) is None)
        ]
        diary_entries = [
            _entry_to_dict(entry) for entry in persona_entries if _is_diary_like_entry(entry)
        ]
        final_diary_entry, used_fragments = await _build_final_diary(
            dt=dt,
            persona_name=persona_name,
            diary_entries=diary_entries,
            daily_summary=daily_summary,
            study_summary=study_summary or {},
            daily_record=daily_record,
        )

        scope = get_persona_scope(persona_name)
        base_dir = self._scope_roots.get(scope) or self._scope_roots["aveline"]
        persona_dir = (
            base_dir
            / _get_persona_dir_name(persona_name)
            / str(dt.year)
            / str(dt.month)
            / str(dt.day)
        )
        await asyncio.to_thread(persona_dir.mkdir, parents=True, exist_ok=True)

        diary_payload = {
            "date": date_key,
            "persona": persona_name,
            "entry_count": 1 if final_diary_entry else 0,
            "is_finalized": bool(final_diary_entry),
            "note": "" if final_diary_entry else "今天暂无可用素材，尚未生成成品日记。",
            "source_counts": {
                "diary_fragments": len(diary_entries),
                "used_fragments": len(used_fragments),
            },
            "entries": [final_diary_entry] if final_diary_entry else [],
            "source_fragments_preview": used_fragments[:12],
        }
        learning_payload = {
            "date": date_key,
            "persona": persona_name,
            "study_summary": study_summary or {},
            "daily_summary": (aveline_daily_summary or daily_summary).model_dump() if (aveline_daily_summary or daily_summary) else None,
        }
        index_files = {
            "diary": "diary.json",
        }
        if is_ling_persona:
            index_files["learning_summary"] = "learning_summary.json"
        index_payload = {
            "date": date_key,
            "persona": persona_name,
            "scope": scope,
            "files": index_files,
            "counts": {
                "diary_entries": 1 if final_diary_entry else 0,
            },
        }

        file_writes = [
            (persona_dir / "diary.json", diary_payload),
            (persona_dir / "index.json", index_payload),
        ]
        if is_ling_persona:
            file_writes.insert(1, (persona_dir / "learning_summary.json", learning_payload))
        for filepath, payload in file_writes:
            await asyncio.to_thread(
                filepath.write_text,
                json.dumps(payload, ensure_ascii=False, indent=2),
                "utf-8",
            )

        return {
            "path": str(persona_dir),
            "scope": scope,
            "diary_entries": 1 if final_diary_entry else 0,
        }


_service_instance: Optional[PersonaJournalExportService] = None
# P0-23: 使用 threading.Lock + double-check 保护 get_persona_journal_export_service 单例，
# 防止多线程并发导致重复创建 PersonaJournalExportService 实例（存储重复加载、状态不一致）
_service_lock = threading.Lock()


def get_persona_journal_export_service() -> PersonaJournalExportService:
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _service_instance is not None:
                return _service_instance
            _service_instance = PersonaJournalExportService()
    return _service_instance
