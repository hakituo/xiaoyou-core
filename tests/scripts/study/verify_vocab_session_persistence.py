# -*- coding: utf-8 -*-
"""静态验证 Android 背单词未完成会话可跨 App 重启恢复，且不会被远端列表冲掉。

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
    state_path = STUDY_DIR / "VocabUiState.kt"

    for path in (store_path, manager_path, view_model_path, state_path):
        if not path.exists():
            problems.append(f"缺少文件: {path.relative_to(ROOT)}")
    if problems:
        return report(problems)

    store = store_path.read_text(encoding="utf-8")
    manager = manager_path.read_text(encoding="utf-8")
    view_model = view_model_path.read_text(encoding="utf-8")
    state = state_path.read_text(encoding="utf-8")

    for marker, problem in (
        ("const val CURRENT_VERSION = 4", "旧版错误复习队列快照没有失效"),
        ("val date: String", "快照未记录所属业务日期"),
        ("fun isValid(today: String)", "快照校验没有带上「今天」参数"),
        ("date == today", "跨天的残留快照仍会被恢复"),
        ("version == CURRENT_VERSION", "恢复快照时没有校验数据版本"),
        ("val learnWords: List<DailyWord>", "快照未保存动态卡片队列"),
        ("val currentCardIndex: Int", "快照未保存当前卡片索引"),
        ("val redoCounts: Map<String, Int>", "快照未保存三轮强化计数"),
        ("val reviewResults: List<ReviewResultItem>", "快照未保存本轮会/不会结果"),
        ("context.getSharedPreferences", "快照未写入 App 私有持久化存储"),
        ("json.encodeToString", "快照没有序列化写入"),
        ("json.decodeFromString", "快照没有反序列化恢复"),
        ("LocalDate.now()", "快照日期没有取设备本地时区"),
    ):
        require(store, marker, problem, problems)

    for marker, problem in (
        ("val sessionDate: String", "本地队列未记录所属业务日期"),
    ):
        require(state, marker, problem, problems)

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
        "current.isNewWordsMode",
        "背新词入口不能从未完成快照续背",
        problems,
    )
    # 中途退出后，Again 重排到队尾的错词必须还在本地队列里：切 Tab 触发的
    # loadLearnWords() 不能再用远端当天批次覆盖本地断点。
    require(
        manager,
        "private fun hasPendingQueue(state: VocabUiState): Boolean",
        "缺少「本地还有未走完队列」的判定",
        problems,
    )
    load_start = manager.find("fun loadLearnWords(")
    load_guard = manager.find("hasPendingQueue(vocabState.value)", load_start)
    load_fetch = manager.find("getDailyVocabulary(0, order)", load_start)
    if load_start < 0 or load_guard < 0 or load_fetch < 0 or load_guard > load_fetch:
        problems.append("loadLearnWords 会用远端列表覆盖未完成的本地队列（错词重排会丢）")
    if "state.sessionDate == todayKey()" not in manager:
        problems.append("未完成队列没有做跨天失效，昨天的残留列表会锁死今天的刷新")
    if manager.count("sessionDate = todayKey()") < 2:
        problems.append("开新会话时没有记录会话日期")
    if "sessionDate = \"\"" not in manager:
        problems.append("会话收尾后没有清空会话日期，远端刷新会被一直拦截")

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

    print("静态验证通过: 旧错误快照已失效，未完成队列既不被远端列表覆盖，也不会跨天残留。")
    print("真机复验: 背几张后按返回键退出 -> 切走再切回背单词 Tab -> 列表不应被远端批次替换；")
    print("         点开始复习应从下一张继续，且 Again 的错词稍后再次出现；再强退 App 重开同样从断点继续。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
