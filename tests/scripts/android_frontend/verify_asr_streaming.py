"""验证聊天页语音输入（ASR）是"边说边出字"的流式体验，而不是说完才出结果。

需求：
1. 录音过程中把 ASR 的流式中间结果实时上屏（转写条），不用等说完；
2. 断句（endpoint）后已识别的内容不能丢，停止录音时要拿到完整文本。

对应实现：
- SherpaNcnnAsrEngine：新增 committedText 累积已断句文本，partialText 恒为
  "已确认句 + 当前句"；endpoint 命中时**先累积再 reset**（顺序反了这句就丢了）；
  stopListening 结果改用 combineText 拼接，不再只返回最后一句；
- VoiceInputManager：开录前清空上一轮中间态；partialText/amplitude 转发协程并入
  同一个 job（原来每次开录都新起一组 collector，属于协程泄漏）；
- ChatInputBars：新增 ChatVoiceTranscribingBar（波形 + 实时文本 + 停止按钮）；
- ChatScreen：录音中 / Processing 阶段渲染转写条，绑定 voicePartialText / voiceAmplitude；
- ChatVoiceInputController：最终结果落进输入框后清空 voicePartialText。

运行：d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe tests/scripts/android_frontend/verify_asr_streaming.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_MAIN = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
SHERPA_ENGINE = APP_MAIN / "services/SherpaNcnnAsrEngine.kt"
VOICE_MANAGER = APP_MAIN / "services/VoiceInputManager.kt"
CHAT_DIR = APP_MAIN / "presentation/chat"
CHAT_INPUT_BARS = CHAT_DIR / "ChatInputBars.kt"
CHAT_SCREEN = CHAT_DIR / "ChatScreen.kt"
# 底部区域（含转写条接线）在 2026-09-24 从 ChatScreen 拆到 ChatBottomArea.kt，检查点跟着搬家
CHAT_BOTTOM_AREA = CHAT_DIR / "ChatBottomArea.kt"
CHAT_VOICE_CONTROLLER = CHAT_DIR / "ChatVoiceInputController.kt"
CHAT_VIEW_MODEL = CHAT_DIR / "ChatViewModel.kt"

IMPORT_RE = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$")
# Kotlin 属性委托（`val x by y`）会隐式调用 getValue/setValue，正文里搜不到名字，不算未使用
DELEGATE_IMPORTS = (
    "import androidx.compose.runtime.getValue",
    "import androidx.compose.runtime.setValue",
)


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def find_unused_imports(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    body = "\n".join(
        line
        for line in lines
        if not line.startswith("import ") and not line.startswith("package ")
    )
    unused: list[str] = []
    for line in lines:
        if not line.startswith("import ") or line.strip() in DELEGATE_IMPORTS:
            continue
        matched = IMPORT_RE.match(line)
        if not matched:
            continue
        fq_name, alias = matched.group(1), matched.group(2)
        if fq_name.endswith("*"):
            continue
        name = alias or fq_name.rsplit(".", 1)[-1]
        if not re.search(r"\b" + re.escape(name) + r"\b", body):
            unused.append(line)
    return unused


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("聊天页 ASR 流式输出验证")
    print("=" * 70)

    engine = SHERPA_ENGINE.read_text(encoding="utf-8")
    manager = VOICE_MANAGER.read_text(encoding="utf-8")
    bars = CHAT_INPUT_BARS.read_text(encoding="utf-8")
    screen = CHAT_SCREEN.read_text(encoding="utf-8")
    bottom_area = CHAT_BOTTOM_AREA.read_text(encoding="utf-8")
    controller = CHAT_VOICE_CONTROLLER.read_text(encoding="utf-8")
    view_model = CHAT_VIEW_MODEL.read_text(encoding="utf-8")

    # 1. 引擎层：断句累积，流式文本不丢字
    results.append(
        _check(
            "private var committedText" in engine and "fun combineText(" in engine,
            "SherpaNcnnAsrEngine 累积已断句文本并提供 combineText 拼接",
        )
    )
    results.append(
        _check(
            "val combined = combineText(text)" in engine
            and "_partialText.value = combined" in engine,
            "partialText 输出的是「已确认句 + 当前句」的完整流式文本",
        )
    )

    # endpoint 必须先累积再 reset：reset 之后 recognizer.text 会变空
    commit_pos = engine.find("committedText = combineText(text)")
    reset_pos = engine.find("recognizer?.reset(recreate = false)", commit_pos)
    results.append(
        _check(
            commit_pos != -1 and reset_pos != -1 and commit_pos < reset_pos,
            "endpoint 命中时先累积当前句、后 reset（顺序反了会丢句）",
        )
    )

    results.append(
        _check(
            "combineText(recognizer?.text ?: \"\")" in engine,
            "stopListening 返回完整文本（已确认句 + 最后一句），不再只剩最后一句",
        )
    )
    results.append(
        _check(
            engine.count('committedText = ""') >= 3,
            "开始录音 / cancel / reset 都会清空 committedText（3 处）",
        )
    )

    # 2. VoiceInputManager：中间态清理 + collector 不泄漏
    results.append(
        _check(
            "开录前清空上一轮的中间态" in manager,
            "VoiceInputManager 开录前清空 partialText/amplitude（避免降级通道带回上次文本）",
        )
    )
    results.append(
        _check(
            manager.count("sherpaObserverJob = scope.launch {") == 1
            and "sherpaNcnnEngine.partialText.collect" in manager,
            "partialText/amplitude 转发协程挂在 sherpaObserverJob 上（不再每次开录新起一组）",
        )
    )

    # 3. UI 层：流式中间结果显示到转写条
    results.append(
        _check(
            "fun ChatVoiceTranscribingBar(" in bars,
            "ChatInputBars 提供语音实时转写条 ChatVoiceTranscribingBar",
        )
    )
    results.append(
        _check(
            "AudioWaveform(" in bars and "partialText.isNotBlank()" in bars,
            "转写条展示实时文本并带音量波形",
        )
    )
    results.append(
        _check(
            "ChatVoiceTranscribingBar(" in bottom_area
            and "partialText = uiState.voicePartialText" in bottom_area
            and "amplitude = uiState.voiceAmplitude" in bottom_area
            and "ChatBottomArea(" in screen,
            "聊天页把 voicePartialText / voiceAmplitude 接到转写条（流式上屏）",
        )
    )
    results.append(
        _check(
            "uiState.isRecording" in bottom_area
            and "uiState.voiceInputState is VoiceInputState.Processing" in bottom_area,
            "录音中与收尾识别阶段都显示转写条",
        )
    )
    results.append(
        _check(
            "onStop = onStopVoice" in bottom_area
            and "onStopVoice = { viewModel.stopVoiceRecording() }" in screen,
            "转写条可直接停止录音（与点麦克风是同一个动作）",
        )
    )

    # 4. 最终结果落地后清掉中间态，且 Singleton 状态归零（防旧文本重放回输入框）
    results.append(
        _check(
            "voicePartialText = \"\"" in controller,
            "ChatVoiceInputController 在 Result 后清空 voicePartialText",
        )
    )
    results.append(
        _check(
            "voiceInputManager.reset()" in controller,
            "Result 消费后立即重置 VoiceInputManager（Singleton StateFlow 不归零会重放旧识别文本）",
        )
    )
    results.append(
        _check(
            "sherpaNcnnEngine.reset()" in manager,
            "VoiceInputManager.reset() 连 sherpa 引擎状态一起重置",
        )
    )
    results.append(
        _check(
            "voiceInputController.cancelRecording()" in view_model,
            "ChatViewModel.onCleared 用 cancelRecording 丢弃未消费的识别结果",
        )
    )

    # 5. 没有留下未使用 import
    unused: list[str] = []
    for path in (SHERPA_ENGINE, VOICE_MANAGER, CHAT_INPUT_BARS, CHAT_SCREEN, CHAT_BOTTOM_AREA, CHAT_VOICE_CONTROLLER, CHAT_VIEW_MODEL):
        for line in find_unused_imports(path):
            unused.append(f"{path.name}: {line}")
    results.append(
        _check(
            not unused,
            "相关文件无未使用 import"
            + ("" if not unused else "，实际：\n    " + "\n    ".join(unused)),
        )
    )

    print("\n" + "-" * 70)
    for ok, msg in results:
        print(msg)
    failed = [msg for ok, msg in results if not ok]
    print("-" * 70)
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        for msg in failed:
            print(f"  {msg}")
        return 1
    print("全部通过：录音中实时上屏中间文本，断句不丢字，停止后完整文本落进输入框。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
