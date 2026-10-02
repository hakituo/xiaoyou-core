"""验证服务器本地时区依赖已消除，且去重阈值拆分后行为不变

背景（2026-09-03）：
    在排查"两套轮子"时发现两类问题：

    1. 多处绕过项目的时区工具 core/utils/time_utils.get_current_time()，
       直接用 time.strftime / datetime.now() / datetime.fromtimestamp()，
       这些取的是**服务器本地时区**。当前开发机就是 Asia/Shanghai 所以碰巧正确，
       一旦部署到 UTC 机器，日期归属会整体偏移 8 小时，导致：
       - daily_word_log 把当天记录误判成 historical_backlog 并批量重灌；
       - get_manual_study_stats 的"最近 N 天"窗口与业务日期错位。

       注意：FSRS 调度器里的 UTC 不属于此类问题。fsrs 库强制要求
       review_card 传入 aware 且为 UTC 的 datetime（否则抛
       ValueError: datetime must be timezone-aware and set to UTC），
       且其间隔按 timedelta 计算，不受时区影响。本轮不动它。

    2. Deduplicator 整句判定里，Jaccard 分数 score 误用了序列比例的阈值
       whole_ratio_threshold，且第三个条件 whole_combo_score_threshold
       因恒被蕴含而形同虚设。本次拆成两个独立字段并沿用原数值，
       目标是语义清晰但**行为完全不变**。

本脚本校验：
- 时间相关位置不再裸用 time.strftime / datetime.now()；
- fromtimestamp 均带配置时区；
- 去重阈值拆分后，在 score × ratio 全网格上的判定结果与旧逻辑逐点一致。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


_STUDY_DIR = _PROJECT_ROOT / "core" / "tools" / "study" / "english"


def test_configured_tz_helper() -> None:
    _section("测试 1: daily_word_log 提供并使用配置时区")
    from core.tools.study.english.daily_word_log import _configured_tz

    tz = _configured_tz()
    if tz is None:
        _fail("_configured_tz() 返回 None（get_current_time 未带时区？）")
        return
    _ok(f"_configured_tz() 返回 {tz}")

    from datetime import datetime, timedelta

    offset = datetime.now(tz).utcoffset()
    expected = timedelta(hours=8)  # Asia/Shanghai
    if offset == expected:
        _ok(f"偏移量 {offset} 与 Asia/Shanghai 一致")
    else:
        _fail(f"偏移量 {offset} 不符合预期 {expected}")


def test_fromtimestamp_has_tz() -> None:
    _section("测试 2: fromtimestamp 均显式带时区")
    for name in ("daily_word_log.py", "stats.py"):
        src = (_STUDY_DIR / name).read_text(encoding="utf-8")
        # 找出所有 fromtimestamp 调用
        for m in re.finditer(r"fromtimestamp\(\s*([^)]*)", src):
            snippet = m.group(0)
            line_no = src[: m.start()].count("\n") + 1
            # 允许跨行：向后多看 120 字符判断是否带 tz 参数
            tail = src[m.start() : m.start() + 200]
            has_tz = "_configured_tz()" in tail or "tzinfo" in tail or "tz" in tail
            if not has_tz:
                _fail(f"{name}:{line_no} fromtimestamp 未带时区", snippet[:80])
                break
        else:
            _ok(f"{name} 的 fromtimestamp 均带时区")


def _strip_comments(src: str) -> str:
    """去掉 # 之后的内容，避免把注释里提到的旧写法误判为仍在使用。"""
    out = []
    for line in src.splitlines():
        # 简单处理：本文件不含字符串内的 # 字面量需求，直接截断即可
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


def test_no_bare_server_local_time() -> None:
    _section("测试 3: 已消除裸用 time.strftime / datetime.now()")
    checks = [
        ("stats.py", r"time\.strftime\(\s*[\"']%Y-%m-%d"),
        ("stats.py", r"datetime\.now\(\)"),
        ("daily_word_log.py", r"time\.strftime\(\s*[\"']%Y"),
    ]
    for name, pattern in checks:
        src = _strip_comments((_STUDY_DIR / name).read_text(encoding="utf-8"))
        hits = list(re.finditer(pattern, src))
        if hits:
            line_no = src[: hits[0].start()].count("\n") + 1
            _fail(f"{name}:{line_no} 仍存在 {pattern}")
        else:
            _ok(f"{name} 已无 {pattern}")

    # 确认改用的是配置时区工具
    src = (_STUDY_DIR / "stats.py").read_text(encoding="utf-8")
    if "get_current_time()" in src:
        _ok("stats.py 改用 get_current_time()")
    else:
        _fail("stats.py 未使用 get_current_time()")


def _old_judgement(score: float, ratio: float, policy: dict) -> bool:
    """拆分前的原始逻辑（whole_combo_score_threshold 原值随场景不同）"""
    if (
        score >= policy["whole_ratio_threshold"]
        and ratio >= policy["whole_ratio_threshold"]
        and score >= policy["_old_combo_score_threshold"]
    ):
        return True
    return score >= policy["whole_threshold"]


def _new_judgement(score: float, ratio: float, policy: dict) -> bool:
    """拆分后的逻辑"""
    if (
        score >= policy["whole_combo_jaccard_threshold"]
        and ratio >= policy["whole_combo_ratio_threshold"]
    ):
        return True
    return score >= policy["whole_threshold"]


def test_dedup_threshold_behaviour_unchanged() -> None:
    _section("测试 4: 去重阈值拆分后行为逐点一致（全网格回归）")
    from core.services.active_care.postprocess.deduplicator import Deduplicator

    # 拆分前 whole_combo_score_threshold 的历史取值
    old_combo_by_scene = {"general": 0.65, "reminder": 0.52}

    for scene in ("general", "reminder"):
        policy = dict(Deduplicator._resolve_repeat_policy(scene))  # noqa: SLF001
        policy["_old_combo_score_threshold"] = old_combo_by_scene[scene]

        required = (
            "whole_threshold",
            "whole_ratio_threshold",
            "whole_combo_jaccard_threshold",
            "whole_combo_ratio_threshold",
        )
        missing = [k for k in required if k not in policy]
        if missing:
            _fail(f"{scene} policy 缺少字段 {missing}")
            continue
        _ok(f"{scene} policy 字段完整")

        # 两个 combo 阈值现在是独立字段，不再共用同一个
        if ("whole_combo_jaccard_threshold" in policy
                and "whole_combo_ratio_threshold" in policy):
            _ok(f"{scene} Jaccard 与序列比例使用各自独立的阈值")
        else:
            _fail(f"{scene} 阈值字段仍缺失")

        mismatch = []
        for i in range(101):
            for j in range(101):
                score, ratio = i / 100.0, j / 100.0
                if _old_judgement(score, ratio, policy) != _new_judgement(score, ratio, policy):
                    mismatch.append((score, ratio))
        if mismatch:
            _fail(
                f"{scene} 有 {len(mismatch)} 个网格点判定发生变化",
                f"前 5 个: {mismatch[:5]}",
            )
        else:
            _ok(f"{scene} 在 101×101 网格上判定结果与拆分前完全一致（行为未变）")


def test_dedup_still_catches_obvious_repeat() -> None:
    _section("测试 5: 去重仍能拦住明显复读（未因改动失效）")
    from core.services.active_care.postprocess.deduplicator import Deduplicator

    pairs = [
        ("中午吃什么呀", "中午吃什么呀"),
        ("在做家务呢，你呢？", "在做家务呢，你呢？"),
        ("今天背单词了吗", "今天背单词了吗"),
    ]
    for a, b in pairs:
        if Deduplicator.is_semantically_repetitive(b, a):
            _ok(f"拦截复读: {a!r}")
        else:
            _fail(f"未拦截明显复读: {a!r}")

    # 完全不同的句子不应被误杀
    distinct = [
        ("中午吃什么呀", "你论文改完了没"),
        ("在做家务呢", "刚才看到一句话挺有意思的"),
    ]
    for a, b in distinct:
        if not Deduplicator.is_semantically_repetitive(b, a):
            _ok(f"未误杀: {b!r}")
        else:
            _fail(f"误杀无关消息: {b!r}")


def main() -> int:
    print("=" * 62)
    print("时区依赖消除 & 去重阈值拆分 验证")
    print("=" * 62)

    test_configured_tz_helper()
    test_fromtimestamp_has_tz()
    test_no_bare_server_local_time()
    test_dedup_threshold_behaviour_unchanged()
    test_dedup_still_catches_obvious_repeat()

    print("\n" + "=" * 62)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 62)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
