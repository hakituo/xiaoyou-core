#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 start_scripts/ 下的批处理启动脚本不会被 cmd 解析坑绊住。

## 背景（实测结论，别改成别的写法）

cmd.exe 按「当前控制台代码页」解码 .bat 的行；文件里只要出现多字节（非 ASCII）字符，
读取位置就会漂移，**把后面的行截断**，症状是 `'ain.py' is not recognized` 这类少字母的报错。实测：

- 文件顶部写 `chcp 65001` 会触发（在文件中间切换代码页）；
- 存成 UTF-8 with BOM **无效**，照样漂移；
- 转成 GBK 且不写 chcp，在 UTF-8 控制台下也漂移；
- 因此唯一与代码页无关的稳法是 **bat 内容保持纯 ASCII**（`chcp 65001` 可以保留，
  它只负责让子窗口里的 Python 中文日志正常显示）。

另两个同类解析坑：

1. 括号块内部的 `echo` 里出现 ASCII 括号：`)` 会提前闭合 `if/else (...)` 块。
2. 括号块内部用 `::` 当注释：`::` 是标签写法，块内会被当非法标签，必须用 `rem`。

## 已知例外

`start_pet.bat` 第 43 行 `echo Waiting for port 3000... (%RETRY_COUNT%/%MAX_RETRIES%)`
里的括号是**承重**的：它提前闭合第 22 行的 `if %errorlevel% neq 0 (`，使后面的
`goto CHECK_PORT` 跳出块外、运行期才展开 `%RETRY_COUNT%`；直接删括号会让
`if %RETRY_COUNT% lss %MAX_RETRIES%` 在解析期展开成 `if lss goto CHECK_PORT`（报
`goto was unexpected at this time.`）。该文件既无 `chcp` 也无非 ASCII，不在本坑范围内，
故列入例外；要根治得把重试循环挪出 `if` 块（属结构改动，另行处理）。

用法：`venv_cpu\\Scripts\\python.exe tests\\scripts\\startup\\verify_start_scripts_batch_safety.py`
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "start_scripts"
TMP_PREFIX = "_verify_batch_safety_tmp_"

# 承重括号例外：见模块 docstring
BLOCK_ECHO_PAREN_EXCEPTIONS = {"start_pet.bat"}
# 重试循环依赖真实时序，不参与 dry-run
DRY_RUN_SKIP = {"start_pet.bat"}
# cmd 解析漂移的症状串（出现任一即判定为解析被截断）
DRIFT_MARKERS = (
    "is not recognized",
    "was unexpected at this time",
    "the filename, directory name, or volume label syntax is incorrect",
)

# dry-run 时把会真正拉起进程的行整行注释掉（只动副本）
NEUTRALIZE_PATTERN = re.compile(
    r"^(?P<indent>\s*)(?P<verb>start|call|timeout|pause|ping|npm|pip|node|npx|powershell|\"|%)",
    re.IGNORECASE,
)


def _strip_quoted(line: str) -> str:
    """去掉引号片段，便于近似统计括号（cmd 里引号内的括号不参与块划分）。"""
    return re.sub(r"'[^']*'", "", re.sub(r'"[^"]*"', "", line))


def _block_depths(lines: list[str]) -> list[int]:
    """返回每行行首处的括号嵌套深度，用于识别「该行位于括号块内部」。"""
    depths: list[int] = []
    depth = 0
    for line in lines:
        depths.append(depth)
        bare = _strip_quoted(line)
        depth = max(depth + bare.count("(") - bare.count(")"), 0)
    return depths


def _static_issues(path: Path) -> list[str]:
    """静态检查：纯 ASCII、块内 echo 不带括号、块内不用 `::` 注释、括号收尾闭合。"""
    data = path.read_bytes()
    issues: list[str] = []
    if data.startswith(b"\xef\xbb\xbf"):
        issues.append("带 UTF-8 BOM")
    non_ascii = [index for index, byte in enumerate(data) if byte > 127]
    if non_ascii:
        issues.append(f"含 {len(non_ascii)} 个非 ASCII 字节")

    lines = data.decode("utf-8", errors="replace").splitlines()
    depths = _block_depths(lines)
    allow_paren = path.name in BLOCK_ECHO_PAREN_EXCEPTIONS
    paren_lines: list[int] = []
    label_lines: list[int] = []
    for index, (line, depth) in enumerate(zip(lines, depths), start=1):
        if depth <= 0:
            continue
        stripped = line.strip()
        if stripped.lower().startswith("echo") and ("(" in stripped or ")" in stripped):
            paren_lines.append(index)
        if stripped.startswith("::"):
            label_lines.append(index)
    if paren_lines and not allow_paren:
        issues.append(f"块内 echo 含括号 行{paren_lines}")
    if label_lines:
        issues.append(f"块内 :: 注释 行{label_lines}")
    if depths and depths[-1] != 0:
        issues.append(f"文件结束时括号未闭合 depth={depths[-1]}")
    return issues


def _dry_run(path: Path) -> tuple[bool, str]:
    """把拉起进程的行注释掉，跑一遍副本，确认没有解析漂移症状。"""
    text = path.read_text(encoding="ascii")
    neutralized = "\n".join(
        f"{match.group('indent')}rem [DRY] {line.strip()}"
        if (match := NEUTRALIZE_PATTERN.match(line))
        else line
        for line in text.splitlines()
    )
    tmp_path = SCRIPTS_DIR / f"{TMP_PREFIX}{path.name}"
    tmp_path.write_text(neutralized, encoding="ascii", newline="\r\n")
    try:
        completed = subprocess.run(
            ["cmd", "/c", str(tmp_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    output = ((completed.stdout or "") + (completed.stderr or "")).lower()
    hits = [marker for marker in DRIFT_MARKERS if marker in output]
    detail = f"exit={completed.returncode}"
    if hits:
        detail += f", 命中漂移症状={hits}"
    return (not hits), detail


def main() -> None:
    targets = sorted(path for path in SCRIPTS_DIR.glob("*.bat"))
    if not targets:
        raise SystemExit(f"未找到任何批处理脚本: {SCRIPTS_DIR}")

    failures: list[str] = []
    for path in targets:
        issues = _static_issues(path)
        detail = "; ".join(issues) if issues else "静态检查通过"
        if issues:
            failures.append(f"{path.name}: {detail}")
        print(f"[{'FAIL' if issues else 'PASS'}] {path.name} 静态检查 -> {detail}")

        if path.name in DRY_RUN_SKIP:
            print(f"[SKIP] {path.name} dry-run（见模块 docstring 的承重括号例外）")
            continue
        ok, dry_detail = _dry_run(path)
        if not ok:
            failures.append(f"{path.name}: dry-run {dry_detail}")
        print(f"[{'PASS' if ok else 'FAIL'}] {path.name} dry-run -> {dry_detail}")

    if failures:
        raise SystemExit("start_scripts 批处理安全检查失败:\n  " + "\n  ".join(failures))

    print("start_scripts 批处理安全检查通过。")


if __name__ == "__main__":
    sys.exit(main())
