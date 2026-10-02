"""静态校验 Android 聊天生成已脱离 ChatViewModel 生命周期。

仅做源码级回归检查，不执行 Gradle：
1. 点发送后的准备阶段和 SSE 生成都必须运行在进程级后台 CoroutineScope；
2. 最终 AI 消息必须直接由后台生成协程写入 Room；
3. 页面销毁后 UI/TTS 更新必须停止，不能继续操作旧页面；
4. 图片/视频结果落库不能再依赖 viewModelScope；
5. 后台生成完成后必须同步会话列表预览元数据；
6. 重进聊天时必须继承进程级 HTTP 流状态，继续抑制 WS 双通道重复回复。
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SEND_SOURCE = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/chat/ChatSendController.kt"
)
VIEW_MODEL_SOURCE = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/chat/ChatViewModel.kt"
)


def main() -> None:
    send_text = SEND_SOURCE.read_text(encoding="utf-8")
    view_model_text = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

    required = {
        "进程级后台作用域": "CoroutineScope(SupervisorJob() + Dispatchers.IO)",
        "发送入口后台化": "fun sendMessage(\n",
        "后台启动生成": "backgroundGenerationScope.launch",
        "独立生成函数": "private suspend fun runAssistantGeneration(",
        "UI 生命周期守卫": "scope.coroutineContext[Job]?.isActive == true",
        "主线程 UI 守卫": "withContext(Dispatchers.Main.immediate)",
        "最终消息直接落库": "val result = chatRepository.insertMessage(finalMessage)",
        "图片消息直接落库": "val result = chatRepository.insertMessage(imageMessage)",
        "视频消息直接落库": "val result = chatRepository.insertMessage(videoMessage)",
        "后台更新会话预览": "persistConversationPreview(finalMessage, personaFilename)",
        "预览仓库写入": "personaLocalMetaRepository.updateLastMessage(",
        "全局 HTTP 流状态": "val backgroundHttpStreamingActive: StateFlow<Boolean>",
        "HTTP 流计数开始": "markHttpStreamStarted()",
        "HTTP 流计数结束": "markHttpStreamFinished()",
    }
    missing = [name for name, marker in required.items() if marker not in send_text]
    if missing:
        raise SystemExit(f"后台聊天生成回归失败，缺少: {', '.join(missing)}")

    send_body = send_text.split("fun sendMessage(", 1)[1].split("/** 编辑某个用户请求", 1)[0]
    if "backgroundGenerationScope.launch" not in send_body:
        raise SystemExit("后台聊天生成回归失败：sendMessage 入口仍未脱离页面生命周期")
    if "scope.launch" in send_body:
        raise SystemExit("后台聊天生成回归失败：sendMessage 入口仍残留 viewModelScope 启动")

    vm_required = {
        "预览仓库接线": "personaLocalMetaRepository = personaLocalMetaRepository",
        "重进页面同步 HTTP 流": "observeBackgroundHttpStreaming()",
        "读取全局流状态": "ChatSendController.backgroundHttpStreamingActive.collect",
        "同步到 flushManager": "flushManager.setHttpStreamingActive(active)",
    }
    vm_missing = [name for name, marker in vm_required.items() if marker not in view_model_text]
    if vm_missing:
        raise SystemExit(f"后台聊天生成回归失败，ChatViewModel 缺少: {', '.join(vm_missing)}")

    send_controller_block = view_model_text.split(
        "private val sendController = ChatSendController(", 1
    )[1].split("private val uploadHelper", 1)[0]
    if "generateMessageId = { generateMessageId() }" in send_controller_block:
        raise SystemExit("后台聊天生成回归失败：ChatSendController 仍依赖非线程安全 ViewModel 消息计数器")

    forbidden = {
        "最终消息仍绑 viewModelScope": "scope.launch(Dispatchers.IO) {\n            chatRepository.insertMessage(finalMessage)",
        "图片消息仍绑 viewModelScope": "scope.launch(Dispatchers.IO) {\n                            runCatching { chatRepository.insertMessage(imageMessage)",
        "视频消息仍绑 viewModelScope": "scope.launch(Dispatchers.IO) {\n                            runCatching { chatRepository.insertMessage(videoMessage)",
    }
    found = [name for name, marker in forbidden.items() if marker in send_text]
    if found:
        raise SystemExit(f"后台聊天生成回归失败，发现旧实现: {', '.join(found)}")

    print("OK: Android 聊天发送可立即离开页面，并继续持久化回复/预览且避免双通道重复")


if __name__ == "__main__":
    main()
