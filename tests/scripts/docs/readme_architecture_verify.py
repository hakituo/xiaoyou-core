#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 README.md 与 static/demo/architecture.svg 架构图一致性。

检查项：
1. README.md 包含有效的 mermaid 代码块；
2. Mermaid 图中包含预期的分层与关键模块；
3. static/demo/architecture.svg 存在且包含对应关键文本；
4. SVG 基础格式合法（以 <svg 开头、</svg> 结尾）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README_PATH = ROOT / "readme.md"
SVG_PATH = ROOT / "static" / "demo" / "architecture.svg"

EXPECTED_MERMAID_KEYWORDS = [
    "客户端层 Clients",
    "接口层 Interface / Routers",
    "核心层 Core",
    "记忆层 Memory",
    "调度层 Scheduler",
    "存储层 Storage",
    "AvelineService",
    "ActiveCare",
    "PersonaSystem",
    "OpenAI Compatible",
    "Obsidian",
    "ChromaDB",
    "Redis L2 Cache",
]

EXPECTED_SVG_KEYWORDS = [
    "客户端层 Clients",
    "接口层 Interface / Routers",
    "核心层 Core",
    "记忆层 Memory",
    "调度层 Scheduler",
    "存储层 Storage",
    "AvelineService",
    "ActiveCare",
    "PersonaSystem / Prompt",
    "/v1 OpenAI Compatible",
    "Obsidian",
    "ChromaDB",
    "Redis L2 Cache",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_mermaid_block(readme: str) -> tuple[bool, str]:
    pattern = r"```mermaid\s*\n(.*?)\n```"
    match = re.search(pattern, readme, re.DOTALL)
    if not match:
        return False, "README.md 中未找到 ```mermaid ... ``` 代码块"
    mermaid = match.group(1)
    missing = [kw for kw in EXPECTED_MERMAID_KEYWORDS if kw not in mermaid]
    if missing:
        return False, f"Mermaid 图中缺少关键字: {missing}"
    return True, f"Mermaid 图包含全部 {len(EXPECTED_MERMAID_KEYWORDS)} 个预期关键字"


def check_svg(svg: str) -> tuple[bool, str]:
    if not svg.strip().startswith("<?xml"):
        return False, "SVG 文件缺少 XML 声明"
    if "<svg" not in svg or "</svg>" not in svg:
        return False, "SVG 文件格式不合法"
    missing = [kw for kw in EXPECTED_SVG_KEYWORDS if kw not in svg]
    if missing:
        return False, f"SVG 图中缺少关键字: {missing}"
    return True, f"SVG 文件格式合法且包含全部 {len(EXPECTED_SVG_KEYWORDS)} 个预期关键字"


def main() -> int:
    errors: list[str] = []

    if not README_PATH.exists():
        errors.append(f"README 文件不存在: {README_PATH}")
        print("\n".join(errors))
        return 1

    if not SVG_PATH.exists():
        errors.append(f"SVG 文件不存在: {SVG_PATH}")

    readme = read_text(README_PATH)
    ok, msg = check_mermaid_block(readme)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    if not ok:
        errors.append(msg)

    if SVG_PATH.exists():
        svg = read_text(SVG_PATH)
        ok, msg = check_svg(svg)
        print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
        if not ok:
            errors.append(msg)

    if errors:
        print("\n验证失败，请检查架构图内容。")
        return 1

    print("\n所有架构图验证通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
