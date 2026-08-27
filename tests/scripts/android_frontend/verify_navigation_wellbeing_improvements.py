"""静态验证 Android 侧边栏、废弃路由和数字健康改进是否完整落地。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ANDROID_SOURCE = (
    PROJECT_ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
)


def read(relative_path: str) -> str:
    return (ANDROID_SOURCE / relative_path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_drawer_gesture() -> None:
    source = read("presentation/MainActivity.kt")
    drawer = read("presentation/components/PullableNavigationDrawer.kt")
    require("PullableNavigationDrawer(" in source, "主页没有使用可跟手侧边栏")
    require("ModalNavigationDrawer(" not in source, "仍在使用无法注入连续位移的 Material Drawer")
    require("AnchoredDraggableState" in drawer, "侧边栏没有统一的锚点拖拽状态")
    require(".anchoredDraggable(" in drawer, "主页直接拖拽没有驱动侧边栏位移")
    require("NestedScrollConnection" in drawer, "缺少 Pager 边界 NestedScroll 仲裁")
    require("onPreScroll" in drawer and "onPostScroll" in drawer, "手势接力后没有持续接管双向位移")
    require("dispatchRawDelta(available.x)" in drawer, "Pager 剩余拖拽没有实时驱动 Drawer")
    require("translationX = state.dragState.offset" in drawer, "Drawer UI 没有绑定实时拖拽偏移")
    require("onPostFling" in drawer and "animateTo(target)" in drawer, "松手后没有按距离/速度吸附")
    require("distance * 0.12f" in drawer and "progress >= 0.12f" in drawer, "主页与 Route 的侧栏打开距离仍不一致")
    require("onPreFling" in drawer and "originalFlingVelocityX = if (drawerHasMoved)" in drawer, "Route 没有保留自身拖拽的原始甩动速度")
    require("releaseVelocityX >= velocityThresholdPx" in drawer, "Route 没有复用主页的速度打开判定")
    require("if (!drawerHasMoved)" in drawer, "子页面甩动仍可能在抽屉未位移时串联打开侧栏")
    require("originalFlingVelocityX = if (drawerHasMoved)" in drawer, "抽屉仍会记录子页面独占手势的甩动速度")
    require("if (state.isVisible)" in drawer, "关闭态仍可能保留全屏遮罩点击层")
    require("clickable(enabled = state.isVisible" not in drawer, "透明禁用遮罩仍覆盖 NavHost 点击")
    require(".clickable(onClick = onDismissRequest)" in drawer, "打开态遮罩无法点击关闭")
    require("pointerInput" not in source, "MainActivity 仍存在全屏上帝窗口手势监听")
    require("PointerEventPass.Initial" not in source, "MainActivity 仍在根节点抢占指针事件")
    require("WindowInsets.systemGestures" not in source, "旧边缘窗口范围计算仍然存在")
    require("detectHorizontalDragGestures" not in source, "旧透明边缘窗口手势仍然存在")
    require(".offset(x = 24.dp)" not in source, "旧透明边缘窗口仍然存在")


def verify_circle_removed() -> None:
    circle_dir = ANDROID_SOURCE / "presentation/circle"
    require(not circle_dir.exists() or not any(circle_dir.glob("*.kt")), "圈子页面源码仍然存在")
    nav_graph = read("presentation/navigation/NavGraph.kt")
    drawer = read("presentation/components/DrawerContent.kt")
    require("Routes.CIRCLE" not in nav_graph + drawer, "导航或侧边栏仍引用圈子 Route")
    require("aveline://circle" not in nav_graph, "圈子深链页面仍在导航图注册")


def verify_companion_panel_gesture() -> None:
    companion = read("presentation/companion/CompanionScreen.kt")
    chat = read("presentation/chat/ChatScreen.kt")
    panel = read("presentation/components/PullableDismissPanel.kt")

    require(".pointerInput(" not in companion, "伴侣详情内部仍用全屏 pointerInput 抢 Pager 手势")
    require("Animatable" not in companion and "Channel<" not in companion, "伴侣详情旧拖拽状态仍存在")
    require("userScrollEnabled = pagerScrollEnabled" not in companion, "伴侣详情仍靠禁用 Pager 转移手势")
    require("PullableDismissPanel(" in chat, "聊天页没有用跟手容器包住整个伴侣详情")
    require("rememberPullableDismissPanelState" in chat, "伴侣详情没有统一锚点状态")
    require("AnchoredDraggableState" in panel and ".anchoredDraggable(" in panel, "详情页没有直接跟手拖拽")
    require("NestedScrollConnection" in panel, "详情页没有接收 Pager 第一页边界剩余位移")
    require("onPreScroll" in panel and "onPostScroll" in panel, "详情页接力后不能连续正反拖动")
    require("dispatchRawDelta(available.x)" in panel, "详情页剩余位移没有实时驱动面板")
    require("translationX = state.anchoredState.offset" in panel, "整个详情页没有绑定实时水平偏移")
    require("distance * 0.12f" in panel and "progress >= 0.12f" in panel, "伴侣详情退出距离仍然过长")
    require("onPreFling" in panel and "originalFlingVelocityX = available.x" in panel, "伴侣详情没有保留 Pager 原始甩动速度")


def verify_wellbeing_enforcement() -> None:
    view_model = read("presentation/wellbeing/WellbeingViewModel.kt")
    screen = read("presentation/wellbeing/WellbeingScreen.kt")
    accessibility = read("services/AvelineAccessibilityService.kt")
    repository = read("data/repository/ContextRepositoryImpl.kt")

    require("cacheLimitsForLocalEnforcement(limits)" in view_model, "页面限额没有立即同步到本地")
    require("getAppUsageSince(todayStart)" in view_model, "页面仍完全依赖后端陈旧用量")
    require("EnforcementStatusCard" in screen, "页面没有展示限制能力是否就绪")
    require("enforceUsageLimitForForegroundApp" in accessibility, "无障碍服务没有即时拦截入口")
    require("val movedHome = goHome()" in accessibility, "无 Shizuku 时没有退回桌面的降级路径")
    require("acceptBackgroundFallback = true" in accessibility, "退回桌面后没有启用后台结束降级路径")

    aggregation = repository[repository.index("val aggregated =") : repository.index("return aggregated.map")]
    require(".take(20)" not in aggregation, "受限应用仍可能因前 20 截断而漏检")
    require("queryEvents(" in repository, "会话限额仍使用无法精确裁切的 daily bucket")


def verify_backend_model_selection() -> None:
    dto = read("data/remote/dto/ModelDto.kt")
    repository = read("data/repository/PluginsRepositoryImpl.kt")
    settings = read("presentation/settings/SettingsViewModel.kt")
    model_preference = (
        PROJECT_ROOT
        / "core/interfaces/websocket/adapters/handlers/chat/model_pref.py"
    ).read_text(encoding="utf-8")

    require('@SerialName("category")' in dto and '@SerialName("path")' in dto, "Android 没有读取后端模型类别或路由")
    require("matchesBackendSelection(response.selectedModelId)" in repository, "模型页没有按后端当前模型选择卡片")
    require("backendSelectedModelId" in repository, "后端当前模型没有作为权威状态缓存")
    require('put("model", cachedModelRoutes[modelId] ?: modelId)' in repository, "切换模型仍使用错误字段或展示名称")
    require("?: cachedModels.firstOrNull()" not in repository, "模型仓库仍会把列表第一项误当当前模型")
    require("?: models.firstOrNull()" not in settings, "设置页仍会把列表第一项误当当前模型")
    require("model = str(forced_model).strip()" in model_preference, "后端仍会忽略移动端发送的具体模型路由")


def verify_shop_cache() -> None:
    repository_contract = read("domain/repository/ShopRepository.kt")
    repository = read("data/repository/ShopRepositoryImpl.kt")
    view_model = read("presentation/shop/ShopViewModel.kt")
    nav_graph = read("presentation/navigation/NavGraph.kt")

    require("data class ShopCacheSnapshot" in repository_contract, "商城仓库没有可跨 ViewModel 恢复的分页快照")
    require("fun getCachedShopSnapshot" in repository_contract, "商城页面无法同步读取已有缓存")
    require("@Singleton" in repository and "cachedPages" in repository, "商城缓存没有保存在单例仓库中")
    require("pages.values.flatMap" in repository, "商城没有恢复已加载的分页数据")
    require("if (page == 1) pages.clear()" in repository, "手动刷新后仍可能拼接旧分页")
    require("shopRepository.getCachedShopSnapshot(category)" in view_model, "商城进入时仍未读取缓存")
    require("CACHE_MAX_AGE_MILLIS" in view_model, "商城缓存没有合理的新鲜度控制")
    require("loadJob?.cancel()" in view_model and "loadMoreJob?.cancel()" in view_model, "快速切类目时旧请求仍会覆盖新页面")
    require("items = if (keepVisibleItems) it.items else emptyList()" in view_model, "后台刷新仍会清空当前商品")
    require("onRefresh = shopViewModel::refreshItems" in nav_graph, "商城刷新按钮没有走显式刷新入口")


def main() -> None:
    verify_drawer_gesture()
    verify_circle_removed()
    verify_companion_panel_gesture()
    verify_wellbeing_enforcement()
    verify_backend_model_selection()
    verify_shop_cache()
    print("Android 前端静态验证通过：商城缓存、手势独占、后端模型同步、侧边栏与伴侣详情跟手拖拽、圈子清理、数字健康即时执行均已落地。")


if __name__ == "__main__":
    main()
