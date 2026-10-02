# -*- coding: utf-8 -*-
"""专注番茄钟后端会话验证（阶段1 MVP）。

覆盖：
- 重复/乱序 observation 幂等（sequence 去重）
- monitoring=true 掉线自动暂停
- monitoring=false 纯计时会话不依赖观察 heartbeat
- 暂停/恢复计时累计正确
- 结束幂等 + 总结生成
- 隐私护栏：含 base64/图片字段的 observation 被拒

用法（项目根目录）：
    .\venv_core\Scripts\python.exe tests\scripts\study\verify_focus_session.py

不调用 Gradle / 不启动 FastAPI，直接单元测试 FocusSessionService。
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.services.study.focus_session_service import (  # noqa: E402
    FocusSessionService,
    FocusSessionError,
)
from config.focus_monitor_config import get_focus_monitor_config  # noqa: E402

UID = "verify_user"
TIMER_UID = "verify_timer_only_user"


def fail(problems: list, msg: str):
    problems.append(msg)
    print(f"  [FAIL] {msg}")


def ok(msg: str):
    print(f"  [ok] {msg}")


def build_obs(seq: int, observed_at_offset: float = 0.0, presence="present",
              activity="focused", conf=0.9, signals=None, page_visible=True):
    now = time.time()
    return {
        "sequence": seq,
        "observed_at": now + observed_at_offset,
        "presence": presence,
        "activity": activity,
        "confidence": conf,
        "signals": signals or [],
        "page_visible": page_visible,
        "client_ts": now + observed_at_offset,
    }


def main() -> int:
    problems: list[str] = []
    cfg = get_focus_monitor_config()
    svc = FocusSessionService()

    # 1) 开始有监控会话
    sess = svc.start_session(UID, "验证任务", planned_minutes=25, mode="gentle", monitoring=True)
    sid = sess.session_id
    ok(f"会话开始: {sid}")

    # 新会话必须从 started_at 开始计算 heartbeat 宽限期，不能因为 last_observed_at=0 立刻掉线。
    if sess.last_observed_at <= 0 or abs(sess.last_observed_at - sess.started_at) > 1.0:
        fail(problems, "monitoring 会话开始时应初始化 last_observed_at")
    else:
        ok("monitoring 会话从开始时刻计算 heartbeat 宽限期")

    # 2) 批量 observation：正常序列 1,2,3
    r1 = svc.record_observations(UID, [build_obs(1), build_obs(2), build_obs(3)])
    if r1["accepted"] != 3 or r1["ignored"] != 0:
        fail(problems, f"正常观察应全部接受: {r1}")
    else:
        ok("正常序列1-3 接受=3")

    # 3) 幂等：重复 sequence 1,2 应被忽略
    r2 = svc.record_observations(UID, [build_obs(1), build_obs(2)])
    if r2["ignored"] != 2 or r2["accepted"] != 0:
        fail(problems, f"重复序列应忽略: {r2}")
    else:
        ok("重复 sequence 幂等忽略=2")

    # 4) 乱序：先到 6 再到 4,5（4,5 也应接受，不依赖顺序）
    r3 = svc.record_observations(UID, [build_obs(6), build_obs(4), build_obs(5)])
    if r3["accepted"] != 3:
        fail(problems, f"乱序应全部接受: {r3}")
    else:
        ok("乱序 4,5,6 接受=3")

    # 5) 隐私护栏：含 base64 / image 字段应被丢弃（不抛错，批量上报更健壮）
    bad = dict(build_obs(7))
    bad["base64"] = "data:image/png;base64,AAAA"
    rp = svc.record_observations(UID, [bad])
    if rp["dropped"] != 1:
        fail(problems, f"含 base64 字段的 observation 应被丢弃: {rp}")
    else:
        ok("含 base64 字段被丢弃（隐私护栏）")

    # 6) 暂停 / 恢复：active 秒数只在 pause/finish 时结算进 accumulated。
    svc.pause(UID, "user")
    svc.resume(UID)
    before = svc.get_current(UID).accumulated_active_seconds
    time.sleep(0.3)
    after = svc.get_current(UID).accumulated_active_seconds
    if after - before >= 0.1:
        fail(problems, f"未结算 active 段不应直接写 accumulated: before={before} after={after}")
    else:
        ok("暂停/恢复累计字段正确（实时段由 effective_elapsed 计算）")

    # 7) monitoring=true 掉线自动暂停：把 last_observed_at 设为很久以前再检测
    cur = svc.get_current(UID)
    cur.last_observed_at = time.time() - (cfg.offline_grace_sec + 10)
    svc._persist(cur)
    result = svc.check_offline_and_pause(UID)
    if result != "auto_paused_offline" or svc.get_current(UID).status != "paused":
        fail(problems, f"监控会话掉线应自动暂停: result={result}")
    else:
        ok("monitoring=true 掉线自动暂停生效")
    svc.resume(UID)

    # 8) monitoring=false 是纯计时客户端（Android 番茄钟）：绝不能因为没有 observation 被暂停。
    timer_svc = FocusSessionService()
    timer_sess = timer_svc.start_session(
        TIMER_UID, "Android纯计时", planned_minutes=25, mode="gentle", monitoring=False
    )
    timer_sess.last_observed_at = time.time() - (cfg.offline_grace_sec + 3600)
    timer_svc._persist(timer_sess)
    timer_result = timer_svc.check_offline_and_pause(TIMER_UID)
    if timer_result is not None or timer_svc.get_current(TIMER_UID).status != "active":
        fail(problems, f"纯计时会话不应依赖 observation 自动暂停: result={timer_result}")
    else:
        ok("monitoring=false 纯计时会话不受 heartbeat 掉线策略影响")
    if not timer_svc.has_active_session(TIMER_UID):
        fail(problems, "has_active_session 应识别 active 纯计时会话")
    else:
        ok("has_active_session 可作为其它子系统的正式学习事实门控")
    timer_svc.pause(TIMER_UID)
    if not timer_svc.has_active_session(TIMER_UID, include_paused=True):
        fail(problems, "paused FocusSession 仍应被视为正式学习执行态")
    else:
        ok("paused FocusSession 仍属于正式学习执行态")
    timer_svc.finish(TIMER_UID, note="纯计时验证结束")

    # 9) 结束 + 总结 + 有效专注同步
    finished = svc.finish(UID, self_rating=4, note="验证结束")
    if finished.status != "finished":
        fail(problems, "结束状态应为 finished")
    elif not finished.summary_text:
        fail(problems, "结束应生成自然语言总结")
    else:
        ok(f"结束生成总结: {finished.summary_text[:40]}...")

    # 10) 结束幂等：无活动会话时再 finish 应报错（不是二次结算）
    try:
        svc.finish(UID)
        fail(problems, "已结束会话不应重复结束（幂等）")
    except FocusSessionError:
        ok("结束幂等：重复结束被拒")

    # 11) 历史可查
    hist = svc.get_history(UID, limit=5)
    if not any(h["session_id"] == sid for h in hist):
        fail(problems, "历史中应包含刚结束的会话")
    else:
        ok("历史包含已结束会话")

    # 12) 跨天目录：存储路径按 YYYY/MM/DD
    from core.services.study.focus_session_models import FocusSession
    probe = FocusSession(session_id="p", user_id=UID, subject="", planned_minutes=1)
    sdir = probe.storage_dir().replace("\\", "/")
    parts = sdir.split("/")
    ok_year = parts[-4] == "focus_sessions" and len(parts[-3]) == 4
    ok_month = parts[-2].isdigit() and 1 <= int(parts[-2]) <= 12
    ok_day = parts[-1].isdigit() and 1 <= int(parts[-1]) <= 31
    if ok_year and ok_month and ok_day:
        ok(f"存储目录按 YYYY/MM/DD: .../{parts[-3]}/{parts[-2]}/{parts[-1]}")
    else:
        fail(problems, f"存储目录格式不符: {sdir}")

    print("\n" + "=" * 50)
    if problems:
        print(f"验证失败 {len(problems)} 项：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("✅ 专注番茄钟后端验证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
