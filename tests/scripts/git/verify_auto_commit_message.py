"""验证 auto_commit_push.py 的提交信息生成策略：更新日志详细、commit 一句话。

检查点：
1. commit 就是一句话：`--message` 给什么就用什么，不加前缀、不加文件数
2. 文件清单不进 commit（git show --stat 本来就能看到）
3. 未给摘要时退化为模块摘要（如 `更新 core、tests 相关文件`）
4. 超长摘要被截断，摘要过长也不会破坏单行格式
5. 空摘要 + 空文件清单仍有兜底文案
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "git" / "auto_commit_push.py"


def load_module():
    spec = importlib.util.spec_from_file_location("auto_commit_push", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(name: str, passed: bool, detail: str) -> bool:
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    return passed


def main() -> int:
    module = load_module()
    results: list[bool] = []

    sample = [
        "core/services/study/service.py",
        "core/services/study/session.py",
        "core/tools/study/english/quiz.py",
        "routers/v1/vocab.py",
        "UPDATES.md",
    ]

    # 1) 传入摘要：原样使用，就是一句话
    message = module.build_commit_message(sample, "背单词接入 FSRS 调度")
    results.append(record(
        "一句话提交",
        message == "背单词接入 FSRS 调度\n" and not message.startswith("auto:"),
        repr(message),
    ))

    # 2) 文件清单不进 commit
    results.append(record(
        "不含文件清单",
        all(path not in message for path in sample) and "文件）" not in message,
        "commit 里没有文件路径与文件计数",
    ))

    # 3) 未给摘要：退化为模块摘要
    auto_message = module.build_commit_message(sample)
    results.append(record(
        "缺省模块摘要",
        auto_message == "更新 core、routers、根目录 相关文件\n",
        repr(auto_message),
    ))

    # 4) 超长摘要截断且保持单行
    long_message = module.build_commit_message(sample, "很" * 200)
    results.append(record(
        "超长摘要截断",
        long_message.count("\n") == 1 and long_message.endswith("…\n")
        and len(long_message) <= module.COMMIT_SUMMARY_MAX + 1,
        f"{len(long_message) - 1} 字符",
    ))

    # 5) 空清单兜底
    empty_message = module.build_commit_message([])
    results.append(record(
        "空变更兜底",
        empty_message == "日常自动提交\n",
        repr(empty_message),
    ))

    passed = all(results)
    print("-" * 60)
    print(f"结果: {'PASS' if passed else 'FAIL'}（{sum(results)}/{len(results)}）")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
