# -*- coding: utf-8 -*-
"""专注番茄钟阶段3/4/5 验证：

阶段3（严格模式 + 低频视觉复核）：
- strict 模式下，持续分心达到阈值且信号可靠、冷却已过 → 策略建议 vision_review
- 非 strict / 信号缺失 / 冷却中 / 专注不足 → 不触发
- request_vision_review 只记录结构化结论文本，绝不保存任何图像/帧

阶段5（AI 只读工具）：
- get_current_focus_session 已统一 current/recent/session 三种查询
- 旧 get_focus_session_summary 仅保留禁用兼容壳，不再向模型暴露第二个近义工具
- 当前会话返回实时 effective_minutes / remaining_seconds，而非只看已结算秒数
- 返回体中不含任何图像/媒体字段（base64/frame/image 等）
- 工具不参与开启摄像头监控

阶段4 为 Android 端（Kotlin），此处仅做后端契约自检（Endpoint 路径存在、仓库方法签名可达），
实际编译交由用户在 Android Studio 执行。

用法（项目根目录）：
    .\venv_core\Scripts\python.exe tests\scripts\study\verify_focus_phases_345.py
"""
import asyncio
import json
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

    cur.vision_review_last_at = time.time()
    dec2 = svc.policy.evaluate_strict_vision_review(cur)
    if dec2.should_nudge:
        fail(problems, f"冷却期内不应再次建议: reason={dec2.reason}")
    else:
        ok("冷却期内不再建议 vision_review")

    sess.mode = "gentle"
    dec3 = svc.policy.evaluate_strict_vision_review(sess)
    if dec3.should_nudge:
        fail(problems, "gentle 模式不应触发视觉复核")
    else:
        ok("gentle 模式不触发视觉复核")

    sess.mode = "strict"
    sess.monitoring = False
    dec4 = svc.policy.evaluate_strict_vision_review(sess)
    if dec4.should_nudge:
        fail(problems, "无摄像头监控不应触发视觉复核")
    else:
        ok("无摄像头监控不触发视觉复核")

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
    dumped = cur_after.to_dict()
    leak = [k for k in IMAGE_LEAK_KEYS if k in dumped]
    if leak:
        fail(problems, f"会话序列化意外含图像字段: {leak}")
    else:
        ok("会话序列化不含任何图像字段")

    svc.finish(UID, self_rating=3, note="阶段3验证")

    # ============ 阶段5：AI 统一只读工具 ============
    print("\n--- 阶段5：AI 统一只读工具 ---")
    svc2 = FocusSessionService()

    # 工具使用模块级单例；测试显式替换为本轮 service，避免跨实例缓存干扰。
    import core.services.study.focus_session_service as focus_service_module
    focus_service_module._service = svc2

    finished_seed = svc2.start_session(
        UID, "AI工具测试", planned_minutes=25, mode="gentle", monitoring=True
    )
    svc2.record_observations(UID, [
        build_obs(1, activity="focused"),
        build_obs(2, activity="possibly_distracted"),
    ])
    svc2.finish(UID, self_rating=5, note="ai工具验证")

    from core.tools.focus_session_tool import GetFocusSessionTool

    tool = GetFocusSessionTool()

    cur_out = asyncio.run(tool._run(user_id=UID, scope="current"))
    if "没有" not in cur_out:
        fail(problems, f"应返回无进行中会话: {cur_out}")
    else:
        ok("统一工具 current：无会话时正确提示")

    # 重新开始会话，并人为把 last_resume_at 前移 120s，验证实时有效时长会算 active 段。
    live = svc2.start_session(
        UID, "AI聚合测试", planned_minutes=25, mode="gentle", monitoring=False
    )
    live.last_resume_at = time.time() - 120
    svc2._persist(live)
    cur_out2 = asyncio.run(tool._run(user_id=UID, scope="current"))
    if any(k in cur_out2 for k in IMAGE_LEAK_KEYS):
        fail(problems, f"当前会话工具返回含图像字段: {cur_out2}")
    else:
        ok("统一工具 current 返回聚合态且不含图像字段")
    try:
        cur_data = json.loads(cur_out2)
        if float(cur_data.get("effective_minutes", 0.0)) < 1.5:
            fail(problems, f"当前 active 段未计入实时有效时长: {cur_data}")
        else:
            ok("统一工具 current 会计算未结算的 active 实时时长")
    except Exception as exc:
        fail(problems, f"current 输出不是合法 JSON: {exc}: {cur_out2}")

    svc2.finish(UID, self_rating=4, note="收尾")

    session_out = asyncio.run(
        tool._run(user_id=UID, scope="session", session_id=finished_seed.session_id)
    )
    if any(k in session_out for k in IMAGE_LEAK_KEYS):
        fail(problems, f"指定会话查询返回含图像字段: {session_out}")
    elif "focus_rate" not in session_out:
        fail(problems, f"指定会话查询缺少专注率字段: {session_out}")
    else:
        ok("统一工具 session 返回总结与专注率聚合字段")

    recent_out = asyncio.run(tool._run(user_id=UID, scope="recent", limit=2))
    try:
        recent_data = json.loads(recent_out)
        if not isinstance(recent_data, list) or not recent_data:
            fail(problems, f"recent 应返回非空列表: {recent_out}")
        else:
            ok("统一工具 recent 可返回最近历史会话")
    except Exception as exc:
        fail(problems, f"recent 输出不是合法 JSON: {exc}: {recent_out}")

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

    # 工具注册检查：统一工具启用，旧 summary 名只保留禁用兼容壳。
    from core.tools.registry import register_all_tools, ToolRegistry
    registry = ToolRegistry()
    register_all_tools(registry)
    if not registry.is_enabled("get_current_focus_session"):
        fail(problems, "统一专注查询工具 get_current_focus_session 未启用")
    elif "get_focus_session_summary" not in registry._tools:
        fail(problems, "旧 summary 兼容注册项缺失")
    elif registry.is_enabled("get_focus_session_summary"):
        fail(problems, "旧 get_focus_session_summary 不应继续向模型暴露")
    else:
        ok("AI 专注查询已合并：统一工具启用，旧 summary 兼容壳禁用")

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
