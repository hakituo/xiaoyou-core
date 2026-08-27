# -*- coding: utf-8 -*-
"""静态验证 Android 背单词未完成会话可跨 App 重启恢复。

用法（项目根目录）：
    .\venv_core\Scripts\python.exe tests\scripts\study\verify_vocab_session_persistence.py

本脚本不调用 Gradle，避免与 Android Studio 争用缓存锁。真机验证步骤见输出。
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STUDY_DIR = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
    / "presentation/study"
)


def require(source: str, marker: str, problem: str, problems: list[str]) -> None:
    """要求源码包含关键标记。"""
    if marker not in source:
        problems.append(problem)


def main() -> int:
    problems: list[str] = []
    store_path = STUDY_DIR / "StudyVocabSessionStore.kt"
    manager_path = STUDY_DIR / "StudyVocabReviewManager.kt"
    view_model_path = STUDY_DIR / "StudyViewModel.kt"

    for path in (store_path, manager_path, view_model_path):
        if not path.exists():
            problems.append(f"缺少文件: {path.relative_to(ROOT)}")
    if problems:
        return report(problems)

    store = store_path.read_text(encoding="utf-8")
    manager = manager_path.read_text(encoding="utf-8")
    view_model = view_model_path.read_text(encoding="utf-8")

    for marker, problem in (
        ("val learnWords: List<DailyWord>", "快照未保存动态卡片队列"),
        ("val currentCardIndex: Int", "快照未保存当前卡片索引"),
        ("val redoCounts: Map<String, Int>", "快照未保存三轮强化计数"),
        ("val reviewResults: List<ReviewResultItem>", "快照未保存本轮会/不会结果"),
        ("context.getSharedPreferences", "快照未写入 App 私有持久化存储"),
        ("json.encodeToString", "快照没有序列化写入"),
        ("json.decodeFromString", "快照没有反序列化恢复"),
    ):
        require(store, marker, problem, problems)

    require(
        manager,
        "fun restoreUnfinishedSession(): Boolean",
        "复习管理器缺少冷启动恢复入口",
        problems,
    )
    if manager.count("persistUnfinishedSession()") < 3:
        problems.append("正常切卡与 Again 重排后没有同时保存快照")
    require(manager, "sessionStore?.clear()", "完成会话后没有清理快照", problems)
    require(
        manager,
        "current.isNewWordsMode &&",
        "背新词入口不能从未完成快照续背",
        problems,
    )

    restore_pos = view_model.find("restoreUnfinishedSession()")
    load_pos = view_model.find("loadLearnWords()", restore_pos)
    if restore_pos < 0 or load_pos < 0 or restore_pos > load_pos:
        problems.append("StudyViewModel 冷启动没有先恢复快照再决定是否拉取远端列表")

    return report(problems)


def report(problems: list[str]) -> int:
    """输出验证结果。"""
    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("静态验证通过: 未完成队列、索引、Again 次数和本轮结果均可跨 App 重启恢复。")
    print("真机复验: 点 Again -> 强退 App -> 重开 -> 进入同一背词入口，应从下一张继续且该词稍后再次出现。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
