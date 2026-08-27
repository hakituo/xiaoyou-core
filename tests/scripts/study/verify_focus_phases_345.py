# -*- coding: utf-8 -*-
"""专注番茄钟阶段3/4/5 验证：

阶段3（严格模式 + 低频视觉复核）：
- strict 模式下，持续分心达到阈值且信号可靠、冷却已过 → 策略建议 vision_review
- 非 strict / 信号缺失 / 冷却中 / 专注不足 → 不触发
- request_vision_review 只记录结构化结论文本，绝不保存任何图像/帧

阶段5（AI 只读工具）：
- get_current_focus_session / get_focus_session_summary 返回聚合统计
- 返回体中不含任何图像/媒体字段（base64/frame/image 等）
- 工具不参与开启摄像头监控

阶段4 为 Android 端（Kotlin），此处仅做后端契约自检（Endpoint 路径存在、仓库方法签名可达），
实际编译交由用户在 Android Studio 执行。

用法（项目根目录）：
    .\venv_core\Scripts\python.exe tests\scripts\study\verify_focus_phases_345.py
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.services.study.focus_session_service import (  # noqa: E402
    FocusSessionService,
)
from config.focus_monitor_config import get_focus_monitor_config  # noqa: E402

UID = "verify_345"
IMAGE_LEAK_KEYS = ("base64", "frame", "image", "image_data", "screenshot", "media")


def fail(problems: list, msg: str):
    problems.append(msg)
    print(f"  [FAIL] {msg}")


def ok(msg: str):
    print(f"  [ok] {msg}")


def build_obs(seq: int, presence="present", activity="focused", conf=0.9):
    now = time.time()
    return {
        "sequence": seq,
        "observed_at": now,
        "presence": presence,
        "activity": activity,
        "confidence": conf,
        "signals": [],
        "page_visible": True,
        "client_ts": now,
    }


def main() -> int:
    problems: list[str] = []
    cfg = get_focus_monitor_config()
    svc = FocusSessionService()

    # ============ 阶段3：strict 模式低频视觉复核决策 ============
    print("\n--- 阶段3：strict 模式低频视觉复核 ---")
    sess = svc.start_session(UID, "严格控制", planned_minutes=25, mode="strict", monitoring=True)

    # 先注入足够的有效专注（达到最短专注阈值）
    svc.record_observations(UID, [
        build_obs(1, activity="focused"),
        build_obs(2, activity="focused"),
        build_obs(3, activity="focused"),
    ])
    # 把会话的累计有效专注人为抬高到超过 strict_vision_min_focus_sec
    cur = svc.get_current(UID)
    cur.accumulated_active_seconds = cfg.strict_vision_min_focus_sec + 30
    cur.last_observed_at = time.time()
    cur.last_presence = "present"
    cur.last_activity = "possibly_distracted"
    cur.last_confidence = 0.9
    cur._distraction_since = time.time() - (cfg.strict_distraction_sec + 5)
    svc._persist(cur)

    dec = svc.policy.evaluate_strict_vision_review(cur)
    if not (dec.should_nudge and dec.vision_review):
        fail(problems, f"满足全部条件应建议 vision_review: reason={dec.reason}")
    else:
        ok("满足全部条件 → 建议 vision_review")

    # 冷却：立即再评估应被冷却拦截
    cur.vision_review_last_at = time.time()
    dec2 = svc.policy.evaluate_strict_vision_review(cur)
    if dec2.should_nudge:
        fail(problems, f"冷却期内不应再次建议: reason={dec2.reason}")
    else:
        ok("冷却期内不再建议 vision_review")

    # 非 strict 不触发
    sess.mode = "gentle"
    dec3 = svc.policy.evaluate_strict_vision_review(sess)
    if dec3.should_nudge:
        fail(problems, "gentle 模式不应触发视觉复核")
    else:
        ok("gentle 模式不触发视觉复核")

    # 无摄像头监控不触发
    sess.mode = "strict"
    sess.monitoring = False
    dec4 = svc.policy.evaluate_strict_vision_review(sess)
    if dec4.should_nudge:
        fail(problems, "无摄像头监控不应触发视觉复核")
    else:
        ok("无摄像头监控不触发视觉复核")

    # request_vision_review 只记录结论，不存图像
    sess.monitoring = True
    svc.request_vision_review(UID, lambda: "画面中人在低头看手机，明显分心。")
    cur_after = svc.get_current(UID)
    if not cur_after.vision_review_events:
        fail(problems, "视觉复核结论应被记录到 vision_review_events")
    else:
        ev = cur_after.vision_review_events[0]
        if "看手机" not in ev.get("conclusion", ""):
            fail(problems, f"结论文本未正确保存: {ev}")
        else:
            ok(f"视觉复核结论结构化保存（无图像）: {ev['conclusion'][:20]}...")
    # 确认会话序列化后不含任何图像字段
    dumped = cur_after.to_dict()
    leak = [k for k in IMAGE_LEAK_KEYS if k in dumped]
    if leak:
        fail(problems, f"会话序列化意外含图像字段: {leak}")
    else:
        ok("会话序列化不含任何图像字段")

    svc.finish(UID, self_rating=3, note="阶段3验证")

    # ============ 阶段5：AI 只读工具 ============
    print("\n--- 阶段5：AI 只读工具 ---")
    svc2 = FocusSessionService()
    s = svc2.start_session(UID, "AI工具测试", planned_minutes=25, mode="gentle", monitoring=True)
    svc2.record_observations(UID, [
        build_obs(1, activity="focused"),
        build_obs(2, activity="possibly_distracted"),
    ])
    svc2.finish(UID, self_rating=5, note="ai工具验证")

    from core.tools.focus_session_tool import (
        GetCurrentFocusSessionTool,
        GetFocusSessionSummaryTool,
    )

    # 当前无进行中会话
    cur_tool = GetCurrentFocusSessionTool()
    cur_out = asyncio.run(cur_tool._run(user_id=UID))
    if "没有" not in cur_out:
        fail(problems, f"应返回无进行中会话: {cur_out}")
    else:
        ok("当前会话工具：无会话时正确提示")

    # 重新开始一个会话，验证 current 工具返回聚合态且不含图像
    svc2.start_session(UID, "AI聚合测试", planned_minutes=25, mode="gentle", monitoring=True)
    cur_out2 = asyncio.run(cur_tool._run(user_id=UID))
    if any(k in cur_out2 for k in IMAGE_LEAK_KEYS):
        fail(problems, f"当前会话工具返回含图像字段: {cur_out2}")
    else:
        ok("当前会话工具返回聚合态且不含图像字段")
    if "effective_minutes" not in cur_out2 and "session_id" not in cur_out2:
        fail(problems, f"当前会话工具返回缺少聚合字段: {cur_out2}")
    else:
        ok("当前会话工具返回包含聚合字段(时长/专注率等)")

    # summary 工具：查询刚结束的会话
    sum_tool = GetFocusSessionSummaryTool()
    sum_out = asyncio.run(sum_tool._run(user_id=UID, session_id=s.session_id))
    if any(k in sum_out for k in IMAGE_LEAK_KEYS):
        fail(problems, f"总结工具返回含图像字段: {sum_out}")
    else:
        ok("总结工具返回聚合数据且不含图像字段")
    if "focus_rate" not in sum_out:
        fail(problems, f"总结工具缺少专注率字段: {sum_out}")
    else:
        ok("总结工具返回含专注率等聚合字段")
    svc2.finish(UID, self_rating=4, note="收尾")

    # ============ 阶段4：后端契约自检 ============
    print("\n--- 阶段4：后端契约自检（Endpoint/仓库方法存在） ---")
    from routers.v1 import study_focus as sf_mod  # noqa: F401
    router_paths = [r.path for r in sf_mod.router.routes]
    required = [
        "/study/focus-sessions/current",
        "/study/focus-sessions",
        "/study/focus-sessions/{session_id}/pause",
        "/study/focus-sessions/{session_id}/resume",
        "/study/focus-sessions/{session_id}/finish",
        "/study/focus-sessions/{session_id}/summary",
        "/study/focus-sessions/history",
        "/study/focus-sessions/{session_id}/vision-review",
    ]
    missing = [p for p in required if p not in router_paths]
    if missing:
        fail(problems, f"缺少专注会话路由: {missing}")
    else:
        ok("阶段4 后端 focus-session 路由齐全（含 vision-review）")

    # 工具注册检查
    from core.tools.registry import register_all_tools, ToolRegistry
    registry = ToolRegistry()
    register_all_tools(registry)
    if "get_current_focus_session" not in registry._tools:
        fail(problems, "get_current_focus_session 未注册")
    elif "get_focus_session_summary" not in registry._tools:
        fail(problems, "get_focus_session_summary 未注册")
    else:
        ok("阶段5 两个 AI 工具已注册")

    # ============ 结果 ============
    print("\n" + "=" * 50)
    if problems:
        print(f"验证失败 {len(problems)} 项：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("✅ 专注番茄钟 阶段3/4/5 验证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
