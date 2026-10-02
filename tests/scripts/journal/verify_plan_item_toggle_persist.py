"""验证安卓端勾选计划项后不再被后端计划同步覆盖。

背景（2026-09-11）：
    用户反馈"安卓端 study 模块里面的计划，勾了他不会持久化，换个页面回去
    又没被勾上"。核查当天的两个文件：

        D:\\AI\\Study\\Daily\\2026\\09\\11\\plan.md   3 条，全部 "- [x]"
        companion_data/user_data/daily/2026/09/11/plan.json
                                                     4 条，全部 status=pending

    plan.md 是投影，plan.json 才是真源，而安卓端勾选只整篇覆盖 plan.md。
    后端当天 12:01:22 与 18:00:09 两次执行检查点重排，日志都打印
    "计划已同步到 Study Daily"，每次都用真源重新生成 plan.md，
    把用户手动勾上的状态整片抹回未勾选。

修复：
    1. 新增计划项真源接口组（``plan/item/status|add|update|remove``），勾选 / 新增 /
       编辑 / 删除统一走 JournalService 写回真源，由真源派生 plan.md；
    2. 安卓端四条链路全部改调这组接口，整篇覆盖 plan.md 的旧路径整体下线；
    3. 顺带修 ``_mark_vocab_plan_completed_if_done`` 的日期语义——它此前用
       ``mark_plan_item_status(None, ...)``，而 True 分支会落到"明日"，
       与 ``get_plan(None)``（今日）不一致，导致"背完单词自动勾选"静默失效；
    4. 顺带按 life.py 的先例把 824 行的 study_daily.py 拆成
       shared / content / notes / plan + 聚合入口。

本脚本固化：名称匹配规则、勾选与增删改确实落真源且带显式日期、后续同步不再
覆盖、"背完自动勾选"用的是今日、安卓侧接线未被改回整篇覆盖，以及拆分后
study-daily 的路由集合与拆分前完全一致。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0

_ANDROID_APP = _PROJECT_ROOT / "clients/frontend/aveline-android/android/app"
_ANDROID_SRC = _ANDROID_APP / "src/main/java/com/aveline/ai/mobile"
_ANDROID_TEST = _ANDROID_APP / "src/test/java/com/aveline/ai/mobile"

# 拆分后 study-daily 必须仍注册出这组路由（路径与拆分前完全一致）
_EXPECTED_STUDY_DAILY_ROUTES = {
    ("GET", "/study-daily/calendar"),
    ("GET", "/study-daily/date/{date}"),
    ("GET", "/study-daily/latest-progress"),
    ("GET", "/study-daily/notes"),
    ("GET", "/study-daily/notes/{filename}"),
    ("GET", "/study-daily/library"),
    ("GET", "/study-daily/library/note"),
    ("POST", "/study-daily/plan/item/status"),
    ("POST", "/study-daily/plan/item/add"),
    ("POST", "/study-daily/plan/item/update"),
    ("POST", "/study-daily/plan/item/remove"),
}


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


@contextmanager
def _patched(target, name: str, value):
    """临时替换目标属性，退出时还原"""
    old = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, old)


class _FakeJournal:
    """只记录调用的假 JournalService"""

    def __init__(self, plan):
        self.plan = plan
        self.mark_calls = []

    async def get_plan(self, date=None):
        self.get_plan_date = date
        return self.plan

    async def mark_plan_item_status(self, date, item_id, status):
        self.mark_calls.append((date, item_id, status))
        return SimpleNamespace(id=item_id, status=status)


async def _fake_read_text(_path):
    return "- [x] 19:00 核心学习块\n"


async def _call_endpoint(journal, *, date, time, title, done):
    """直接调用端点函数（不经 HTTP），只关心写入语义"""
    from routers.v1 import study_daily_plan as mod

    with (
        _patched(
            sys.modules["core.services.journal.service"],
            "get_journal_service",
            lambda: journal,
        ),
        _patched(mod, "_plan_file_path", lambda *_: Path("plan.md")),
        _patched(mod, "_read_text_async", _fake_read_text),
    ):
        return await mod.update_plan_item_status(
            mod.PlanItemStatusRequest(date=date, time=time, title=title, done=done)
        )


def test_title_normalization_and_matching() -> None:
    _section("测试 1: 客户端名称漂移后仍能命中真源计划项")
    from routers.v1.study_daily_plan import (  # noqa: F401
        PlanItemStatusRequest,
        _normalize_plan_title,
    )

    from core.services.journal.models import DailyPlan, PlanItem

    item = PlanItem(id="p_vocab", time="21:10", title="复习到期英语词汇（123 个）")
    plan = DailyPlan(date="2026-09-11", items=[item])

    # 真源标题 / 安卓回写（带时长）/ 后端同步（带 ✅）/ 短名称（安卓把括号当时长剥掉）
    forms = (
        ("复习到期英语词汇（123 个）", "21:10"),
        ("复习到期英语词汇（123 个） （60分钟）", "21:10"),
        ("复习到期英语词汇（123 个）（60分钟） ✅", "21:10"),
    )
    for form, time in forms:
        journal = _FakeJournal(plan)
        resp = asyncio.run(
            _call_endpoint(
                journal,
                date="2026-09-11",
                time=time,
                title=form,
                done=True,
            )
        )
        if resp["status"] == "success" and journal.mark_calls == [
            ("2026-09-11", "p_vocab", "completed")
        ]:
            _ok(f"命中并写真源: {form!r}")
        else:
            _fail(f"未能命中: {form!r}", f"resp={resp} calls={journal.mark_calls}")

    # 安卓把行尾括号当 duration 剥掉后名称变短
    math_item = PlanItem(id="p_math", time="09:00", title="复习数学（第1章）")
    journal = _FakeJournal(DailyPlan(date="2026-09-11", items=[math_item]))
    resp = asyncio.run(
        _call_endpoint(
            journal, date="2026-09-11", time="09:00", title="复习数学", done=True
        )
    )
    if resp["status"] == "success" and journal.mark_calls:
        _ok("客户端名称比真源短（复习数学 ← 复习数学（第1章））也能命中")
    else:
        _fail("短名称未命中", f"resp={resp}")

    if _normalize_plan_title(" 复习数学 ✅ ") == "复习数学":
        _ok("归一化会剥掉行尾状态标记与空白")
    else:
        _fail("归一化结果异常", _normalize_plan_title(" 复习数学 ✅ "))


def test_toggle_writes_truth_source() -> None:
    _section("测试 2: 勾选/取消勾选都写回真源，且日期显式")
    from core.services.journal.models import DailyPlan, PlanItem

    plan = DailyPlan(
        date="2026-09-11",
        items=[PlanItem(id="p_core", time="19:00", title="核心学习块")],
    )

    journal = _FakeJournal(plan)
    resp = asyncio.run(
        _call_endpoint(
            journal, date="2026-09-11", time="19:00", title="核心学习块", done=True
        )
    )
    if journal.mark_calls == [("2026-09-11", "p_core", "completed")]:
        _ok("勾选写入 (日期, item_id, completed)，日期是显式的 2026-09-11")
    else:
        _fail("勾选写入异常", str(journal.mark_calls))
    if resp.get("data", {}).get("plan"):
        _ok("接口回传重新生成的 plan.md 全文")
    else:
        _fail("接口未回传 plan 全文", str(resp))

    journal = _FakeJournal(plan)
    asyncio.run(
        _call_endpoint(
            journal, date="2026-09-11", time="19:00", title="核心学习块", done=False
        )
    )
    if journal.mark_calls == [("2026-09-11", "p_core", "pending")]:
        _ok("取消勾选写回 pending")
    else:
        _fail("取消勾选写入异常", str(journal.mark_calls))


def test_ambiguous_and_missing_are_refused() -> None:
    _section("测试 3: 定位不到计划项时报错，不静默误标")
    from core.services.journal.models import DailyPlan, PlanItem

    plan = DailyPlan(
        date="2026-09-11",
        items=[
            PlanItem(id="p1", time="08:00", title="复习到期英语词汇（52 个）"),
            PlanItem(id="p2", time="21:10", title="复习到期英语词汇（52 个）"),
        ],
    )
    journal = _FakeJournal(plan)
    resp = asyncio.run(
        _call_endpoint(
            journal,
            date="2026-09-11",
            time="",
            title="复习到期英语词汇（52 个）",
            done=True,
        )
    )
    if resp["status"] == "error" and not journal.mark_calls:
        _ok("同名多条且无法按时间消歧 → 报错且不写")
    else:
        _fail("歧义项被写入", f"resp={resp} calls={journal.mark_calls}")

    journal = _FakeJournal(plan)
    resp = asyncio.run(
        _call_endpoint(
            journal, date="2026-09-11", time="21:10", title="不存在的计划项", done=True
        )
    )
    if resp["status"] == "error" and not journal.mark_calls:
        _ok("真源里没有的项 → 报错且不写")
    else:
        _fail("不存在的项被写入", f"resp={resp}")

    journal = _FakeJournal(plan)
    resp = asyncio.run(
        _call_endpoint(
            journal, date="2026/09/11", time="21:10", title="复习到期英语词汇（52 个）",
            done=True,
        )
    )
    if resp["status"] == "error" and not journal.mark_calls:
        _ok("非法日期 → 报错且不写")
    else:
        _fail("非法日期未被拦截", f"resp={resp}")


def test_truth_source_survives_resync() -> None:
    _section("测试 4: 勾选落真源后，后端再次同步 plan.md 仍保留勾选")
    from core.services.journal.models import DailyPlan, PlanItem
    from core.services.journal.service import JournalService
    import core.services.journal.plan_service as plan_service_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        service = JournalService()
        plan_date = datetime(2026, 9, 11)

        def _daily_dir(date, scope="user"):
            return (
                tmp_root
                / scope
                / "daily"
                / date.strftime("%Y")
                / date.strftime("%m")
                / date.strftime("%d")
            )

        with (
            _patched(service.storage, "get_daily_dir", _daily_dir),
            _patched(
                plan_service_mod,
                "get_study_daily_date_dir",
                lambda date: tmp_root / "daily" / date.strftime("%Y/%m/%d"),
            ),
        ):
            plan = DailyPlan(
                date="2026-09-11",
                items=[
                    PlanItem(id="p_core", time="19:00", title="核心学习块", status="pending"),
                    PlanItem(id="p_vocab", time="21:10", title="复习到期英语词汇（123 个）"),
                ],
            )
            asyncio.run(service.storage.save_plan(plan, plan_date, scope="user"))
            # 首次同步：生成 plan.md（两项都未勾选）
            asyncio.run(service._plan_service._sync_plan_to_study_daily(plan, plan_date))

            # 用户在安卓端勾上一项 → 接口写回真源
            updated = asyncio.run(
                service.mark_plan_item_status("2026-09-11", "p_core", "completed")
            )
            if updated is None:
                _fail("mark_plan_item_status 返回 None")
                return

            plan_md = tmp_root / "daily" / "2026" / "09" / "11" / "plan.md"
            first = plan_md.read_text(encoding="utf-8")
            if "- [x] 19:00 核心学习块" in first:
                _ok("勾选后 plan.md 立刻显示 [x]")
            else:
                _fail("勾选后 plan.md 未显示 [x]", first)

            # 模拟后端再次同步（检查点重排 / 睡眠结算 / 背完自动勾选都会走这里）
            reloaded = asyncio.run(service.storage.get_plan(plan_date, scope="user"))
            asyncio.run(
                service._plan_service._sync_plan_to_study_daily(reloaded, plan_date)
            )
            second = plan_md.read_text(encoding="utf-8")
            if "- [x] 19:00 核心学习块" in second:
                _ok("再次同步后 [x] 仍在（真源已持有该状态）")
            else:
                _fail("再次同步把勾选抹掉了", second)

            statuses = {it.id: it.status for it in reloaded.items}
            if statuses.get("p_core") == "completed":
                _ok("真源 plan.json 中该项为 completed")
            else:
                _fail("真源状态不是 completed", str(statuses))


def test_vocab_auto_mark_uses_today() -> None:
    _section("测试 5: 背完单词自动勾选用的是今日计划（防 None→明日回归）")
    from core.services.journal.models import DailyPlan, PlanItem
    from routers.v1 import vocab as vocab_router

    plan = DailyPlan(
        date="2026-09-11",
        items=[
            PlanItem(
                id="p_vocab",
                time="21:10",
                title="复习到期英语词汇（123 个）",
                source_key="vocab:due_review",
            )
        ],
    )
    journal = _FakeJournal(plan)
    service = SimpleNamespace(get_today_review_status=lambda: {"completed": True})

    with _patched(
        sys.modules["core.services.journal.service"],
        "get_journal_service",
        lambda: journal,
    ):
        got = asyncio.run(vocab_router._mark_vocab_plan_completed_if_done(service))

    if got and journal.mark_calls == [("2026-09-11", "p_vocab", "completed")]:
        _ok("自动勾选写入显式今日日期，而不是 None（None 会落到明日）")
    else:
        _fail("自动勾选日期语义仍有问题", f"got={got} calls={journal.mark_calls}")


def test_plan_item_crud_end_to_end() -> None:
    _section("测试 6: 增 / 改 / 删 走真源后 plan.md 立即反映，再次同步不丢")
    from core.services.journal.models import DailyPlan, PlanItem
    from core.services.journal.service import JournalService
    import core.services.journal.plan_service as plan_service_mod
    import core.services.workspace.service as workspace_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        service = JournalService()
        plan_date = datetime(2026, 9, 11)

        def _daily_dir(date, scope="user"):
            return (
                tmp_root
                / scope
                / "daily"
                / date.strftime("%Y")
                / date.strftime("%m")
                / date.strftime("%d")
            )

        plan_md = tmp_root / "daily" / "2026" / "09" / "11" / "plan.md"
        with (
            _patched(service.storage, "get_daily_dir", _daily_dir),
            _patched(
                plan_service_mod,
                "get_study_daily_date_dir",
                lambda date: tmp_root / "daily" / date.strftime("%Y/%m/%d"),
            ),
            # 计划项增删改可能创建 Workspace 提醒，这里换成无 schedule_message 的桩，
            # 避免验证脚本动到真实提醒数据
            _patched(workspace_mod, "get_workspace_service", lambda: SimpleNamespace()),
        ):
            plan = DailyPlan(
                date="2026-09-11",
                items=[PlanItem(id="p1", time="19:00", title="核心学习块")],
            )
            asyncio.run(service.storage.save_plan(plan, plan_date, scope="user"))
            asyncio.run(service._plan_service._sync_plan_to_study_daily(plan, plan_date))

            # 新增：一项带时间、一项无固定时间（灵活）
            asyncio.run(
                service.add_plan_item(
                    "2026-09-11",
                    {"time": "08:00", "title": "晨读", "estimated_duration_minutes": 30},
                )
            )
            after_add = asyncio.run(
                service.add_plan_item("2026-09-11", {"time": "", "title": "预习生物"})
            )
            text = plan_md.read_text(encoding="utf-8")
            if "08:00 晨读（30分钟）" in text and "灵活 预习生物（60分钟）" in text:
                _ok("新增项出现在 plan.md（无固定时间的项写作『灵活』）")
            else:
                _fail("新增项未出现在 plan.md", text)

            # 编辑：晨读 -> 07:30 早读 20 分钟
            target = next(i for i in after_add.items if i.title == "晨读")
            asyncio.run(
                service.update_plan_item(
                    "2026-09-11",
                    target.id,
                    {"time": "07:30", "title": "早读", "estimated_duration_minutes": 20},
                )
            )
            text = plan_md.read_text(encoding="utf-8")
            if "07:30 早读（20分钟）" in text and "晨读" not in text:
                _ok("编辑后的名称/时间/时长已反映到 plan.md")
            else:
                _fail("编辑未生效", text)

            # 删除：预习生物
            current = asyncio.run(service.get_plan("2026-09-11"))
            target = next(i for i in current.items if i.title == "预习生物")
            asyncio.run(service.remove_plan_item("2026-09-11", target.id))
            text = plan_md.read_text(encoding="utf-8")
            if "预习生物" not in text and "早读" in text:
                _ok("删除后该项从 plan.md 消失，其它项保留")
            else:
                _fail("删除未生效", text)

            # 模拟后端再次同步（12 点 / 18 点检查点重排走同一条路）
            reloaded = asyncio.run(service.get_plan("2026-09-11"))
            asyncio.run(
                service._plan_service._sync_plan_to_study_daily(reloaded, plan_date)
            )
            if plan_md.read_text(encoding="utf-8") == text:
                _ok("再次同步后增 / 改 / 删结果全部保留")
            else:
                _fail("再次同步改动了内容", plan_md.read_text(encoding="utf-8"))


def test_android_wiring() -> None:
    _section("测试 7: 安卓侧接线已全部改走计划真源")
    required = (
        (
            _ANDROID_SRC / "presentation/study/StudyPlanTab.kt",
            "onToggle = { onToggleItem(item) }",
            "计划 Tab 勾选回调指向 onToggleItem",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanTab.kt",
            "onAddItem(edited)",
            "新增走 onAddItem",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanTab.kt",
            "onUpdateItem(editingItem, edited)",
            "编辑带上编辑前的项（用于在真源中定位）",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanTab.kt",
            "onDeleteItem(editingItem)",
            "删除走 onDeleteItem",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanViewModel.kt",
            "updatePlanItemStatus",
            "ViewModel 调用勾选接口",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanViewModel.kt",
            "addPlanItem(",
            "ViewModel 调用新增接口",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanViewModel.kt",
            "updatePlanItem(",
            "ViewModel 调用编辑接口",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanViewModel.kt",
            "removePlanItem(",
            "ViewModel 调用删除接口",
        ),
        (
            _ANDROID_SRC / "data/remote/api/StudyDailyApiService.kt",
            "/api/v1/study-daily/plan/item/status",
            "API 声明勾选路由",
        ),
        (
            _ANDROID_SRC / "data/remote/api/StudyDailyApiService.kt",
            "/api/v1/study-daily/plan/item/add",
            "API 声明新增路由",
        ),
        (
            _ANDROID_SRC / "data/remote/api/StudyDailyApiService.kt",
            "/api/v1/study-daily/plan/item/update",
            "API 声明编辑路由",
        ),
        (
            _ANDROID_SRC / "data/remote/api/StudyDailyApiService.kt",
            "/api/v1/study-daily/plan/item/remove",
            "API 声明删除路由",
        ),
        (
            _ANDROID_SRC / "data/repository/StudyRepositoryImpl.kt",
            "planItemResult",
            "仓库统一判定 status=error，避免静默失败",
        ),
        (
            _ANDROID_SRC / "domain/PlanMarkdownCodec.kt",
            "flexibleTimeRegex",
            "解码器支持『灵活』无时间项",
        ),
        (
            _ANDROID_SRC / "domain/PlanMarkdownCodec.kt",
            r"trimStart('\uFEFF')",
            "解码器兼容带 BOM 的旧 plan.md",
        ),
        (
            _ANDROID_TEST / "domain/PlanMarkdownCodecTest.kt",
            "灵活表示无固定时间",
            "解码器单测覆盖『灵活』项",
        ),
    )
    for path, needle, label in required:
        if not path.exists():
            _fail(f"文件缺失: {path}")
        elif needle in path.read_text(encoding="utf-8"):
            _ok(label)
        else:
            _fail(f"{label} —— 未找到 {needle!r}", str(path))

    # 整篇覆盖 plan.md 的写路径必须已经下线，否则等于把投影当成了真源
    forbidden = (
        (
            _ANDROID_SRC / "data/remote/api/StudyDailyApiService.kt",
            "updateStudyDailyPlan",
            "整篇覆盖投影的接口已下线",
        ),
        (
            _ANDROID_SRC / "data/repository/StudyRepositoryImpl.kt",
            "updatePlan(",
            "仓库不再提供整篇写 plan.md",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyPlanViewModel.kt",
            "savePlan",
            "ViewModel 不再整篇保存计划",
        ),
        (
            _ANDROID_SRC / "presentation/study/StudyScreenV2.kt",
            "onSavePlan",
            "计划 Tab 不再暴露整篇保存回调",
        ),
        (
            _ANDROID_SRC / "domain/PlanMarkdownCodec.kt",
            "fun serialize",
            "解码器不再提供整篇序列化（避免被当写回方案复用）",
        ),
        (
            _PROJECT_ROOT / "routers/v1/study_daily.py",
            "APIRouter(prefix=",
            "聚合入口不得再声明 prefix（会叠加成 /study-daily/study-daily）",
        ),
    )
    for path, needle, label in forbidden:
        if not path.exists():
            _fail(f"文件缺失: {path}")
        elif needle in path.read_text(encoding="utf-8"):
            _fail(f"{label} —— 仍能匹配到 {needle!r}", str(path))
        else:
            _ok(label)


def test_route_registry_after_split() -> None:
    _section("测试 8: 拆分后 study-daily 路由集合与拆分前一致")
    from routers.v1.study_daily import router as study_daily_router

    actual = {
        (method, route.path)
        for route in study_daily_router.routes
        for method in (getattr(route, "methods", None) or [])
    }
    missing = sorted(_EXPECTED_STUDY_DAILY_ROUTES - actual)
    extra = sorted(actual - _EXPECTED_STUDY_DAILY_ROUTES)
    if not missing and not extra:
        _ok(f"聚合入口注册出 {len(actual)} 条 study-daily 路由，与预期清单一致")
    else:
        _fail("路由集合与预期不符", f"missing={missing} extra={extra}")


def main() -> int:
    print("=" * 68)
    print("安卓端计划勾选持久化（写回计划真源）验证")
    print("=" * 68)

    test_title_normalization_and_matching()
    test_toggle_writes_truth_source()
    test_ambiguous_and_missing_are_refused()
    test_truth_source_survives_resync()
    test_vocab_auto_mark_uses_today()
    test_plan_item_crud_end_to_end()
    test_android_wiring()
    test_route_registry_after_split()

    print("\n" + "=" * 68)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 68)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
