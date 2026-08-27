"""验证 Android 端聊天记录/列表预览按角色隔离的修复是否到位。

背景（Bug）：
    1) 和某个角色聊天后，切到其他角色的会话窗口，仍显示上一个角色的聊天记录；
    2) 修复后：会话列表的"最后一条消息预览"仍然串台（Aveline 显示卡夫卡的消息，
       点进去 Aveline 却为空，卡夫卡预览不更新）。

根因（叠加）：
    1) SessionRepositoryImpl.observeCurrentSession() 把 sessionId 读成局部变量快照，
       Flow 建立后锁死在首个会话，切角色时下游无法感知。
    2) 进入聊天页只记录 pendingSwitch，不切本地 session；只看历史不发消息时
       currentSessionId 停留在上一个角色。
    3) StateManager.restoreState() 在后台线程无条件把持久化的旧 sessionId 写回
       AppPreferences，与用户进入聊天页的切换形成竞态。
    4) 预览归属用了后端全局 active persona（currentPersonaFilename）而非当前查看的
       session：active persona 只在发消息时才切换，导致预览写错 persona（串台）。

2026-08-18 重构说明：原 ChatViewModel 过大的 persona/session 切换逻辑拆到
ChatSessionController，WS 消息落库与列表预览拆到 ChatIncomingMessageHandler；
本脚本断言的是拆分后的位置。

本脚本用静态断言检查修复特征，不依赖 Gradle 构建（项目规则：不在沙箱跑 gradle）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 仓库根目录：tests/scripts/android/ -> 上溯三级
REPO_ROOT = Path(__file__).resolve().parents[3]
ANDROID_SRC = (
    REPO_ROOT
    / "clients"
    / "frontend"
    / "aveline-android"
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "aveline"
    / "ai"
    / "mobile"
)
CHAT_DIR = ANDROID_SRC / "presentation" / "chat"

PREFS = ANDROID_SRC / "data" / "local" / "preferences" / "AppPreferences.kt"
SESSION_REPO = ANDROID_SRC / "data" / "repository" / "SessionRepositoryImpl.kt"
CHAT_VM = CHAT_DIR / "ChatViewModel.kt"
STATE_MANAGER = ANDROID_SRC / "utils" / "StateManager.kt"
SESSION_CONTROLLER = CHAT_DIR / "ChatSessionController.kt"
INCOMING_HANDLER = CHAT_DIR / "ChatIncomingMessageHandler.kt"
SESSION_OBSERVER = CHAT_DIR / "ChatSessionObserver.kt"
SEND_CONTROLLER = CHAT_DIR / "ChatSendController.kt"


class Checker:
    """收集断言结果，最终统一汇报。"""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []

    def check(self, ok: bool, name: str, detail: str = "") -> None:
        if ok:
            self.passed.append(name)
        else:
            self.failed.append(f"{name}{f' -> {detail}' if detail else ''}")

    def report(self) -> int:
        for name in self.passed:
            print(f"  [PASS] {name}")
        for name in self.failed:
            print(f"  [FAIL] {name}")
        total = len(self.passed) + len(self.failed)
        print(f"\n结果: {len(self.passed)}/{total} 项通过")
        return 0 if not self.failed else 1


def read(path: Path, checker: Checker) -> str:
    """读取源文件；缺失时记为失败并返回空串。"""
    if not path.exists():
        checker.check(False, f"文件存在: {path.name}", f"未找到 {path}")
        return ""
    return path.read_text(encoding="utf-8")


def strip_block_comments(text: str) -> str:
    """移除块注释与行注释，避免注释里的关键字造成误判。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def extract_block(text: str, header: str) -> str:
    """提取以 header 开头、到下一个同缩进右花括号的代码块。"""
    match = re.search(re.escape(header) + r".*?\n    \}", text, flags=re.DOTALL)
    return match.group(0) if match else ""


def main() -> int:
    print("验证 Android 聊天记录/列表预览按角色隔离修复\n")
    checker = Checker()

    prefs = strip_block_comments(read(PREFS, checker))
    session_repo = strip_block_comments(read(SESSION_REPO, checker))
    chat_vm = strip_block_comments(read(CHAT_VM, checker))
    state_manager = strip_block_comments(read(STATE_MANAGER, checker))
    session_ctrl = strip_block_comments(read(SESSION_CONTROLLER, checker))
    incoming = strip_block_comments(read(INCOMING_HANDLER, checker))
    session_observer = strip_block_comments(read(SESSION_OBSERVER, checker))
    send_controller = strip_block_comments(read(SEND_CONTROLLER, checker))

    # --- 修复点 1: currentSessionId 可观测 ---
    print("修复点 1: AppPreferences 暴露响应式 currentSessionIdFlow")
    checker.check(
        "currentSessionIdFlow" in prefs,
        "AppPreferences 定义 currentSessionIdFlow",
    )
    checker.check(
        "_currentSessionIdFlow.value = value" in prefs,
        "currentSessionId 的 setter 同步推送到 Flow",
    )

    # --- 修复点 2: observeCurrentSession 跟随切换 ---
    print("\n修复点 2: observeCurrentSession 跟随 sessionId 变化")
    observe_body = extract_block(session_repo, "override fun observeCurrentSession()")
    checker.check(bool(observe_body), "定位 observeCurrentSession 实现")
    checker.check(
        "currentSessionIdFlow" in observe_body,
        "observeCurrentSession 订阅响应式 sessionId",
    )
    checker.check(
        "flatMapLatest" in observe_body,
        "observeCurrentSession 用 flatMapLatest 重建下游订阅",
    )
    # 回归防护：不得再把 sessionId 读成一次性局部快照
    checker.check(
        not re.search(r"val\s+sessionId\s*=\s*appPreferences\.currentSessionId", observe_body),
        "observeCurrentSession 不再使用 sessionId 局部快照",
    )

    # --- 修复点 3: 进入聊天页立即切本地 session（ChatSessionController） ---
    print("\n修复点 3: 进入聊天页即切换本地 session")
    checker.check(
        "fun switchLocalSession" in session_ctrl,
        "ChatSessionController 提供 switchLocalSession",
    )
    pending_body = extract_block(session_ctrl, "fun setPendingSwitch(")
    checker.check(bool(pending_body), "定位 setPendingSwitch 实现")
    checker.check(
        "switchLocalSession" in pending_body,
        "setPendingSwitch 立即切换本地 session",
    )
    # ensureSessionForCurrentPersona 应优先采用待查看角色，避免被全局 active persona 冲回
    ensure_body = extract_block(session_ctrl, "suspend fun ensureSessionForCurrentPersona()")
    checker.check(
        "pendingSwitchFilename" in ensure_body,
        "ensureSessionForCurrentPersona 优先使用 pendingSwitchFilename",
    )

    # --- 修复点 4: flushManager 惰性初始化，规避 init 期 NPE ---
    print("\n修复点 4: flushManager 惰性初始化")
    checker.check(
        re.search(r"flushManager\s*:\s*ChatFlushManager\s+by\s+lazy", chat_vm) is not None,
        "ChatViewModel 的 flushManager 使用 by lazy（init 块先于属性声明执行）",
    )

    # --- 修复点 5: 状态恢复不覆盖已切换的会话 ---
    print("\n修复点 5: StateManager 恢复不覆盖当前会话")
    restore_body = extract_block(state_manager, "private fun restoreState()")
    checker.check(bool(restore_body), "定位 restoreState 实现")
    checker.check(
        "isNullOrBlank()" in restore_body,
        "restoreState 仅在无会话时兜底恢复 sessionId",
    )

    # --- 修复点 6: 列表预览归属以"消息自身 sessionId"为准（ChatIncomingMessageHandler） ---
    print("\n修复点 6: 会话列表预览归属以消息自身 sessionId 为准")
    update_body = extract_block(incoming, "fun updateLastMessagePreview(")
    checker.check(bool(update_body), "定位 updateLastMessagePreview 实现")
    checker.check(
        "personaFilenameFromSessionId(last.sessionId)" in update_body,
        "预览归属以消息自身的 sessionId 反推（权威，防切换竞态串写）",
    )
    checker.check(
        "personaFilenameFromSessionId(getSessionId())" in update_body,
        "消息无 sessionId 时回退当前 sessionId 反推",
    )
    checker.check(
        "getPersonaFilename()" in update_body,
        "反推失败时回退到 active persona（兼容非 web_ 老会话）",
    )
    # 回归防护：预览不得再把后端 active persona 当首选归属
    checker.check(
        "val filename = currentPersonaFilename" not in update_body,
        "预览归属不再首选 currentPersonaFilename（串台根因）",
    )

    # --- 修复点 7: ChatSessionController 提供 sessionId->persona 反推 ---
    print("\n修复点 7: sessionId -> persona filename 反推工具")
    checker.check(
        "fun personaFilenameFromSessionId" in session_ctrl,
        "ChatSessionController.personaFilenameFromSessionId 存在",
    )
    checker.check(
        '"web_"' in session_ctrl or "'web_'" in session_ctrl,
        "反推逻辑基于 web_ 前缀约定",
    )

    # --- 修复点 8: observeMessages 切换竞态防护（ChatSessionObserver） ---
    print("\n修复点 8: observeMessages 切换竞态防护（旧 flow 残留不串台）")
    observe_msgs_body = extract_block(session_observer, "private fun observeMessages()")
    checker.check(bool(observe_msgs_body), "定位 observeMessages 实现")
    checker.check(
        "expectedSessionId" in observe_msgs_body,
        "observeMessages 记录当前 flow 的 sessionId 用于归属校验",
    )
    checker.check(
        "messages = emptyList()" in observe_msgs_body,
        "切换会话时立即清空旧消息（不再先显示上一个角色记录）",
    )
    checker.check(
        "it.sessionId != expectedSessionId" in observe_msgs_body,
        "collect 丢弃不属于当前会话的残留消息（防串台上屏）",
    )
    checker.check(
        "return@collect" in observe_msgs_body,
        "残留消息不更新 uiState.messages 也不写预览",
    )
    # 回归防护：预览回调必须受归属校验保护
    checker.check(
        observe_msgs_body.find("onMessagesLoaded") > observe_msgs_body.find("return@collect"),
        "onMessagesLoaded 位于归属校验之后（残留消息不触发预览写入）",
    )

    # --- 拆分完整性: 新类不引用 ChatViewModel（避免循环依赖） ---
    print("\n拆分完整性: 新类不反向依赖 ChatViewModel")
    for path, name in (
        (SESSION_CONTROLLER, "ChatSessionController"),
        (INCOMING_HANDLER, "ChatIncomingMessageHandler"),
        (SESSION_OBSERVER, "ChatSessionObserver"),
        (SEND_CONTROLLER, "ChatSendController"),
    ):
        text = strip_block_comments(read(path, checker))
        checker.check(
            "ChatViewModel" not in text,
            f"{name} 不引用 ChatViewModel（无循环依赖）",
        )

    # --- 解耦: 消息流观察迁移到 ChatSessionObserver ---
    print("\n解耦: 消息流观察迁移到 ChatSessionObserver")
    checker.check(
        "fun observeMessages()" in session_observer,
        "ChatSessionObserver 持有 observeMessages（随会话切换加载历史）",
    )
    checker.check(
        "fun observeWebSocketMessages()" in session_observer,
        "ChatSessionObserver 持有 observeWebSocketMessages（WS 事件分发）",
    )
    checker.check(
        "private fun observeMessages()" not in chat_vm,
        "ChatViewModel 不再定义 observeMessages（避免重复监听）",
    )
    checker.check(
        "private fun observeWebSocketMessages()" not in chat_vm,
        "ChatViewModel 不再定义 observeWebSocketMessages",
    )
    # 发消息核心流程迁移到 ChatSendController
    print("\n解耦: 发消息核心流程迁移到 ChatSendController")
    checker.check(
        "fun sendMessage(" in send_controller,
        "ChatSendController 持有 sendMessage 实现",
    )
    send_body = extract_block(send_controller, "fun sendMessage(")
    checker.check(
        "consumePendingSwitchIfNeeded" in send_body,
        "sendMessage 内部消费 pendingSwitch（发消息才切后端 persona）",
    )
    checker.check(
        "setHttpStreamingActive" in send_body,
        "sendMessage 抑制 WS 双通道冲突",
    )
    # ChatViewModel 保持薄壳：仅转发 sendMessage
    # （转发为跨行写法 `fun sendMessage(...) =\n sendController.sendMessage`，
    #  strip 掉空白后匹配更稳健）
    checker.check(
        "sendController.sendMessage" in re.sub(r"\s+", "", chat_vm),
        "ChatViewModel.sendMessage 转发给 ChatSendController",
    )
    checker.check(
        "= sessionObserver.createNewSession" in chat_vm,
        "ChatViewModel.createNewSession 转发给 ChatSessionObserver",
    )

    print()
    return checker.report()


if __name__ == "__main__":
    sys.exit(main())
