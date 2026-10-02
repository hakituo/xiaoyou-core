r"""验证 auto_commit_push 的重复提交保护。

背景：把「追加写文件」和「提交」写在同一条命令里时，命令若被重跑一次
（例如沙箱拦截后提升权限重跑），追加内容会写两遍、同一批改动也会提交两次。
保护口径：提交说明相同 且 本次文件是上一次提交文件的子集 -> 跳过。

运行：
    D:\projects\xiaoyou\venv_core\Scripts\python.exe -m tests.scripts.git.verify_auto_commit_duplicate_guard
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_FAILED: list[str] = []

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.git.auto_commit_push import _is_duplicate_of_last_commit  # noqa: E402


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    _FAILED.append(msg)


def _mock_git(last_subject: str, last_files: list[str]):
    """构造假的 run_cmd：按命令返回上次提交信息。"""

    def _run(cmd, cwd=None, timeout=30, env=None):
        if "log" in cmd:
            return 0, last_subject, ""
        if "show" in cmd:
            return 0, "\n".join(last_files), ""
        return 0, "", ""

    return _run


def test_detects_repeat_run() -> None:
    print("\n=== 测试 1: 命令重跑（说明相同、文件是上次的子集）-> 判定重复 ===")
    run = _mock_git(
        "数字健康关怀加一次同步单条与跨应用全局节流",
        ["core/a.py", "docs/updates/2026/09/2026-09-19.md", ".trae/memory/2026-09-19.md"],
    )
    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=run):
        dup = _is_duplicate_of_last_commit(
            "数字健康关怀加一次同步单条与跨应用全局节流",
            [".trae/memory/2026-09-19.md"],
        )
    if dup:
        _ok("识别为重跑")
    else:
        _fail("未能识别重跑")


def test_allows_different_message() -> None:
    print("\n=== 测试 2: 提交说明不同 -> 不算重复 ===")
    run = _mock_git("上一次的说明", ["a.py", "b.py"])
    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=run):
        dup = _is_duplicate_of_last_commit("这次是新说明", ["a.py"])
    if not dup:
        _ok("说明不同则放行")
    else:
        _fail("说明不同却被拦下")


def test_allows_new_files() -> None:
    print("\n=== 测试 3: 含上次没有的新文件 -> 不算重复 ===")
    run = _mock_git("同一个说明", ["a.py"])
    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=run):
        dup = _is_duplicate_of_last_commit("同一个说明", ["a.py", "new_file.py"])
    if not dup:
        _ok("出现新文件则放行")
    else:
        _fail("有新文件却被拦下")


def test_empty_change_list() -> None:
    print("\n=== 测试 4: 空变更清单 -> 不算重复（交给上层处理） ===")
    run = _mock_git("同一个说明", ["a.py"])
    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=run):
        dup = _is_duplicate_of_last_commit("同一个说明", [])
    if not dup:
        _ok("空清单不误判")
    else:
        _fail("空清单被误判为重复")


def main() -> int:
    print("=" * 64)
    print("auto_commit_push 重复提交保护验证")
    print("=" * 64)
    test_detects_repeat_run()
    test_allows_different_message()
    test_allows_new_files()
    test_empty_change_list()
    print("=" * 64)
    if _FAILED:
        print(f"失败 {len(_FAILED)} 项：" + "、".join(_FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
