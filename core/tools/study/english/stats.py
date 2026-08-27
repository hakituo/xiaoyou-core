"""统计与总览层（解耦自 VocabularyManager）。

职责：
- get_stats：词典/进度总体统计
- get_mistakes / get_weak_words：错词与弱词
- get_retention_curve / get_memory_curve_data：记忆曲线（旧/新）
- get_review_overview：首页总览
- _calc_daily_streak / _predict_memory_curve：底层计算
- get_manual_study_stats：手动背诵统计

依赖 VocabDataStore 提供数据与进度。
"""

import math
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import ts_to_str, get_current_time
from .loader import MASTER_FILE

logger = get_logger("VocabStats")


# 词书选择列表的固定展示顺序（递进式分级词书）
LEVEL_ORDER = [
    "CET4-顺序.json",
    "CET6-顺序.json",
    "考研-顺序.json",
    "托福-顺序.json",
    "雅思-顺序.json",
    "GRE-顺序.json",
]


def get_stats(store) -> Dict:
    progress_stats = store.get_progress_stats()

    available_words = []
    available_sentences = []

    try:
        if os.path.exists(store.words_dir):
            available_words.extend(
                [f for f in os.listdir(store.words_dir) if f.endswith(".json")]
            )
        if os.path.exists(store.sentence_dir):
            available_sentences.extend(
                [f for f in os.listdir(store.sentence_dir) if f.endswith(".json")]
            )
        if os.path.exists(store.study_data_root):
            root_files = [
                f
                for f in os.listdir(store.study_data_root)
                if f.endswith(".json") and f not in ["Words", "Sentence"]
            ]
            available_words.extend(root_files)
        available_words = list(set(available_words))
        available_sentences = list(set(available_sentences))
        # 排除全量释义总表（仅复习释义兜底用，不作为可选词书），并按级别固定顺序展示
        available_words = [f for f in available_words if f != MASTER_FILE]
        available_words = [
            f for f in LEVEL_ORDER if f in available_words
        ] + sorted(f for f in available_words if f not in LEVEL_ORDER)
    except Exception as e:
        logger.error(f"Failed to list dictionary files: {e}")

    total_words = (
        store.get_word_count_from_file()
        if not store._loaded
        else len(store.dictionary)
    )

    return {
        "total_words": total_words,
        "learned_words": progress_stats["learned"],
        "due_words": progress_stats["due"],
        "to_review": progress_stats["due"],
        "mastered_words": progress_stats["mastered"],
        "available_word_files": available_words,
        "available_sentence_files": available_sentences,
        "current_dictionary": os.path.basename(store.dictionary_path),
        "current_sentence_collection": (
            os.path.basename(store.sentence_path) if store.sentence_path else None
        ),
    }


def get_linked_unfamiliar_words(
    store,
    unfamiliar_words: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict]:
    """构建长期生词本与 App 历史错题的只读合并视图。

    ``progress.history`` 是 App/FSRS 的历史错误次数，``unfamiliar_word.txt``
    是 AI 与用户共同维护的当前难词计数。App 评分会同时更新两侧，因此合并
    时取两者较大值，避免同一次错误被重复相加；同时保留两个原始计数字段，
    方便调用方解释来源。
    """
    store._ensure_loaded()
    if unfamiliar_words is None:
        try:
            from .unfamiliar_word_book import get_unfamiliar_word_book

            unfamiliar_words = get_unfamiliar_word_book().list_words()
        except Exception as exc:
            logger.warning("读取 unfamiliar 错词失败: %s", exc)
            unfamiliar_words = []

    mistakes_by_word: Dict[str, Dict[str, Any]] = {}
    for item in unfamiliar_words:
        word = str(item.get("word") or "").strip()
        unknown_count = max(0, int(item.get("unknown_count") or 0))
        if not word:
            continue
        key = word.lower()
        mistakes_by_word[key] = {
            **item,
            "word": word,
            "unknown_count": unknown_count,
            "error_count": unknown_count,
            "progress_error_count": 0,
            "unfamiliar_count": unknown_count,
            "last_error": 0,
        }

    for word, data in store.progress.items():
        errors = sum(1 for h in data.get("history", []) if h["quality"] < 3)
        if errors <= 0:
            continue
        key = str(word).strip().lower()
        current = mistakes_by_word.setdefault(
            key,
            {
                "word": word,
                "unknown_count": 0,
                "error_count": 0,
                "progress_error_count": 0,
                "unfamiliar_count": 0,
                "last_error": 0,
            },
        )
        current["progress_error_count"] = errors
        current["last_error"] = (
            data.get("history", [])[-1]["timestamp"] if data.get("history") else 0
        )
        linked_count = max(int(current.get("unfamiliar_count") or 0), errors)
        current["unknown_count"] = linked_count
        current["error_count"] = linked_count

    for item in mistakes_by_word.values():
        item["sources"] = [
            source
            for source, value in (
                ("progress", item.get("progress_error_count", 0)),
                ("unfamiliar", item.get("unfamiliar_count", 0)),
            )
            if value
        ]
    return list(mistakes_by_word.values())


def get_mistakes(
    store,
    limit: int = 20,
    unfamiliar_words: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict]:
    """返回 App 错题本，并合并长期 unfamiliar 难词计数。"""
    linked_words = get_linked_unfamiliar_words(store, unfamiliar_words)

    mistake_counts = sorted(
        (
            item
            for item in linked_words
            if int(item.get("error_count") or 0) > 0
        ),
        key=lambda item: (
            int(item.get("error_count") or 0),
            float(item.get("last_error") or 0),
        ),
        reverse=True,
    )

    result = []
    for m in mistake_counts[:limit]:
        info = store.get_word_info(m["word"])
        result.append(
            {
                **m,
                "translations": info.get("translations", []) if info else [],
            }
        )
    return result


def get_weak_words(store, limit: int = 50) -> List[Dict]:
    store._ensure_loaded()
    weak_words = []
    for word, data in store.progress.items():
        is_weak = False
        if data["interval"] < 3 and data["reps"] > 0:
            is_weak = True
        elif data["history"] and data["history"][-1]["quality"] < 3:
            is_weak = True
        if is_weak:
            word_info = store.get_word_info(word)
            if word_info:
                weak_words.append({**word_info, "stats": data})
    weak_words.sort(key=lambda x: x["stats"]["interval"])
    return weak_words[:limit]


def get_retention_curve(store) -> List[int]:
    """旧的艾宾浩斯近似曲线（基于 easiness/interval 的简化投影）。"""
    store._ensure_loaded()
    if not store.progress:
        return [100, 80, 60, 45, 35, 28, 25]  # Default Ebbinghaus

    total_easiness = sum(d["easiness"] for d in store.progress.values())
    avg_easiness = total_easiness / len(store.progress)
    total_interval = sum(d["interval"] for d in store.progress.values())
    avg_interval = total_interval / len(store.progress)

    curve = []
    for day in range(1, 8):
        stability = max(1.0, avg_interval * 0.5 + (avg_easiness - 2.5) * 5)
        retention = math.exp(-day / stability) * 100
        curve.append(min(100, max(5, int(retention))))
    return curve


def get_memory_curve_data(store) -> Dict:
    store._ensure_loaded()
    stats = get_stats(store)
    weak_words = get_weak_words(store, limit=1000)

    future_reviews = {}
    now = time.time()
    for data in store.progress.values():
        if data["next_review"] > now:
            days = math.ceil((data["next_review"] - now) / (24 * 3600))
            if days < 0:
                days = 0
            if days not in future_reviews:
                future_reviews[days] = 0
            future_reviews[days] += 1

    future_review_list = [
        {"day": d, "count": c}
        for d, c in sorted(future_reviews.items())
        if d <= 30
    ]

    return {
        "stats": stats,
        "weak_word_count": len(weak_words),
        "future_reviews": future_review_list,
        "review_advice": [
            {
                "word": w["word"],
                "next_review": ts_to_str(
                    w["stats"]["next_review"], "%Y-%m-%d %H:%M:%S"
                ),
            }
            for w in weak_words[:10]
        ],
    }


def _calc_daily_streak(store) -> int:
    """从 daily 日志目录倒推最近连续「有内容」的日期数。

    从今天往前数，跳过空文件（今天还没背但文件已预创建），
    遇到不存在或无内容的文件则中断。
    """
    try:
        from .daily_word_log import get_daily_word_log

        log = get_daily_word_log()
        base = getattr(log, "base_dir", None) or os.path.join(
            store.study_data_root, "Words", "daily"
        )
        streak = 0
        cur = get_current_time().date()
        today = cur
        for _ in range(365):
            ymd = cur.strftime("%Y/%m/%d")
            y, m, d = ymd.split("/")
            fpath = os.path.join(base, y, m, f"{d}.txt")
            if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                streak += 1
                cur = cur - timedelta(days=1)
            else:
                if cur == today:
                    cur = cur - timedelta(days=1)
                    continue
                break
        return streak
    except Exception:
        return 0


def _predict_memory_curve(store, days: int = 30) -> List[Dict]:
    """基于 FSRS stability 预测未来 days 天整体记忆留存率曲线。

    recall(t) = 2^(-Δt / stability)，整体取平均。
    仅对已有 FSRS 状态的词有效；老 SM-2 词用 interval 近似 stability。
    """
    try:
        word_stabilities = []
        for data in store.progress.values():
            stab = data.get("fsrs_stability")
            if not stab:
                iv = data.get("interval", 0)
                stab = max(iv, 1.0)
            else:
                stab = max(stab, 0.5)
            if stab and stab > 0:
                word_stabilities.append(stab)
        if not word_stabilities:
            return []
        per_day = []
        for day in range(1, days + 1):
            recalls = [2.0 ** (-day / s) for s in word_stabilities]
            avg = sum(recalls) / len(recalls) if recalls else 0.0
            per_day.append({"day": day, "retention": round(avg * 100, 1)})
        return per_day
    except Exception:
        return []


def get_review_overview(store) -> Dict:
    """首页/统计页总览。"""
    from .quiz import get_daily_words

    store._ensure_loaded()
    now = time.time()

    due_today = get_daily_words(store, 0)
    streak = _calc_daily_streak(store)
    curve = get_memory_curve_data(store)
    future_reviews = curve.get("future_reviews", [])
    memory_curve = _predict_memory_curve(store, days=30)

    learned = len(store.progress)
    due_count = sum(
        1
        for d in store.progress.values()
        if (d.get("fsrs_due") or d.get("next_review", 0)) <= now
    )
    mastered = sum(1 for d in store.progress.values() if d.get("interval", 0) > 21)

    return {
        "due_today_count": len(due_today),
        "streak_days": streak,
        "learned_words": learned,
        "due_words": due_count,
        "mastered_words": mastered,
        "future_reviews": future_reviews,
        "memory_curve": memory_curve,
        "new_today": sum(1 for w in due_today if w.get("status") == "new"),
        "review_today": sum(1 for w in due_today if w.get("status") == "review"),
    }


def get_today_review_status(
    store,
    daily_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """返回今日词汇任务的实时权威状态。

    ``get_stats().to_review`` 只统计当前已经到期的 FSRS 卡片，不能表达
    “今天这一轮是否做完”；昨日日记里的 ``review_target`` 也只是旧快照。
    这里统一按 Android 实际取词口径计算剩余量，并补充今日已复习与最终
    未掌握数量，供 Active Care 做事实锚点和发送前校验。

    每次会话正常结束时，StudyService 已经会把“完成词汇复习”写进当日生活
    记录。这个显式完成记录的优先级高于动态 FSRS 队列：会话结束后新到期的
    少量卡片不能把今天重新判为“没背完”。传入 ``daily_record`` 主要用于测试
    和调用方复用已加载的数据；不传则读取当天记录。
    """
    store._ensure_loaded()
    from .quiz import get_daily_words

    now = get_current_time()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    tomorrow_start = (now + timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).timestamp()

    reviewed_words = 0
    review_events = 0
    new_words = 0
    mistake_words = 0
    for data in store.progress.values():
        history = data.get("history", [])
        today_entries = [
            entry
            for entry in history
            if today_start <= float(entry.get("timestamp", 0) or 0) < tomorrow_start
        ]
        if not today_entries:
            continue
        reviewed_words += 1
        review_events += len(today_entries)
        if len(history) == len(today_entries):
            new_words += 1
        if any(int(entry.get("quality", 5) or 5) < 3 for entry in today_entries):
            mistake_words += 1

    unresolved_words = 0
    try:
        from .daily_word_log import get_daily_word_log

        today_key = now.strftime("%Y/%m/%d")
        unresolved_words = len(
            {
                str(item.get("word") or "").strip().lower()
                for item in get_daily_word_log().get_words_for_date(today_key)
                if str(item.get("word") or "").strip()
            }
        )
    except Exception as exc:
        logger.warning("读取今日未掌握词数量失败: %s", exc)

    remaining_words = len(get_daily_words(store, 0))

    if daily_record is None:
        try:
            from core.services.daily.manager import get_daily_manager

            daily_record = get_daily_manager().get_record(now.strftime("%Y-%m-%d"))
        except Exception as exc:
            logger.warning("读取今日词汇会话完成记录失败: %s", exc)
            daily_record = {}

    completed_session = None
    study_data = daily_record.get("study", {}) if isinstance(daily_record, dict) else {}
    sessions = study_data.get("sessions", []) if isinstance(study_data, dict) else []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        topic = str(session.get("topic") or "").strip()
        content = str(session.get("content") or "").strip()
        if topic == "英语词汇" and "完成词汇复习" in content:
            completed_session = session

    explicitly_completed = completed_session is not None
    completed = explicitly_completed or (reviewed_words > 0 and remaining_words == 0)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "reviewed_words": reviewed_words,
        "review_events": review_events,
        "new_words": new_words,
        "mistake_words": mistake_words,
        "unresolved_words": unresolved_words,
        "remaining_words": remaining_words,
        "completed": completed,
        "completion_source": (
            "daily_study_session"
            if explicitly_completed
            else ("empty_current_queue" if completed else "")
        ),
        "completed_at": (
            str(completed_session.get("time") or "") if completed_session else ""
        ),
    }


def get_manual_study_stats(store, days: int = 7, date: str = None) -> Dict[str, Any]:
    """获取手动背诵统计。"""
    store._ensure_loaded()
    meta = store.meta.get("manual_study", {})

    if date:
        entry = meta.get(date)
        return {
            "status": "success",
            "date": date,
            "total": entry["total"] if entry else 0,
            "sessions": entry["sessions"] if entry else 0,
        }

    today = time.strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    recent = {d: v for d, v in meta.items() if cutoff <= d <= today}
    recent = dict(sorted(recent.items()))
    return {
        "status": "success",
        "range": f"{cutoff} ~ {today}",
        "days": recent,
        "range_total": sum(v["total"] for v in recent.values()),
        "range_sessions": sum(v["sessions"] for v in recent.values()),
        "all_total": sum(v["total"] for v in meta.values()),
    }


def add_manual_study(store, count: int, date: str = None) -> Dict[str, Any]:
    """手动记录当天背了多少单词。"""
    if not count or count <= 0:
        return {"status": "error", "message": "count 必须为正整数"}
    store._ensure_loaded()
    if date is None:
        date = time.strftime("%Y-%m-%d")

    meta = store.meta.setdefault("manual_study", {})
    day_entry = meta.setdefault(date, {"total": 0, "sessions": 0, "updated_at": 0})
    day_entry["total"] += int(count)
    day_entry["sessions"] += 1
    day_entry["updated_at"] = time.time()

    store.save_progress()
    return {
        "status": "success",
        "date": date,
        "added": int(count),
        "day_total": day_entry["total"],
        "day_sessions": day_entry["sessions"],
        "all_total": sum(d["total"] for d in meta.values()),
    }
