"""FSRS / SM-2 复习调度层（解耦自 VocabularyManager）。

职责：
- 当前 App quality(1-4) → FSRS Rating 映射（0 兼容 Again，5 兼容 Easy）
- 历史事件的**分版本**评分语义：旧事件按发生当时后端实际生效的 0-5 量表解释
- 从进度恢复 / 写回 FSRS Card 状态；从原始 history 按时间 replay 重建
- update_word_progress：FSRS 优先，不可用时回退 SM-2，并同步 daily 生词日志
- update_word_progress_sm2：原 SM-2 回退实现

依赖 VocabDataStore 提供的数据与持久化能力。

评分语义切换（详见 LEGACY_RATING_CUTOFF 注释）：历史里同一个 ``quality=4``
在 cutoff 前后含义不同，rebuild 时必须按事件发生时间选择 schema，不能统一
套用当前 App 语义，否则会把旧 Good 当成 Easy，系统性高估记忆强度。
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from core.utils.logger import get_logger

try:
    from fsrs import Scheduler, Card, Rating, State

    _FSRS_AVAILABLE = True
except ImportError:
    _FSRS_AVAILABLE = False
    Scheduler = Card = Rating = State = None

logger = get_logger("VocabScheduler")

if not _FSRS_AVAILABLE:
    # 核心调度算法不应因安装方式不同静默改变，回退时必须留下明确告警。
    logger.warning(
        "fsrs 库不可用，背单词调度回退到 SM-2（间隔与 FSRS 不一致）；"
        "请安装依赖 fsrs==6.3.2（见 requirements/base.txt 与 pyproject.toml）"
    )

# v1 曾把 App 的 1/2/3/4 误按旧 0-5 量表映射，且使用了 FSRS
# 默认的分钟级 learning steps。App 每天队列是按日锁定的，并不会在
# 10 分钟后重新拉卡，因此分钟级状态只会在第二天造成集中重复。
# v3：rebuild 按事件发生时间区分旧/新评分语义（rating migration）。
FSRS_SCHEMA_VERSION = 3
# 历史评分语义迁移版本；已迁移的进度会带上 rating_migration_version，
# 迁移脚本据此保证幂等，不会把 4→3 之后再跑一次变成 3→2。
RATING_MIGRATION_VERSION = 1

# history 事件来源（新增兼容字段 source；旧记录没有 source 时按 manual_review 处理）
SOURCE_MANUAL_REVIEW = "manual_review"
SOURCE_QUIZ = "quiz"
SOURCE_DAILY_RETRY = "daily_retry"
SOURCE_SAME_SESSION_RETRY = "same_session_retry"
SOURCE_AI_UNFAMILIAR_CHECK = "ai_unfamiliar_check"
HISTORY_SOURCES = (
    SOURCE_MANUAL_REVIEW,
    SOURCE_QUIZ,
    SOURCE_DAILY_RETRY,
    SOURCE_SAME_SESSION_RETRY,
    SOURCE_AI_UNFAMILIAR_CHECK,
)

# ---------------------------------------------------------------------------
# 评分语义切换时间（cutoff）
#
# 依据（不靠猜测，均可在仓库内复核）：
#   1. 旧版 fsrs_scheduler.py 的映射为 1/2→Again、3→Hard、4→Good、5→Easy
#      （commit 6ddb82f9，2026-08-26 之前的实现）。
#   2. 现行映射 1=Again、2=Hard、3=Good、4=Easy 由 commit aad9c453
#      （2026-09-03 17:31 +0800 的批量自动提交）带入，更新日志「2026-09-01」
#      条目（docs/updates/2026/09/2026-09-01.md）记录了这次修复。
#   3. 同一次修复执行了 FSRS v2 历史重建，落盘备份
#      output/user_data/vocab_progress.pre_fsrs_v2_20260901_154729.bak.json，
#      即新映射最迟在 2026-09-01 15:47:29（Asia/Shanghai）已经生效；
#      该备份内最后一条历史为 2026-08-31 19:01:45，9/1 当天 15:47 之前没有任何
#      复习事件，因此这个边界不存在归属歧义。
#
# cutoff 之前：1/2 -> Again，3 -> Hard，4 -> Good，5 -> Easy
# cutoff 之后：1 -> Again，2 -> Hard，3 -> Good，4 -> Easy
# ---------------------------------------------------------------------------
LEGACY_RATING_CUTOFF_ISO = "2026-09-01T15:47:29+08:00"
LEGACY_RATING_CUTOFF = datetime.fromisoformat(LEGACY_RATING_CUTOFF_ISO).timestamp()

# Hard 在 FSRS 中是成功回忆，默认交给 FSRS 调度；只有卡片仍然很脆弱
# （stability 低于该阈值天，通常是刚学的新词）时才额外安排第二天 daily 重看。
# 参考值：新卡判 Hard 后 stability≈1.29 天，判 Good 后≈2.31 天。
HARD_DAILY_RETRY_STABILITY_DAYS = 2.0


def create_daily_scheduler() -> "Scheduler":
    """创建适配「每日固定队列」的 FSRS 调度器。

    - 不使用分钟级学习/重学步骤：Again/Hard 由 daily 日志保证
      第二天优先出现，Good/Easy 直接进入 FSRS 的天级长期调度。
    - 关闭 interval fuzzing：本项目的 Card 会经常被「从 history 重建」
      （迁移、旧 schema 升级、状态损坏修复）。带 fuzz 时同一份历史每次
      rebuild 都会得到不同的 due，迁移无法幂等也无法验证；关闭后
      replay 完全确定。
    """
    return Scheduler(
        learning_steps=(), relearning_steps=(), enable_fuzzing=False
    )


def quality_to_rating(quality: int) -> Optional[int]:
    """当前 App API 语义：1=Again、2=Hard、3=Good、4=Easy。

    只描述**现在**的 App 契约，不含任何历史兼容逻辑；历史请走
    :func:`historical_quality_to_rating` / :func:`history_event_to_rating`。
    0 作为 Again、5 作为 Easy 保留兼容。
    """
    if not _FSRS_AVAILABLE:
        return None
    if quality <= 1:
        return Rating.Again
    elif quality == 2:
        return Rating.Hard
    elif quality == 3:
        return Rating.Good
    else:
        return Rating.Easy


def legacy_quality_to_rating(quality: int) -> Optional[int]:
    """cutoff 之前后端实际生效的旧 0-5 语义：1/2→Again、3→Hard、4→Good、5→Easy。"""
    if not _FSRS_AVAILABLE:
        return None
    if quality <= 2:
        return Rating.Again
    elif quality == 3:
        return Rating.Hard
    elif quality == 4:
        return Rating.Good
    else:
        return Rating.Easy


def historical_quality_to_rating(
    quality: int, timestamp: Optional[float]
) -> Optional[int]:
    """按**事件发生时间**选择评分 schema。

    timestamp 缺失或非法时按旧语义解释：旧语义更保守，不会因为信息缺失
    而把历史评分放大成 Easy。
    """
    try:
        ts = float(timestamp or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if ts <= 0 or ts < LEGACY_RATING_CUTOFF:
        return legacy_quality_to_rating(quality)
    return quality_to_rating(quality)


def history_event_to_rating(event: Dict[str, Any]) -> Optional[int]:
    """history 事件 → FSRS Rating（自动选择该时刻的评分 schema）。"""
    if not isinstance(event, dict):
        return None
    try:
        quality = int(event.get("quality"))
    except (TypeError, ValueError):
        return None
    return historical_quality_to_rating(quality, event.get("timestamp"))


def latest_review_timestamp(data: Dict[str, Any]) -> float:
    """返回该词最近一次复习的时间戳（秒）。

    只看 ``fsrs_last_review`` 在 FSRS 不可用时是错的：此时 :func:`apply_progress`
    会回退到 SM-2，只写 ``next_review``，``fsrs_last_review`` / ``fsrs_due``
    会一直停留在「fsrs 缺失之前」的旧值。后果是当天背过的词被判成「今天没
    背过且早已到期」，刷新每日队列依旧是满的（2026-09-13 实测）。

    history 是 append-only 的复习证据，与 ``fsrs_last_review`` 取最大值即可
    同时覆盖 FSRS 正常与回退两种写入路径。
    """
    if not isinstance(data, dict):
        return 0.0
    candidates: list[float] = []
    try:
        fsrs_last = float(data.get("fsrs_last_review") or 0)
    except (TypeError, ValueError):
        fsrs_last = 0.0
    if fsrs_last > 0:
        candidates.append(fsrs_last)
    for event in data.get("history", []) or []:
        if not isinstance(event, dict):
            continue
        try:
            ts = float(event.get("timestamp", 0) or 0)
        except (TypeError, ValueError):
            continue
        if ts > 0:
            candidates.append(ts)
    return max(candidates, default=0.0)


def event_is_lapse(event: Dict[str, Any]) -> bool:
    """该次复习是否为「没想起来」（Again）。

    独立于 fsrs 库，便于统计/弱词筛选按同样的语义判断：
    旧语义 1/2 都是 Again，新语义只有 1 是 Again。
    """
    if not isinstance(event, dict):
        return False
    try:
        quality = int(event.get("quality"))
        ts = float(event.get("timestamp") or 0)
    except (TypeError, ValueError):
        return False
    if ts > 0 and ts >= LEGACY_RATING_CUTOFF:
        return quality <= 1
    return quality <= 2


def normalize_source(source: Optional[str]) -> str:
    """归一化 history 的 source 字段；未知/缺失一律按 manual_review。"""
    if source in HISTORY_SOURCES:
        return source
    return SOURCE_MANUAL_REVIEW


def should_retry_tomorrow(rating: Optional[int], card: Optional["Card"]) -> bool:
    """是否把该词写入第二天 daily 重试队列。

    Again：确实没想起来，一定重试。
    Hard：FSRS 语义下属于成功回忆，默认交给 FSRS 调度；只有卡片仍然很脆弱
    （stability 低于阈值，通常是刚学的新词）时才额外安排第二天重看。
    """
    if rating is None or Rating is None:
        return False
    if rating == Rating.Again:
        return True
    if rating == Rating.Hard:
        if card is None:
            return False
        try:
            stability = float(getattr(card, "stability", None) or 0)
        except (TypeError, ValueError):
            return False
        return stability < HARD_DAILY_RETRY_STABILITY_DAYS
    return False


def rebuild_fsrs_card_from_history(
    data: Dict[str, Any], until: Optional[float] = None
) -> "Card":
    """从原始 history 按时间 replay 重建当前 FSRS Card。

    - 每个事件按**它发生那一刻**的评分 schema 解释（见 LEGACY_RATING_CUTOFF）；
    - ``until`` 用于只 replay ``timestamp < until`` 的事件，避免把正在处理的
      那次评分重复计入；
    - 同样的 history 一定得到同样的 Card（事件按 timestamp 排序，确定性回放）。
    """
    card = Card()
    if not _FSRS_AVAILABLE:
        return card
    scheduler = create_daily_scheduler()
    events = []
    for event in data.get("history", []):
        if not isinstance(event, dict):
            continue
        try:
            timestamp = float(event.get("timestamp", 0) or 0)
            quality = int(event.get("quality"))
        except (TypeError, ValueError):
            continue
        if timestamp <= 0:
            continue
        if until is not None and timestamp >= until:
            continue
        rating = historical_quality_to_rating(quality, timestamp)
        if rating is None:
            continue
        events.append((timestamp, rating))
    for timestamp, rating in sorted(events, key=lambda item: item[0]):
        reviewed = scheduler.review_card(
            card,
            rating,
            review_datetime=datetime.fromtimestamp(timestamp, timezone.utc),
        )
        card = reviewed[0] if isinstance(reviewed, tuple) else reviewed
    return card


def state_lags_behind_history(data: Dict[str, Any]) -> bool:
    """落盘的 FSRS 状态是否已经落后于 history。

    fsrs 库不可用时 :func:`apply_progress` 会回退到 SM-2，只写 history 与
    ``next_review``，``fsrs_*`` 停在旧值。装回 fsrs 后如果继续信任这份状态，
    缺失期间的评分会被永久忽略（卡片从几天甚至几周前续算，到期日偏近）。
    """
    if not isinstance(data, dict):
        return False
    try:
        state_ts = float(data.get("fsrs_last_review") or 0)
    except (TypeError, ValueError):
        state_ts = 0.0
    return latest_review_timestamp(data) > state_ts + 1e-6


def fsrs_card_from_progress(
    data: Dict[str, Any], before: Optional[float] = None
) -> "Card":
    """从存储的进度恢复一个 FSRS Card（首次或旧 schema 则用历史重建）。

    ``before`` 会透传给重建逻辑，用于排除「本次正在处理的事件」。
    """
    card = Card()
    fsrs_fields = (
        "fsrs_state",
        "fsrs_step",
        "fsrs_stability",
        "fsrs_difficulty",
        "fsrs_due",
        "fsrs_last_review",
    )
    if (
        data.get("fsrs_schema_version") == FSRS_SCHEMA_VERSION
        and all(f in data for f in fsrs_fields)
        and data["fsrs_stability"] is not None
    ):
        try:
            card.state = State(data["fsrs_state"])
            card.step = data["fsrs_step"]
            card.stability = data["fsrs_stability"]
            card.difficulty = data["fsrs_difficulty"]
            # FSRS due/last_review 以 UTC 时间戳（秒）存储
            card.due = datetime.fromtimestamp(data["fsrs_due"], timezone.utc)
            if data["fsrs_last_review"]:
                card.last_review = datetime.fromtimestamp(
                    data["fsrs_last_review"], timezone.utc
                )
        except Exception:
            return rebuild_fsrs_card_from_history(data, until=before)
        # 状态落后于 history（fsrs 缺失期间只写 history 的 SM-2 回退写入）：
        # 落盘状态不可信，必须按 history 全量重建，否则这些评分会被永久忽略。
        if state_lags_behind_history(data):
            return rebuild_fsrs_card_from_history(data, until=before)
        return card
    # 旧版状态的评分映射和学习步骤都不适用，以原始历史重建。
    return rebuild_fsrs_card_from_history(data, until=before)


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
    data["fsrs_schema_version"] = FSRS_SCHEMA_VERSION
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
    store, word: str, quality: int, source: str = SOURCE_MANUAL_REVIEW
) -> Dict[str, Any]:
    """更新某个词的复习进度（FSRS 优先，回退 SM-2）。

    Args:
        store: VocabDataStore 实例
        word: 单词
        quality: App 1-4 评分（0/5 为兼容值）
        source: 评分来源，见 HISTORY_SOURCES；仅记录，不影响调度
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
    now_ts = time.time()
    event = {
        "timestamp": now_ts,
        "quality": quality,
        "source": normalize_source(source),
    }
    new_card = None

    # ---- FSRS 调度（优先）；库不可用时回退到原 SM-2 ----
    rating = quality_to_rating(quality)
    if rating is not None:
        try:
            scheduler = create_daily_scheduler()
            now_utc = datetime.fromtimestamp(now_ts, timezone.utc)
            # 关键顺序：先用「本次评分之前」的状态恢复 Card（缺失/旧 schema 时
            # 从 history 重建），再应用当前这一次评分，最后才把事件写进 history。
            # 若先 append 再恢复，rebuild 会先把这次评分算一遍，随后
            # review_card 再算一遍，新卡首次评分就会被重复计入（double-count）。
            card = fsrs_card_from_progress(data, before=now_ts)
            reviewed = scheduler.review_card(card, rating, review_datetime=now_utc)
            new_card = reviewed[0] if isinstance(reviewed, tuple) else reviewed
            data["history"].append(event)
            save_fsrs_to_progress(data, new_card)
            data["reps"] = len(
                [
                    e
                    for e in data["history"]
                    if isinstance(e, dict) and e.get("quality") is not None
                ]
            )
            # 保留 easiness 仅用于向后兼容展示，不再参与调度
        except Exception as e:
            logger.warning(f"FSRS 调度失败，回退 SM-2 ({word}): {e}")
            if event not in data["history"]:
                data["history"].append(event)
            update_word_progress_sm2(data, quality)
    else:
        data["history"].append(event)
        update_word_progress_sm2(data, quality)

    store.save_progress()

    # 同步 daily 生词日志：复习后无论会/不会，先移除旧记录（避免当天
    # 重新拉取复习词时又出现刚复习过的词）；需要第二天重试的再写入当天
    # 文件，明天复习时优先出现。
    #
    # 不再用 quality<=2 判断「不会」：新语义下 2=Hard 属于成功回忆，
    # 交给 FSRS 调度即可，只有 Again（以及仍很脆弱的新词被判 Hard）才重试。
    if rating is not None:
        retry_tomorrow = should_retry_tomorrow(rating, new_card)
    else:
        retry_tomorrow = quality is not None and quality <= 1
    daily_synced = False
    if quality is not None:
        try:
            from .daily_word_log import get_daily_word_log
            from core.utils.time_utils import get_current_time_str

            log = get_daily_word_log()
            log.remove(word)
            if retry_tomorrow:
                log.mark_unknown(word, date=get_current_time_str("%Y/%m/%d"))
            daily_synced = True
        except Exception as e:
            logger.error(f"同步 daily 生词日志失败 ({word}): {e}")

    # App 的评分与 AI 长期生词本共用同一难度计数：答错时 +1，答对时 -1。
    # 这样 App 的错题会进入 AI 的 unfamiliar 抽查池；AI 对 unfamiliar 的
    # 标记也会通过 /vocab/mistakes 合并结果回显到 App。
    # 与 daily 重试同一口径：只有 Again（以及仍很脆弱的新词被判 Hard）算不会。
    unfamiliar_synced = False
    unfamiliar_unknown_count = None
    if quality is not None:
        try:
            from .unfamiliar_word_book import get_unfamiliar_word_book

            unfamiliar_book = get_unfamiliar_word_book()
            if retry_tomorrow:
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
        "daily_retry": retry_tomorrow,
        "unfamiliar_synced": unfamiliar_synced,
        "unfamiliar_unknown_count": unfamiliar_unknown_count,
        "source": normalize_source(source),
    }
