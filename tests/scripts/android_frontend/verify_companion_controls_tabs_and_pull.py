"""静态验证 Android 伴侣控制、Route Tab 与跟手进入手势。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
)


def read(relative: str) -> str:
    """读取 Android 源文件并统一换行。"""
    return (ANDROID / relative).read_text(encoding="utf-8").replace("\r\n", "\n")


def require(source: str, *needles: str) -> None:
    """断言源码包含全部关键结构。"""
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise AssertionError(f"缺少关键实现: {missing}")


def main() -> None:
    tab_row = read("presentation/components/AvelineTabRow.kt")
    require(
        tab_row,
        "containerColor = Color.Transparent",
        "indicator = {}",
        "divider = {}",
        "maxLines = 1",
        "softWrap = false",
        "FontWeight.SemiBold",
    )
    for forbidden in ("SecondaryIndicator", "SelectionSurface", ".background("):
        if forbidden in tab_row:
            raise AssertionError(f"纯文字 Tab 不应包含: {forbidden}")

    for relative in (
        "presentation/companion/CompanionScreen.kt",
        "presentation/life/LifeScreen.kt",
        "presentation/settings/SettingsScreenV2.kt",
        "presentation/study/StudyScreenV2.kt",
    ):
        require(read(relative), "AvelineTabRow(")

    panel = read("presentation/components/PullableDismissPanel.kt")
    require(
        panel,
        "AnchoredDraggableState(initialValue = DismissPanelValue.Dismissed)",
        "gesturesEnabled: Boolean = true",
        "enabled = gesturesEnabled",
        "if (!gesturesEnabled) {",
        "fun dispatchOpeningDelta",
        "suspend fun settleOpeningDrag",
        "dragState.dispatchRawDelta(deltaX)",
        "dragState.animateTo(target)",
    )
    if panel.count("!gesturesEnabled") < 4:
        raise AssertionError("详情退出手势必须同时禁用拖动、滚动与 fling 接力")

    chat = read("presentation/chat/ChatScreen.kt")
    require(
        chat,
        "companionPanelState.dispatchOpeningDelta(dx)",
        "companionPanelState.dispatchOpeningDelta(deltaX)",
        "companionEditScope.launch {",
        "companionPanelState.settleOpeningDrag(",
        "PullableDismissPanel(",
        "gesturesEnabled = companionDismissGestureEnabled",
        "statusViewModel.refreshStatus()",
    )
    if (
        "openThresholdPx" in chat
        or "slideInHorizontally(" in chat
        or "withFrameNanos" in chat
        or "if (showCompanionPanel) {\n            PullableDismissPanel(" in chat
    ):
        raise AssertionError("聊天页仍存在松手后才触发的旧式详情入场路径")

    api = read("data/remote/api/AvelineApiService.kt")
    require(
        api,
        '@POST("/api/v1/life/sleep/wake")',
        '@POST("/api/v1/life/activity/interrupt")',
        '@POST("/api/v1/life/activity/skip")',
    )

    repository = read("data/repository/StatusRepositoryImpl.kt")
    require(
        repository,
        'throw IllegalStateException(backendMessage ?: "$label 操作失败")',
        "replyMode = response.reply_policy?.mode",
        "dailyPlan = response.daily_plan?.let",
        "CharacterDailySlot(",
    )
    if "return Result.failure(IllegalStateException" in repository:
        raise AssertionError("表达式函数体中不能使用提前 return")

    life_dto = read("data/remote/dto/LifeStatusResponse.kt")
    require(
        life_dto,
        "val reply_policy: ReplyPolicySummaryDto?",
        "val daily_plan: CharacterDailyPlanDto?",
        "data class CharacterDailySlotDto(",
    )
    life_model = read("domain/models/LifeStatus.kt")
    require(
        life_model,
        "val replyMode: String",
        "val dailyPlan: CharacterDailyPlan?",
        "data class CharacterDailySlot(",
    )

    status_tab = read("presentation/companion/CompanionStatusTab.kt")
    require(
        status_tab,
        'label = "唤醒"',
        'label = "打断"',
        'label = "跳过活动"',
        "LifeHealth",
        "LifeHunger",
        "LifeHappiness",
        "LifeEnergy",
        'replyMode == "silent"',
        'replyMode == "delayed"',
        "formatReplyDelay(lifeStatus)",
    )
    for misleading in ("现在可以直接聊天", "chatEligible"):
        if misleading in status_tab:
            raise AssertionError(f"状态页仍混用了 Peer Chat 语义: {misleading}")

    companion_screen = read("presentation/companion/CompanionScreen.kt")
    require(
        companion_screen,
        'listOf("状态", "日程", "模型", "人设", "记忆")',
        "1 -> CompanionScheduleTab(uiState = statusUiState)",
        "onDismissGestureEnabledChange(pagerState.settledPage == 0)",
        "if (!pagerState.isScrollInProgress)",
        "if (pagerState.settledPage == 1) onRefreshStatus()",
    )
    schedule_tab = read("presentation/companion/CompanionScheduleTab.kt")
    require(
        schedule_tab,
        "plan.slots",
        "slot.executionStatus == \"in_progress\"",
        "companionActivityLabel(slot.activity)",
        "companionRoleLabel(plan?.roleId)",
        'text = "今日日程正在同步…"',
    )
    if "还没有生成日程" in schedule_tab:
        raise AssertionError("日程页不能把暂未同步误报为没有生成")

    life_router = (ROOT / "routers/v1/life.py").read_text(encoding="utf-8")
    require(
        life_router,
        '"activity": current_activity.value',
        '"activity_chat_eligible": current_activity in CHAT_ELIGIBLE_ACTIVITIES',
        '"reply_policy": reply_policy',
        '"sleep_summary": sleep_summary',
        '"daily_plan": daily_plan.to_dict() if daily_plan is not None else None',
    )

    print("[OK] 伴侣控制、纯文字 Route Tab 与跟手进入动画静态验证通过")


if __name__ == "__main__":
    main()
