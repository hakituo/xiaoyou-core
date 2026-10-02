#!/usr/bin/env python3
"""验证 publish_public.py 发布流程是否成功（隐私零残留 + 白名单正确性）。

检查项：
    1. 发布脚本以退出码 0 完成（内置残留扫描门禁通过）
    2. 敏感文件未被复制（人设 configs / scene 工具 / 敏感配置等）
    3. 内容替换生效（真实姓名/QQ号 → 占位值）
    4. 敏感数据文件的占位桩存在且可编译（导入链完整）
    5. 白名单核心内容存在（入口/核心层/C++模块/记忆系统/文档）

用法（在仓库根目录运行）：
    venv_cpu python tests/scripts/publish/verify_publish_public.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLISH_SCRIPT = PROJECT_ROOT / "scripts" / "publish" / "publish_public.py"

# 必须不存在的敏感文件/目录（相对路径，目录用前缀判断）
FORBIDDEN_PATHS = [
    "core/character/configs",
    "core/tools/scene_tool.py",
    "core/agents/chat_agent_components/persona_system/prompt/peer_chat_script_system.txt",
    "clients/bots/qq/sensitive_paths.py",
    "clients/bots/telegram/sensitive_media.py",
    "config/yaml/character_daily_sensitive.yaml",
    "tests/unit/test_sensitive_mode.py",
]

# 必须存在的白名单核心内容
REQUIRED_PATHS = [
    "main.py",
    "readme.md",
    "UPDATES.md",
    "docs/updates/README.md",
    "requirements/base.txt",
    "cpp_modules/cpp_scheduler/main.cpp",
    "memory/weighted_memory_manager.py",
    "core/core_engine/event_bus.py",
    "routers/openai_compat.py",
    "clients/frontend/aveline-web/src/Aveline.tsx",
    ".gitignore",
]

# 必须存在的占位桩（被代码引用的敏感数据文件）
REQUIRED_STUBS = [
    "memory/core/taxonomy.py",
    "core/agents/chat_agent_components/persona_system/prompt/components/detailed_persona.py",
    "core/agents/chat_agent_components/persona_system/prompt/dialogue_examples.py",
]

# 内容替换抽查（文件, 应存在的替换后值, 应消失的真实值）
REPLACEMENT_SPOT_CHECKS = [
    ("routers/v1/peer_chat.py", '"Ling"', "Ling"),
    ("config/yaml/app.yaml", "Master", "Master"),
]

# 独立复扫的禁止字符串（与白名单配置一致，双保险）
FORBIDDEN_STRINGS = ["Master", "Master", "Ling", "123456789", "Kafka", "Frost", "Mian", "Chiba"]


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    global _ALL_PASS
    _ALL_PASS = False


_ALL_PASS = True


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    with tempfile.TemporaryDirectory(prefix="xiaoyou_publish_") as tmp:
        target = Path(tmp) / "public"
        print(f"[1/5] 执行发布到临时目录: {target}")
        result = subprocess.run(
            [sys.executable, str(PUBLISH_SCRIPT), "--target", str(target)],
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            print(result.stdout.decode("utf-8", errors="replace"))
            print(result.stderr.decode("utf-8", errors="replace"))
            print("[FAIL] 发布脚本退出码非 0（残留扫描门禁未通过或脚本异常）")
            return 1
        print("  [PASS] 发布脚本退出码 0")

        print("[2/5] 检查敏感文件未被复制")
        for rel in FORBIDDEN_PATHS:
            if (target / rel).exists():
                _fail(f"敏感文件被复制: {rel}")
        if _ALL_PASS:
            print(f"  [PASS] {len(FORBIDDEN_PATHS)} 个敏感路径均不存在")

        print("[3/5] 检查白名单核心内容存在")
        for rel in REQUIRED_PATHS:
            if not (target / rel).exists():
                _fail(f"白名单内容缺失: {rel}")
        if _ALL_PASS:
            print(f"  [PASS] {len(REQUIRED_PATHS)} 个核心路径均存在")

        print("[4/5] 检查占位桩存在且可编译")
        for rel in REQUIRED_STUBS:
            stub = target / rel
            if not stub.exists():
                _fail(f"占位桩缺失: {rel}")
                continue
            compile_result = subprocess.run(
                [sys.executable, "-c", f"compile(open(r'{stub}', encoding='utf-8').read(), r'{rel}', 'exec')"],
                capture_output=True,
            )
            if compile_result.returncode != 0:
                _fail(f"占位桩语法错误: {rel}")
        if _ALL_PASS:
            print(f"  [PASS] {len(REQUIRED_STUBS)} 个占位桩存在且语法有效")

        print("[5/5] 抽查内容替换 + 独立复扫禁止字符串")
        for rel, should_have, should_not in REPLACEMENT_SPOT_CHECKS:
            content = (target / rel).read_text(encoding="utf-8", errors="ignore")
            if should_have not in content:
                _fail(f"{rel} 缺少替换后值 {should_have}")
            if should_not in content:
                _fail(f"{rel} 残留真实值 {should_not}")
        if _ALL_PASS:
            print(f"  [PASS] {len(REPLACEMENT_SPOT_CHECKS)} 处替换抽查通过")

        residual = 0
        for file_path in target.rglob("*"):
            if not file_path.is_file() or ".git" in file_path.relative_to(target).parts:
                continue
            content = file_path.read_bytes().decode("utf-8", errors="ignore")
            for pattern in FORBIDDEN_STRINGS:
                if pattern in content:
                    _fail(f"{file_path.relative_to(target).as_posix()} 残留 {pattern}")
                    residual += 1
        if residual == 0:
            print(f"  [PASS] 独立复扫 {sum(1 for _ in target.rglob('*') if _.is_file())} 个文件零残留")

    print("=" * 60)
    if _ALL_PASS:
        print("[PASS] 发布流程验证全部通过")
        return 0
    print("[FAIL] 发布流程验证未通过，禁止推送公开仓库")
    return 1


if __name__ == "__main__":
    sys.exit(main())
