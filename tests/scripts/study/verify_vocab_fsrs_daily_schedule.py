"""验证 App 评分映射、按日 FSRS 调度与旧状态重建。"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fsrs import Rating  # noqa: E402

from core.tools.study.english.fsrs_scheduler import (  # noqa: E402
    FSRS_SCHEMA_VERSION,
    LEGACY_RATING_CUTOFF,
    create_daily_scheduler,
    historical_quality_to_rating,
    legacy_quality_to_rating,
    quality_to_rating,
    rebuild_fsrs_card_from_history,
    save_fsrs_to_progress,
)


def main() -> int:
    # 当前 App 契约（cutoff 之后生效）
    assert quality_to_rating(0) == Rating.Again
    assert quality_to_rating(1) == Rating.Again
    assert quality_to_rating(2) == Rating.Hard
    assert quality_to_rating(3) == Rating.Good
    assert quality_to_rating(4) == Rating.Easy
    assert quality_to_rating(5) == Rating.Easy

    # 旧 0-5 语义只用于 cutoff 之前的历史事件
    assert legacy_quality_to_rating(1) == Rating.Again
    assert legacy_quality_to_rating(2) == Rating.Again
    assert legacy_quality_to_rating(3) == Rating.Hard
    assert legacy_quality_to_rating(4) == Rating.Good
    assert legacy_quality_to_rating(5) == Rating.Easy
    assert historical_quality_to_rating(4, LEGACY_RATING_CUTOFF - 1) == Rating.Good
    assert historical_quality_to_rating(4, LEGACY_RATING_CUTOFF) == Rating.Easy

    reviewed_at = datetime(2026, 8, 31, 10, tzinfo=timezone.utc)
    expected_min_days = {
        Rating.Again: 1,
        Rating.Hard: 1,
        Rating.Good: 2,
        Rating.Easy: 7,
    }
    scheduler = create_daily_scheduler()
    for rating, minimum_days in expected_min_days.items():
        from fsrs import Card

        card, _ = scheduler.review_card(
            Card(), rating, review_datetime=reviewed_at
        )
        interval_days = (card.due - reviewed_at).total_seconds() / 86400
        assert interval_days >= minimum_days, (rating, interval_days)
        assert card.step is None

    # cutoff 之前的历史：quality=4 是 Good，不是 Easy
    old_data = {
        "history": [
            {"timestamp": reviewed_at.timestamp(), "quality": 4},
        ],
        "fsrs_due": reviewed_at.timestamp() + 600,
    }
    rebuilt = rebuild_fsrs_card_from_history(old_data)
    legacy_days = (rebuilt.due.timestamp() - reviewed_at.timestamp()) / 86400
    assert 1 <= legacy_days < 7, legacy_days

    # cutoff 之后的评分：quality=4 才是 Easy
    new_data = {
        "history": [
            {"timestamp": LEGACY_RATING_CUTOFF + 86400, "quality": 4},
        ],
    }
    rebuilt_new = rebuild_fsrs_card_from_history(new_data)
    assert (
        rebuilt_new.due.timestamp() - (LEGACY_RATING_CUTOFF + 86400)
    ) / 86400 >= 7

    save_fsrs_to_progress(old_data, rebuilt)
    assert old_data["fsrs_schema_version"] == FSRS_SCHEMA_VERSION
    assert old_data["fsrs_step"] is None

    print("通过: App 1-4 评分与 FSRS Rating 一致")
    print("通过: 旧历史事件按旧语义解释，不会把 Good 放大成 Easy")
    print("通过: 每日队列不再产生分钟级隔日重复")
    print(f"通过: 旧评分历史可重建为 FSRS v{FSRS_SCHEMA_VERSION} 状态")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
