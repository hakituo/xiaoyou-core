# -*- coding: utf-8 -*-
"""验证背单词评分按钮乐观更新改造是否成功，供本地手动运行。

背景：原实现点 Again/Hard/Good/Easy 会先等后端 /vocab/review 返回才切卡，
导致 1~2 秒卡顿。改造后改为「点击立即切卡 + 后台同步」。

用法（在项目根）：
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\study\\verify_vocab_optimistic_review.py

检查项：
1. 静态结构：submitReview 内卡片状态推进（currentCardIndex/learnWords 更新）必须
   出现在网络调用（studyRepository.submitReview）之前，且网络调用仍在（未删同步）。
2. 静态结构：会话统计（sessionStats）只应在网络响应的 onSuccess 里更新。
3. 可选运行 Android 单元测试 StudyVocabReviewManagerOptimisticTest，
   覆盖「后端未响应时卡片已切卡」「Again 重排」「最后一张卡结束会话」。
"""
import os
import subprocess
import sys

KOTLIN_FILE = os.path.join(
    "clients", "frontend", "aveline-android", "android", "app", "src", "main",
    "java", "com", "aveline", "ai", "mobile", "presentation", "study",
    "StudyVocabReviewManager.kt",
)
TEST_CLASS = "com.aveline.ai.mobile.presentation.study.StudyVocabReviewManagerOptimisticTest"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def check_structure() -> list:
    """静态结构检查：本地切卡必须在网络调用之前，且后台同步仍存在。"""
    problems = []
    path = os.path.join(ROOT, KOTLIN_FILE)
    if not os.path.exists(path):
        return [f"Kotlin 文件不存在: {path}"]

    with open(path, encoding="utf-8") as f:
        src = f.read()

    # 提取 submitReview 函数体（乐观更新改造范围）
    start = src.find("fun submitReview(quality: Int)")
    if start < 0:
        return ["未找到 submitReview 函数"]
    end = src.find("fun finishSession()")
    if end < 0:
        end = len(src)
    body = src[start:end]

    # 1) 网络调用位置（scope.launch 内 studyRepository.submitReview）
    net_pos = body.find("studyRepository.submitReview(currentWord.word, quality)")
    if net_pos < 0:
        problems.append("未找到后台同步调用 studyRepository.submitReview（同步被删？）")

    # 2) 本地切卡位置（currentCardIndex 更新）
    idx_pos = body.find("currentCardIndex = currentIdx + 1")
    if idx_pos < 0:
        problems.append("未找到本地切卡逻辑 currentCardIndex = currentIdx + 1")

    # 3) 切卡必须发生在网络调用之前（乐观更新核心）
    if net_pos >= 0 and idx_pos >= 0 and idx_pos > net_pos:
        problems.append(
            "切卡逻辑出现在网络调用之后：说明仍会等后端返回才切卡（改造失败）"
        )

    # 4) sessionStats 只应在网络 onSuccess 中更新
    stats_sync = body.find("vocabState.update { it.copy(sessionStats = sessionStats) }")
    stats_before_net = stats_sync >= 0 and net_pos >= 0 and stats_sync < net_pos
    if stats_before_net:
        problems.append("sessionStats 在网络调用之前同步更新（不符合后台刷新的预期）")

    return problems


def run_gradle_test() -> tuple:
    """运行 Android 单元测试，返回 (ok, output)。"""
    android_dir = os.path.join(ROOT, "clients", "frontend", "aveline-android", "android")
    gradlew = "gradlew.bat" if sys.platform.startswith("win") else "gradlew"
    cmd = [
        os.path.join(android_dir, gradlew),
        "testDebugUnitTest",
        "--tests",
        TEST_CLASS,
        "--console=plain",
        "-q",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=android_dir, capture_output=True, text=True, timeout=1800
        )
        return proc.returncode == 0, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return False, "gradle 测试超时（30 分钟）"
    except FileNotFoundError as e:
        return False, f"无法执行 gradlew: {e}"


def main() -> int:
    problems = check_structure()
    if problems:
        print("静态检查失败项:")
        for p in problems:
            print("  -", p)
        return 1
    print("静态检查通过: 本地切卡先于网络调用、后台同步保留、统计仅在响应后刷新")

    if "--skip-test" in sys.argv:
        print("已跳过 Android 单元测试（--skip-test）")
        return 0

    print(f"运行 Android 单元测试 {TEST_CLASS} ...")
    ok, output = run_gradle_test()
    if not ok:
        print("单元测试失败，输出:")
        print(output[-4000:])
        return 1
    print("单元测试通过: 乐观切卡 / Again 重排 / 最后一张卡结束会话 均符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
