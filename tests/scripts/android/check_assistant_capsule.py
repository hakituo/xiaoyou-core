#!/usr/bin/env python3
"""
Android 端「跨应用语音助手悬浮窗」静态校验。

为什么需要它
------------
AGENTS.md 规定 Android/Gradle 任务不允许在沙箱里跑 gradlew / build / compile
（会和 Android Studio 抢 Configuration Cache 锁），编译由用户在 Android Studio 完成。
而 Kotlin / Compose / WindowManager 的失败原因高度集中在少数几个坑上，静态扫描能提前拦掉：

- 漏 import 扩展函数（`InfiniteTransition.animateFloat`、`WindowInsets.navigationBars` 这类），
  报错位置离根因几十行，看起来像别的问题；
- import 分包写错（`Modifier.offset` 在 foundation.layout 而不在 ui.layout）；
- 悬浮窗写成 `MATCH_PARENT` → 变全屏窗口，把整个屏幕的触摸全吃掉；
- Service 里的 ComposeView 忘了挂 `ViewTreeLifecycleOwner` 三件套 → 一 setContent 就崩；
- Activity 顶层 Composable 用了 companion object 里的常量 → Unresolved reference。

检查项
------
1. 文件齐全（悬浮窗相关 9 个）且旧的内嵌容器文件已删除
2. 新增 Kotlin 文件里的大写标识符都能解析（本文件 import / 本文件定义 / 同包定义 / 内置白名单）
3. AppPreferences 的新属性与 KEY_ / DEFAULT_ 常量一一对应
4. Hilt Module 里每个 @Binds 的实现类都带 @Inject constructor
5. 四个端口 interface 与 Stub 实现一一对应
6. Manifest 权限与 Service 注册到位
7. WindowInsets companion 扩展逐个 import（Compose 分包坑）
8. 悬浮窗的关键约束（窗口类型 / WRAP_CONTENT / 触摸穿透 / 三件套 / 尺寸同步）
9. MainActivity 只做启动与引导，不再往 Activity 里挂胶囊
10. import 路径是否在别处出现过（揪写错分包，警告级）
11. 进程安全约束：前台服务逐类型兜底 / onTimeout 降级 / 挂窗口整体兜底与回滚
    （本服务是唯一会追着「App 切到后台」那一刻做动作的组件，异常逃到进程层
    就是「刚切出去就被杀」，所以这几条兜底必须有，且不允许被删掉）
12. 悬浮窗内容不得依赖 Activity 专属 API：主题里不允许 `as Activity` 硬转
    （真机崩溃实证：AvelineTheme 硬转 Activity，在 Service 宿主里抛 ClassCastException，
    抛点还在 ComposeView attach 的 Choreographer 帧里，调用方 try/catch 抓不到）

用法
----
    venv_core\\Scripts\\python.exe tests\\scripts\\android\\check_assistant_capsule.py

退出码 0 = 全部通过；1 = 有检查项失败。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Windows 控制台默认 GBK，打印中文前先把 stdout 切成 UTF-8，避免 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def find_repo_root(start: Path) -> Path:
    """向上找到仓库根（同时含 AGENTS.md 与 clients 目录的那一层）。"""
    for candidate in [start] + list(start.parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / "clients").is_dir():
            return candidate
    raise RuntimeError(f"定位不到仓库根: {start}")


REPO_ROOT = find_repo_root(Path(__file__).resolve())
ANDROID_ROOT = REPO_ROOT / "clients" / "frontend" / "aveline-android" / "android"
SRC_ROOT = ANDROID_ROOT / "app" / "src" / "main" / "java" / "com" / "aveline" / "ai"
MANIFEST_PATH = ANDROID_ROOT / "app" / "src" / "main" / "AndroidManifest.xml"

ASSISTANT_DIR = SRC_ROOT / "mobile" / "presentation" / "assistant"
PORTS_DIR = ASSISTANT_DIR / "ports"
OVERLAY_DIR = SRC_ROOT / "mobile" / "services" / "assistant"

# 不需要 import 的符号：Kotlin 标准库 / 注解 / 语言机制
BUILTIN_SYMBOLS = {
    "Any", "Array", "Boolean", "BooleanArray", "Byte", "Char", "CharSequence",
    "Comparable", "Comparator", "Double", "DoubleArray", "Enum", "Exception", "Error",
    "Float", "FloatArray", "Function", "HashMap", "HashSet", "Int", "IntArray", "Integer",
    "Iterable", "Iterator", "Lazy", "LinkedHashMap", "LinkedHashSet", "List", "Long",
    "LongArray", "Map", "MutableCollection", "MutableIterable", "MutableIterator",
    "MutableList", "MutableMap", "MutableSet", "Nothing", "Number", "Pair", "Result",
    "RuntimeException", "Sequence", "Set", "Short", "ShortArray", "String", "Throwable",
    "Triple", "Unit", "StringBuilder", "IllegalStateException", "IllegalArgumentException",
    "UnsupportedOperationException", "IndexOutOfBoundsException", "NoSuchElementException",
    "Companion", "Deprecated", "JvmStatic", "JvmField", "JvmName", "JvmSuppressWildcards",
    "OptIn", "Suppress", "Volatile", "Synchronized", "Throws", "Transient",
    # java.lang 里无需 import 的常见类型
    "System", "Math", "Thread", "Runnable",
    # android.app.Service 的常量：在 Service 子类里可以裸名直接用，不需 import
    "START_STICKY", "START_NOT_STICKY", "START_REDELIVER_INTENT", "START_STICKY_COMPATIBILITY",
    "STOP_FOREGROUND_DETACH", "STOP_FOREGROUND_REMOVE", "STOP_FOREGROUND_LEGACY",
}

RE_IMPORT = re.compile(r"^\s*import\s+(?:kotlinx\.|androidx\.)?([\w.]+)", re.MULTILINE)
RE_IMPORT_FULL = re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE)
RE_DEFINITION = re.compile(
    r"\b(?:sealed\s+class|data\s+class|enum\s+class|abstract\s+class|class|object|interface|"
    r"fun|typealias|val|var)\s+(\w+)"
)
# 带 receiver 的定义，如 `private fun RowScope.CapsuleContent(...)`
RE_MEMBER_DEFINITION = re.compile(r"\bfun\s+[\w.]+\.(\w+)")
# enum 条目（TAP / WAKE_WORD 这种裸常量）
RE_ENUM_BODY = re.compile(r"enum class \w+[^{]*\{([^{}]*)\}", re.DOTALL)
RE_ENUM_ENTRY = re.compile(r"(?<![\w.])([A-Z][A-Z0-9_]*)(?![\w(])")
RE_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/|\"\"\".*?\"\"\"|\"[^\"\n]*\"", re.DOTALL)
RE_IDENTIFIER = re.compile(r"(?<![\w.])([A-Z][A-Za-z0-9_]*)")

# WindowInsets 的 companion 扩展：只 import WindowInsets 本身取不到这些成员
WINDOW_INSETS_EXTENSIONS = [
    "navigationBars", "navigationBarsIgnoringVisibility", "statusBars",
    "statusBarsIgnoringVisibility", "systemBars", "systemBarsIgnoringVisibility",
    "systemGestures", "mandatorySystemGestures", "captionBar", "ime",
    "imeAnimationSource", "imeAnimationTarget", "displayCutout", "waterfall",
    "tappableElement", "safeContent", "safeDrawing", "safeGestures",
]

results: list[tuple[bool, str, str]] = []
warnings: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    """登记一条检查结果。"""
    results.append((ok, name, detail))
    return ok


def read_kt_files(directory: Path) -> list[Path]:
    """取目录下所有 .kt 文件（不含子目录）。"""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.kt") if p.is_file())


def strip_noise(source: str) -> str:
    """去掉注释与字符串字面量，避免把注释里的名字当成真实引用。"""
    return RE_COMMENT.sub(" ", source)


def extract_definitions(code: str) -> set[str]:
    """抽出一段代码里定义出来的符号名：普通定义 + 带 receiver 的扩展 + enum 条目。"""
    symbols = set(RE_DEFINITION.findall(code))
    symbols.update(RE_MEMBER_DEFINITION.findall(code))
    for body in RE_ENUM_BODY.findall(code):
        symbols.update(RE_ENUM_ENTRY.findall(body))
    return symbols


def collect_symbols(files: list[Path]) -> set[str]:
    """收集一组文件里定义出来的符号名（近似即可，够用来解析引用）。"""
    symbols: set[str] = set()
    for path in files:
        symbols.update(extract_definitions(strip_noise(path.read_text(encoding="utf-8"))))
    return symbols


def function_bodies(code: str, name: str) -> list[str]:
    """截出 `fun <name>(...)` 的全部函数体。

    用花括号配平而不是靠缩进/下一个 fun 的位置：函数体里还有 when / try / for 等
    嵌套管块，按缩进切容易切错。同名重载（如两个 onTimeout）会全部返回。
    """
    bodies: list[str] = []
    for match in re.finditer(rf"\bfun\s+{re.escape(name)}\s*\(", code):
        brace_open = code.find("{", match.end())
        if brace_open < 0:
            continue
        depth = 0
        for index in range(brace_open, len(code)):
            if code[index] == "{":
                depth += 1
            elif code[index] == "}":
                depth -= 1
                if depth == 0:
                    bodies.append(code[brace_open : index + 1])
                    break
    return bodies


def function_body(code: str, name: str) -> str:
    """取单个函数的函数体；找不到返回空串。"""
    bodies = function_bodies(code, name)
    return bodies[0] if bodies else ""


def unresolved_symbols(path: Path, package_symbols: set[str]) -> list[str]:
    """找出文件里引用了但解析不到来源的大写标识符。"""
    source = path.read_text(encoding="utf-8")
    imported = {full.split(".")[-1] for full in RE_IMPORT.findall(source)}
    known = imported | extract_definitions(strip_noise(source)) | package_symbols | BUILTIN_SYMBOLS

    missing = [
        match.group(1)
        for match in RE_IDENTIFIER.finditer(strip_noise(source))
        if match.group(1) not in known
    ]
    return sorted(set(missing))


def main() -> int:
    capsule_stage = ASSISTANT_DIR / "AssistantCapsuleStage.kt"
    capsule = ASSISTANT_DIR / "AssistantCapsule.kt"
    capsule_overlay = ASSISTANT_DIR / "AssistantCapsuleOverlay.kt"
    capsule_view_model = ASSISTANT_DIR / "AssistantCapsuleViewModel.kt"
    ports = PORTS_DIR / "AssistantPorts.kt"
    overlay_service = OVERLAY_DIR / "AssistantOverlayService.kt"
    overlay_lifecycle = OVERLAY_DIR / "AssistantOverlayLifecycleOwner.kt"
    overlay_permission = OVERLAY_DIR / "AssistantOverlayPermission.kt"
    ports_module = SRC_ROOT / "mobile" / "di" / "AssistantPortsModule.kt"
    prefs_path = SRC_ROOT / "mobile" / "data" / "local" / "preferences" / "AppPreferences.kt"
    main_activity = SRC_ROOT / "mobile" / "presentation" / "MainActivity.kt"
    legacy_host = ASSISTANT_DIR / "AssistantCapsuleHost.kt"

    expected_files = [
        capsule_stage, capsule, capsule_overlay, capsule_view_model, ports,
        overlay_service, overlay_lifecycle, overlay_permission, ports_module,
    ]

    # ── 1. 文件齐不齐 + 旧内嵌容器已删除 ─────────────────────────────────────
    missing_files = [str(p) for p in expected_files if not p.is_file()]
    check(
        not missing_files,
        "悬浮窗相关文件齐全",
        f"缺失: {missing_files}" if missing_files else f"{len(expected_files)} 个文件全部存在",
    )
    check(
        not legacy_host.exists(),
        "只能在 Activity 内使用的旧容器已删除",
        "AssistantCapsuleHost.kt 已移除" if not legacy_host.exists()
        else "AssistantCapsuleHost.kt 仍在，说明还留着 App 内的旧路径",
    )
    if missing_files:
        report()
        return 1

    # ── 2. 符号能否解析（漏 import 检查）──────────────────────────────────────
    assistant_symbols = collect_symbols(read_kt_files(ASSISTANT_DIR))
    ports_symbols = collect_symbols(read_kt_files(PORTS_DIR))
    overlay_symbols = collect_symbols(read_kt_files(OVERLAY_DIR))

    unresolved: list[str] = []
    for path in read_kt_files(ASSISTANT_DIR):
        for name in unresolved_symbols(path, assistant_symbols | ports_symbols):
            unresolved.append(f"{path.name}: {name}")
    for path in read_kt_files(PORTS_DIR):
        for name in unresolved_symbols(path, ports_symbols):
            unresolved.append(f"{path.name}: {name}")
    for path in read_kt_files(OVERLAY_DIR):
        for name in unresolved_symbols(path, overlay_symbols):
            unresolved.append(f"{path.name}: {name}")
    for name in unresolved_symbols(ports_module, set()):
        unresolved.append(f"{ports_module.name}: {name}")

    check(
        not unresolved,
        "符号引用可解析（无漏 import / 拼错类名）",
        "全部解析成功" if not unresolved else f"未解析: {unresolved}",
    )

    # ── 3. AppPreferences 属性与常量一一对应 ─────────────────────────────────
    prefs_source = prefs_path.read_text(encoding="utf-8")
    pref_problems: list[str] = []
    for prop, key_const, default_const in [
        ("assistantCapsuleEnabled", "KEY_ASSISTANT_CAPSULE_ENABLED", "DEFAULT_ASSISTANT_CAPSULE_ENABLED"),
        ("assistantOverlayX", "KEY_ASSISTANT_OVERLAY_X", "DEFAULT_ASSISTANT_OVERLAY_POSITION"),
        ("assistantOverlayY", "KEY_ASSISTANT_OVERLAY_Y", "DEFAULT_ASSISTANT_OVERLAY_POSITION"),
        ("assistantOverlayPromptedAt", "KEY_ASSISTANT_OVERLAY_PROMPTED_AT", "DEFAULT_ASSISTANT_OVERLAY_PROMPTED_AT"),
    ]:
        if f"var {prop}:" not in prefs_source:
            pref_problems.append(f"缺属性 var {prop}")
        if f"const val {key_const} =" not in prefs_source:
            pref_problems.append(f"缺常量 {key_const}")
        if f"const val {default_const} =" not in prefs_source:
            pref_problems.append(f"缺常量 {default_const}")
        body = prefs_source.split(f"var {prop}:", 1)[-1].split("get()", 1)[-1][:400]
        if key_const not in body or default_const not in body:
            pref_problems.append(f"{prop} 的 getter/setter 没用上对应常量")
    # 旧的位置字段必须清掉，避免留下两套互相矛盾的位置真源
    for stale in ("assistantCapsuleBiasX", "assistantCapsuleLiftDp"):
        if stale in prefs_source:
            pref_problems.append(f"旧的 {stale} 仍在（位置真源已改为悬浮窗绝对坐标）")
    check(
        not pref_problems,
        "AppPreferences 新属性与 KEY/DEFAULT 常量一一对应",
        "4 组全部匹配，旧位置字段已清理" if not pref_problems else f"{pref_problems}",
    )

    # ── 4. @Binds 实现类必须能注入 ───────────────────────────────────────────
    ports_source = "\n".join(p.read_text(encoding="utf-8") for p in read_kt_files(PORTS_DIR))
    module_source = ports_module.read_text(encoding="utf-8")
    bindings = re.findall(r"abstract fun \w+\(\s*impl:\s*(\w+)\s*\)\s*:\s*(\w+)", module_source)
    bind_problems: list[str] = []
    if len(bindings) != 4:
        bind_problems.append(f"@Binds 条目数应为 4，实际 {len(bindings)}")
    for impl_name, interface_name in bindings:
        if not re.search(rf"class {impl_name}\b[^{{]*@Inject constructor\(", ports_source):
            bind_problems.append(f"{impl_name} 缺少 @Inject constructor")
        if f"interface {interface_name}" not in ports_source:
            bind_problems.append(f"找不到 interface {interface_name}")
    check(
        not bind_problems,
        "Hilt @Binds 的实现类均可注入",
        "4 条绑定全部合规" if not bind_problems else f"{bind_problems}",
    )

    # ── 5. 端口 interface 与 Stub 一一对应 ───────────────────────────────────
    expected_interfaces = {
        "AssistantWakeWordPort", "AssistantBackendPort",
        "AssistantSpeechPort", "AssistantActionPort",
    }
    interfaces = set(re.findall(r"interface (Assistant\w+Port)\b", ports_source))
    stubs = set(re.findall(r"class (StubAssistant\w+Port)\b", ports_source))
    expected_stubs = {f"Stub{name}" for name in expected_interfaces}
    port_problems: list[str] = []
    if interfaces != expected_interfaces:
        port_problems.append(f"interface 集合不符，差异: {expected_interfaces ^ interfaces}")
    if stubs != expected_stubs:
        port_problems.append(f"Stub 集合不符，差异: {expected_stubs ^ stubs}")
    check(
        not port_problems,
        "四个端口 interface 与 Stub 实现一一对应",
        "WakeWord / Backend / Speech / Action 四组齐全" if not port_problems else f"{port_problems}",
    )

    # ── 6. Manifest 权限与 Service 注册 ──────────────────────────────────────
    manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    manifest_problems: list[str] = []
    for permission, why in [
        ("android.permission.SYSTEM_ALERT_WINDOW", "跨应用悬浮窗必需"),
        ("android.permission.FOREGROUND_SERVICE_MICROPHONE", "Android 14+ 麦克风前台服务必需"),
    ]:
        if permission not in manifest:
            manifest_problems.append(f"缺权限 {permission}（{why}）")
    if "AssistantOverlayService" not in manifest:
        manifest_problems.append("AssistantOverlayService 未在 Manifest 注册")
    if 'android:foregroundServiceType="specialUse|dataSync"' not in manifest:
        manifest_problems.append("缺少 foregroundServiceType=\"specialUse|dataSync\" 声明")
    if "PROPERTY_SPECIAL_USE_FGS_SUBTYPE" not in manifest:
        manifest_problems.append("Android 14+ 的 specialUse 类型需要 PROPERTY_SPECIAL_USE_FGS_SUBTYPE 说明")
    check(
        not manifest_problems,
        "Manifest 权限与悬浮窗 Service 注册到位",
        "权限 + 服务 + FGS 类型全部就位" if not manifest_problems else f"{manifest_problems}",
    )

    # ── 7. WindowInsets companion 扩展必须逐个 import ────────────────────────
    inset_problems: list[str] = []
    for path in expected_files:
        code = strip_noise(path.read_text(encoding="utf-8"))
        if "WindowInsets" not in code:
            continue
        imports = set(RE_IMPORT_FULL.findall(code))
        for ext in WINDOW_INSETS_EXTENSIONS:
            if re.search(rf"WindowInsets\.{ext}\b", code) and \
                    f"androidx.compose.foundation.layout.{ext}" not in imports:
                inset_problems.append(
                    f"{path.name}: 用了 WindowInsets.{ext} 但缺 import "
                    f"androidx.compose.foundation.layout.{ext}"
                )
    check(
        not inset_problems,
        "WindowInsets companion 扩展逐个 import（Compose 分包坑）",
        "无遗漏" if not inset_problems else f"{inset_problems}",
    )

    # ── 8. 悬浮窗关键约束 ────────────────────────────────────────────────────
    # 一律用「去注释后」的代码做判断：这两个文件里有意写了警示注释
    # （"绝对不能用 fillMaxSize"），拿原文搜会把这些警示本身当成违规。
    service_source = strip_noise(overlay_service.read_text(encoding="utf-8"))
    overlay_content_source = strip_noise(capsule_overlay.read_text(encoding="utf-8"))
    overlay_problems: list[str] = []

    if "TYPE_APPLICATION_OVERLAY" not in service_source:
        overlay_problems.append("必须用 TYPE_APPLICATION_OVERLAY（只有系统窗口层才能盖在别的 App 之上）")
    if "FLAG_NOT_TOUCH_MODAL" not in service_source:
        overlay_problems.append("缺 FLAG_NOT_TOUCH_MODAL：窗口之外区域的触摸传不到下层 App")
    if "FLAG_NOT_FOCUSABLE" not in service_source:
        overlay_problems.append("缺 FLAG_NOT_FOCUSABLE：会抢输入法焦点")
    if "WindowManager.LayoutParams.WRAP_CONTENT" not in service_source:
        overlay_problems.append(
            "窗口宽高必须是 WRAP_CONTENT —— 用 MATCH_PARENT 会变成全屏窗口，"
            "空白区域把整屏触摸全吃掉"
        )
    if "MATCH_PARENT" in service_source:
        overlay_problems.append("服务里出现了 MATCH_PARENT，悬浮窗窗口不能用它做宽高")
    for setter_import in (
        "androidx.lifecycle.setViewTreeLifecycleOwner",
        "androidx.lifecycle.setViewTreeViewModelStoreOwner",
        "androidx.savedstate.setViewTreeSavedStateRegistryOwner",
    ):
        if setter_import not in service_source:
            overlay_problems.append(
                f"缺 import {setter_import}：Service 里的 ComposeView 需要三件套宿主，否则 setContent 直接崩"
            )
    # 反向检查：这三个在 AndroidX 里**只有扩展函数、没有同名类**，
    # 写成 `androidx.lifecycle.ViewTreeLifecycleOwner` 会 Unresolved reference。
    for class_form in (
        "androidx.lifecycle.ViewTreeLifecycleOwner",
        "androidx.lifecycle.ViewTreeViewModelStoreOwner",
        "androidx.savedstate.ViewTreeSavedStateRegistryOwner",
    ):
        if f"import {class_form}" in service_source:
            overlay_problems.append(
                f"`import {class_form}` 不存在（它们是 Kotlin 扩展函数，不是类），"
                f"应改为 import 对应的 setViewTreeXxxOwner"
            )
    if "removeView" not in service_source:
        overlay_problems.append("onDestroy 必须移除窗口，否则窗口会残留在屏幕上")
    if "updateViewLayout" not in service_source:
        overlay_problems.append("需要 updateViewLayout：拖动改坐标、内容尺寸变化同步窗口都靠它")
    # 内容侧：必须 wrap，绝不能 fill
    if "wrapContentSize" not in overlay_content_source:
        overlay_problems.append("AssistantCapsuleOverlay 需要 wrapContentSize")
    if "fillMaxSize" in overlay_content_source:
        overlay_problems.append(
            "AssistantCapsuleOverlay 里出现 fillMaxSize：会把 WRAP_CONTENT 窗口撑成全屏，"
            "空白区域开始拦触摸"
        )
    check(
        not overlay_problems,
        "悬浮窗关键约束（窗口类型 / 尺寸 / 触摸穿透 / 三件套 / 尺寸同步）",
        "窗口层、WRAP_CONTENT、触摸穿透、三件套、updateViewLayout 全部到位"
        if not overlay_problems else f"{overlay_problems}",
    )

    # ── 9. MainActivity 只负责启动与引导 ─────────────────────────────────────
    activity_source = main_activity.read_text(encoding="utf-8")
    activity_clean = strip_noise(activity_source)
    mount_problems: list[str] = []
    if "AssistantCapsuleHost" in activity_source:
        mount_problems.append("还在往 Activity 里挂胶囊（应改为悬浮窗服务，App 内不该显示）")
    if "AssistantOverlayService.start(" not in activity_clean:
        mount_problems.append("没有启动 AssistantOverlayService")
    if "AssistantOverlayPermission.openOverlaySettings(" not in activity_clean:
        mount_problems.append("没有悬浮窗权限的引导跳转")
    if "override fun onResume" not in activity_clean:
        mount_problems.append("缺 onResume 补偿：用户从系统设置页授权回来后要能自动挂上悬浮窗")
    # 开关关闭时不得无条件发停止指令：那会把没在跑的服务创建出来再停掉，通知栏会闪
    if "AssistantOverlayService.isRunning" not in activity_clean:
        mount_problems.append(
            "关闭分支没有先判 AssistantOverlayService.isRunning 就发停止指令，"
            "会把没在跑的服务拉起来再停掉、通知栏闪一下"
        )
    check(
        not mount_problems,
        "MainActivity 只做启动与权限引导",
        "启动 / 引导 / 回前台补偿都在，且不再挂 App 内胶囊"
        if not mount_problems else f"{mount_problems}",
    )

    # ── 9.2 输入面板链路完整（点胶囊能打字）────────────────────────────────
    stage_source = capsule_stage.read_text(encoding="utf-8")
    capsule_source = capsule.read_text(encoding="utf-8")
    view_model_source = capsule_view_model.read_text(encoding="utf-8")
    composer_problems: list[str] = []

    if "data class Composing" not in stage_source:
        composer_problems.append("AssistantCapsuleStage 里没有 Composing 阶段")
    if "is AssistantCapsuleStage.Composing ->" not in stage_source:
        composer_problems.append("CapsuleGeometry.widthFor 没给 Composing 配宽度（sealed when 不全，编译不过）")
    if "BasicTextField" not in capsule_source:
        composer_problems.append(
            "胶囊里没有 BasicTextField：输入框缺失。"
            "（别改用 Material 的 TextField —— 它带 56dp 最小高度和描边，塞进 44dp 圆柱会顶破形状）"
        )
    for fn in ("onTextChange", "onSubmitText", "onVoiceInput"):
        if f"fun {fn}(" not in view_model_source:
            composer_problems.append(f"ViewModel 缺 {fn}()")
    # 悬浮窗默认带 FLAG_NOT_FOCUSABLE，不动态摘掉的话 IME 永远弹不出来
    if "FLAG_NOT_FOCUSABLE.inv()" not in service_source:
        composer_problems.append(
            "Service 没有动态摘掉 FLAG_NOT_FOCUSABLE：窗口不可聚焦时输入法根本不会弹出，"
            "输入框点了也打不了字"
        )
    check(
        not composer_problems,
        "输入面板链路完整（点胶囊能打字）",
        "阶段 / 宽度 / BasicTextField / ViewModel 回调 / 窗口焦点切换 全部到位"
        if not composer_problems else f"{composer_problems}",
    )

    # ── 9.1 助手总开关当前应处于「默认关闭」状态（产品决策，仅提示）─────────
    if "DEFAULT_ASSISTANT_CAPSULE_ENABLED = true" in prefs_source:
        warnings.append(
            "助手总开关默认值已是 true：确认后端对话与文字输入都已接好，"
            "否则会把只有回声桩的悬浮窗默认推给用户"
        )

    # ── 10. import 路径是否在别处出现过（揪写错分包，警告级）────────────────
    known_imports: set[str] = set()
    for kt_file in SRC_ROOT.rglob("*.kt"):
        known_imports.update(RE_IMPORT_FULL.findall(kt_file.read_text(encoding="utf-8")))
    for path in expected_files:
        for imp in sorted(set(RE_IMPORT_FULL.findall(path.read_text(encoding="utf-8")))):
            if imp not in known_imports:
                warnings.append(
                    f"{path.name} 的 import `{imp}` 在本仓其它 Kotlin 文件里从未出现过，"
                    f"确认包名没写错（如 `Modifier.offset` 在 foundation.layout 而不在 ui.layout）"
                )

    # ── 11. 进程安全约束 ─────────────────────────────────────────────────────
    # 背景：本服务是唯一会「追着 App 切到后台那一刻」做动作的组件（前后台流一翻成后台
    # 就去加系统窗口）。Service 里任何逃到进程层的异常，表现都是「刚切出去就被杀」，
    # 而三星智能管理器只会记一条「应用程序已崩溃」，看不出堆栈。所以刷引导条硬性要求：
    # 三条主路径（onCreate 初始化 / 挂前台 / 挂窗口）都必须有兜底，且不允许被删掉。
    process_safety_problems: list[str] = []

    if "CoroutineExceptionHandler" not in service_source:
        process_safety_problems.append(
            "serviceScope 缺 CoroutineExceptionHandler：SupervisorJob 只隔离失败、不兜异常，"
            "未捕获异常会经 CrashHandler 直接杀掉整个进程"
        )

    start_command_body = function_body(service_source, "onStartCommand")
    if "catch (error: Exception)" not in start_command_body:
        process_safety_problems.append(
            "onStartCommand 没有兜底（通知栏动作与系统 START_STICKY 重启都会走这里）"
        )

    create_body = function_body(service_source, "onCreate")
    if "catch (error: Exception)" not in create_body:
        process_safety_problems.append(
            "onCreate 没有兜底：Service 的 onCreate 抛未捕获异常 = 整个进程崩溃"
        )
    if "stopSelf()" not in create_body:
        process_safety_problems.append(
            "拿不到前台身份时应主动 stopSelf：不挂前台的 Service 会被系统按"
            " ForegroundServiceDidNotStartInTimeException 杀进程"
        )

    start_foreground_body = function_body(service_source, "startForegroundCompat")
    if not start_foreground_body:
        process_safety_problems.append("找不到 startForegroundCompat")
    else:
        if "catch (error: Exception)" not in start_foreground_body:
            process_safety_problems.append(
                "startForegroundCompat 里的 startForeground 没有 try/catch："
                "类型/权限/后台限制/通知被拒任一原因抛出，在 onCreate 里就是进程级崩溃"
            )
        if "ForegroundServiceTypePolicy.candidates()" not in start_foreground_body:
            process_safety_problems.append(
                "没有按 ForegroundServiceTypePolicy 的候选顺序（specialUse → dataSync → 无类型）逐类型尝试"
            )
        if "ForegroundServiceTypePolicy.hasRuntimeQuota" not in start_foreground_body:
            process_safety_problems.append(
                "配额冷却期内没有跳过受配额限制的类型，会陷入「超时 → 重启 → 再超时」死循环"
            )

    if len(function_bodies(service_source, "onTimeout")) < 2:
        process_safety_problems.append(
            "必须同时实现 onTimeout(startId) 与 onTimeout(startId, fgsType)："
            "Android 15 的 dataSync 配额到点若不自行降级，系统抛 RemoteServiceException 崩进程"
        )
    if "STOP_FOREGROUND_DETACH" not in service_source:
        process_safety_problems.append(
            "配额到点降级时应该用 STOP_FOREGROUND_DETACH 解除前台状态（保留通知）"
        )
    if "fgsQuotaResumeAtMs" not in service_source:
        process_safety_problems.append(
            "配额冷却点要与常驻保活服务共用 appPreferences.fgsQuotaResumeAtMs"
            "（Android 15 的 dataSync 配额是按应用统计的，两个前台服务共用一个额度）"
        )

    attach_body = function_body(service_source, "attachOverlay")
    if not attach_body:
        process_safety_problems.append("找不到 attachOverlay")
    else:
        catch_index = attach_body.find("catch (error: Exception)")
        if catch_index < 0:
            process_safety_problems.append(
                "attachOverlay 没有兜底：它跑在「切后台」那一刻的 collector 里，"
                "抛出去就是用户看到的「刚切出去就被杀」"
            )
        else:
            for risky_call in ("setContent", "addView"):
                call_index = attach_body.find(risky_call)
                if call_index < 0:
                    process_safety_problems.append(f"attachOverlay 里找不到 {risky_call}")
                elif call_index > catch_index:
                    process_safety_problems.append(
                        f"{risky_call} 不在 try 保护范围内（它出现在 catch 之后）"
                    )
            if "removeViewImmediate" not in attach_body[catch_index:]:
                process_safety_problems.append(
                    "挂载失败时没有回滚残留窗口：下次切后台会因 overlayView != null 直接 return，"
                    "悬浮窗从此再也出不来"
                )

    check(
        not process_safety_problems,
        "进程安全约束（前台服务逐类型兜底 / onTimeout 降级 / 挂窗口兜底与回滚）",
        "startForeground 逐类型 try/catch + CoroutineExceptionHandler + onTimeout 降级 + attach 回滚全部到位"
        if not process_safety_problems else f"{process_safety_problems}",
    )

    # ── 12. 悬浮窗内容不得依赖 Activity 专属 API ─────────────────────────────
    # 血证（2026-09-23 真机 crash_logs 堆栈）：AvelineTheme 里 `(view.context as Activity).window`
    # 在悬浮窗里抛 java.lang.ClassCastException: AssistantOverlayService cannot be cast to
    # android.app.Activity，抛点是 ComposeView attach 之后的 Choreographer 帧（Composition 延迟到
    # onAttachedToWindow 才开始），所以调用方包在 setContent 外的 try/catch 抓不到，直接崩进程。
    # 结论：悬浮窗里跑的 Compose 代码**不能**假设宿主是 Activity，取不到就要降级而不是硬转。
    theme_path = SRC_ROOT / "mobile" / "presentation" / "theme" / "Theme.kt"
    host_problems: list[str] = []
    if not theme_path.is_file():
        host_problems.append(f"找不到 {theme_path}")
    else:
        theme_source = strip_noise(theme_path.read_text(encoding="utf-8"))
        if re.search(r"\bas\s+Activity\b", theme_source):
            host_problems.append(
                "Theme.kt 里仍有 `as Activity` 硬转：悬浮窗的 LocalView.context 是 Service，"
                "转换必抛 ClassCastException 且崩在 Choreographer 帧里、抓不住"
            )
        if "findActivity()" not in theme_source:
            host_problems.append(
                "Theme.kt 应通过 findActivity() 取宿主 Activity：取不到就跳过状态栏/导航栏配置，"
                "不能靠硬转换"
            )
    check(
        not host_problems,
        "主题可在非 Activity 宿主里安全组合（悬浮窗 Service 不因硬转 Activity 而崩）",
        "窗口颜色配置改为 findActivity() 可空取宿主，Service 宿主下自动跳过"
        if not host_problems else f"{host_problems}",
    )

    return report()


def report() -> int:
    """打印结果并返回退出码。"""
    print("=" * 72)
    print("Android 语音助手悬浮窗 静态校验")
    print("=" * 72)
    for ok, name, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if detail:
            print(f"       {detail}")
    failed = sum(1 for ok, _, _ in results if not ok)
    print("-" * 72)
    if warnings:
        print(f"警告 {len(warnings)} 条（不阻断）：")
        for item in warnings:
            print(f"  ! {item}")
        print("-" * 72)
    if failed:
        print(f"结果: {failed} 项未通过 / 共 {len(results)} 项")
        print("提示: 本脚本只能兜住静态错误，最终仍需 Android Studio 编译确认。")
        return 1
    print(f"结果: 全部 {len(results)} 项通过")
    print("注意: 本脚本不做编译，最终请以 Android Studio 编译结果为准。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
