"""FSRS / SM-2 复习调度层（解耦自 VocabularyManager）。

职责：
- quality(0-5) → FSRS Rating 映射
- 从进度恢复 / 写回 FSRS Card 状态
- update_word_progress：FSRS 优先，不可用时回退 SM-2，并同步 daily 生词日志
- _update_word_progress_sm2：原 SM-2 回退实现

依赖 VocabDataStore 提供的数据与持久化能力。
"""

import time
from typing import Dict, Any, Optional

from core.utils.logger import get_logger

try:
    from fsrs import Scheduler, Card, Rating, State
    from datetime import timezone as _tz

    _FSRS_AVAILABLE = True
except ImportError:
    _FSRS_AVAILABLE = False
    Scheduler = Card = Rating = State = None
    _tz = None

logger = get_logger("VocabScheduler")


def quality_to_rating(quality: int) -> Optional[int]:
    """quality 0-5 → FSRS Rating（Again/Hard/Good/Easy）。"""
    if not _FSRS_AVAILABLE:
        return None
    if quality <= 2:
        return Rating.Again
    elif quality == 3:
        return Rating.Hard
    elif quality == 4:
        return Rating.Good
    else:  # 5
        return Rating.Easy


def fsrs_card_from_progress(data: Dict[str, Any]) -> "Card":
    """从存储的进度恢复一个 FSRS Card（首次则新建）。"""
    card = Card()
    fsrs_fields = (
        "fsrs_state",
        "fsrs_step",
        "fsrs_stability",
        "fsrs_difficulty",
        "fsrs_due",
        "fsrs_last_review",
    )
    if all(f in data for f in fsrs_fields) and data["fsrs_stability"] is not None:
        try:
            card.state = State(data["fsrs_state"])
            card.step = data["fsrs_step"]
            card.stability = data["fsrs_stability"]
            card.difficulty = data["fsrs_difficulty"]
            # FSRS due/last_review 以 UTC 时间戳（秒）存储
            card.due = datetime.fromtimestamp(data["fsrs_due"], _tz.utc)
            if data["fsrs_last_review"]:
                card.last_review = datetime.fromtimestamp(
                    data["fsrs_last_review"], _tz.utc
                )
        except Exception:
            card = Card()
    return card


# fsrs_card_from_progress 用到的 datetime 需在函数内可用，统一在顶部导入
from datetime import datetime  # noqa: E402  (放在函数定义之后以匹配原文件结构)


def save_fsrs_to_progress(data: Dict[str, Any], card: "Card"):
    """把 FSRS Card 状态写回进度 dict（due/last_review 存 UTC 时间戳秒）。"""
    data["fsrs_state"] = int(card.state)
    data["fsrs_step"] = card.step
    data["fsrs_stability"] = card.stability
    data["fsrs_difficulty"] = card.difficulty
    data["fsrs_due"] = card.due.timestamp()
    data["fsrs_last_review"] = (
        card.last_review.timestamp() if card.last_review else None
    )
    # 兼容老字段：用 FSRS 的 due 作为 next_review（秒级时间戳）
    data["next_review"] = data["fsrs_due"]
    data["interval"] = max(0.0, (data["fsrs_due"] - time.time()) / 86400.0)


def update_word_progress_sm2(data: Dict[str, Any], quality: int):
    """原 SM-2 逻辑（FSRS 不可用时的回退，或首次初始化兼容）。"""
    if quality >= 3:
        if data["reps"] == 0:
            data["interval"] = 0.125
        elif data["reps"] == 1:
            data["interval"] = 0.33
        elif data["reps"] == 2:
            data["interval"] = 1.0
        elif data["reps"] == 3:
            data["interval"] = 3.0
        else:
            data["interval"] = data["interval"] * data["easiness"]
        data["reps"] += 1
        data["easiness"] += 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        if data["easiness"] < 1.3:
            data["easiness"] = 1.3
    else:
        data["reps"] = 0
        data["interval"] = 0.01
    data["next_review"] = time.time() + data["interval"] * 86400


def apply_progress(
    store, word: str, quality: int
) -> Dict[str, Any]:
    """更新某个词的复习进度（FSRS 优先，回退 SM-2）。

    Args:
        store: VocabDataStore 实例
        word: 单词
        quality: 0-5 评分
    Returns:
        dict: 含 interval/next_review/fsrs_*/daily_synced 的结果
    """
    store._ensure_loaded()
    if word not in store.progress:
        store.progress[word] = {
            "reps": 0,
            "interval": 0,
            "easiness": 2.5,
            "next_review": 0,
            "history": [],
        }

    data = store.progress[word]
    data["history"].append({"timestamp": time.time(), "quality": quality})

    # ---- FSRS 调度（优先）；库不可用时回退到原 SM-2 ----
    rating = quality_to_rating(quality)
    if rating is not None:
        try:
            scheduler = Scheduler()
            now_utc = datetime.now(_tz.utc)
            card = fsrs_card_from_progress(data)
            reviewed = scheduler.review_card(card, rating, review_datetime=now_utc)
            new_card = reviewed[0] if isinstance(reviewed, tuple) else reviewed
            save_fsrs_to_progress(data, new_card)
            data["reps"] = data.get("reps", 0) + 1
            # 保留 easiness 仅用于向后兼容展示，不再参与调度
        except Exception as e:
            logger.warning(f"FSRS 调度失败，回退 SM-2 ({word}): {e}")
            update_word_progress_sm2(data, quality)
    else:
        update_word_progress_sm2(data, quality)

    store.save_progress()

    # 同步 daily 生词日志：复习后无论会/不会，先移除旧记录（避免当天
    # 重新拉取复习词时又出现刚复习过的词）；quality<=2（不认识/遗忘）再
    # 写入当天文件，明天复习时优先出现。
    daily_synced = False
    if quality is not None:
        try:
            from .daily_word_log import get_daily_word_log
            from core.utils.time_utils import get_current_time_str

            log = get_daily_word_log()
            log.remove(word)
            if quality <= 2:
                log.mark_unknown(word, date=get_current_time_str("%Y/%m/%d"))
            daily_synced = True
        except Exception as e:
            logger.error(f"同步 daily 生词日志失败 ({word}): {e}")

    # App 的评分与 AI 长期生词本共用同一难度计数：答错时 +1，答对时 -1。
    # 这样 App 的错题会进入 AI 的 unfamiliar 抽查池；AI 对 unfamiliar 的
    # 标记也会通过 /vocab/mistakes 合并结果回显到 App。
    unfamiliar_synced = False
    unfamiliar_unknown_count = None
    if quality is not None:
        try:
            from .unfamiliar_word_book import get_unfamiliar_word_book

            unfamiliar_book = get_unfamiliar_word_book()
            if quality <= 2:
                unfamiliar_result = unfamiliar_book.mark_unknown(word)
            else:
                unfamiliar_result = unfamiliar_book.mark_known(word)
            unfamiliar_unknown_count = unfamiliar_result.get("unknown_count", 0)
            unfamiliar_synced = True
        except Exception as e:
            logger.error(f"同步 unfamiliar 生词本失败 ({word}): {e}")

    return {
        "word": word,
        "interval": data.get("interval", 0),
        "next_review": data.get("next_review", 0),
        "easiness": data.get("easiness", 2.5),
        "reps": data.get("reps", 0),
        "fsrs_stability": data.get("fsrs_stability"),
        "fsrs_difficulty": data.get("fsrs_difficulty"),
        "daily_synced": daily_synced,
        "unfamiliar_synced": unfamiliar_synced,
        "unfamiliar_unknown_count": unfamiliar_unknown_count,
    }
