# -*- coding: utf-8 -*-
"""验证 Android 手动构建工作流所需文件完整且不会被自动触发。"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ANDROID_ROOT = REPO_ROOT / "clients" / "frontend" / "aveline-android" / "android"
WRAPPER_JAR = ANDROID_ROOT / "gradle" / "wrapper" / "gradle-wrapper.jar"
WRAPPER_PROPERTIES = ANDROID_ROOT / "gradle" / "wrapper" / "gradle-wrapper.properties"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "android-ci.yml"

EXPECTED_WRAPPER_SHA256 = (
    "7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172"
)
EXPECTED_DISTRIBUTION_SHA256 = (
    "ed1a8d686605fd7c23bdf62c7fc7add1c5b23b2bbc3721e661934ef4a4911d7c"
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """记录并输出单项验证结果。"""
    if condition:
        print(f"  [PASS] {name}")
        return
    suffix = f": {detail}" if detail else ""
    print(f"  [FAIL] {name}{suffix}")
    FAILURES.append(name)


def git_output(*args: str) -> subprocess.CompletedProcess[str]:
    """在仓库根目录执行只读 Git 检查。"""
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def verify_wrapper() -> None:
    """验证 Wrapper JAR 存在、可信且可被 Git 收录。"""
    print("== Gradle Wrapper ==")
    check("gradle-wrapper.jar 存在", WRAPPER_JAR.is_file(), str(WRAPPER_JAR))
    if not WRAPPER_JAR.is_file():
        return

    digest = hashlib.sha256(WRAPPER_JAR.read_bytes()).hexdigest()
    check(
        "Wrapper JAR SHA-256 与 Gradle 8.14.3 官方值一致",
        digest == EXPECTED_WRAPPER_SHA256,
        digest,
    )

    with zipfile.ZipFile(WRAPPER_JAR) as archive:
        names = set(archive.namelist())
    check(
        "Wrapper 主类存在",
        "org/gradle/wrapper/GradleWrapperMain.class" in names,
    )

    ignored = git_output("check-ignore", "--quiet", str(WRAPPER_JAR))
    check("Wrapper JAR 未被 .gitignore 排除", ignored.returncode == 1)

    eligible = git_output(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        str(WRAPPER_JAR),
    )
    check(
        "Wrapper JAR 已跟踪或可被下一次提交收录",
        bool(eligible.stdout.strip()),
    )


def verify_properties() -> None:
    """验证 Wrapper 版本和发行包校验配置。"""
    print("== Wrapper 配置 ==")
    content = WRAPPER_PROPERTIES.read_text(encoding="utf-8")
    check("Gradle 版本固定为 8.14.3", "gradle-8.14.3-all.zip" in content)
    check(
        "Gradle 发行包 SHA-256 已固定",
        f"distributionSha256Sum={EXPECTED_DISTRIBUTION_SHA256}" in content,
    )


def verify_workflow() -> None:
    """验证工作流仅可手动触发，且保留完整的构建检查能力。"""
    print("== GitHub Actions 工作流 ==")
    content = WORKFLOW.read_text(encoding="utf-8")
    trigger_block = content.split("\njobs:", maxsplit=1)[0]
    check("保留手动触发入口", "\n  workflow_dispatch:" in trigger_block)
    check("已关闭 push 自动触发", "\n  push:" not in trigger_block)
    check("已关闭 PR 自动触发", "\n  pull_request:" not in trigger_block)
    expected_fragments = {
        "checkout 使用 Node.js 24 版本": "uses: actions/checkout@v6",
        "setup-java 使用 Node.js 24 版本": "uses: actions/setup-java@v5",
        "upload-artifact 使用当前主版本": "uses: actions/upload-artifact@v7",
        "CI 使用 Gradle 官方下载源": "services.gradle.org/distributions/",
        "CI 下载超时提高到 60 秒": "networkTimeout=60000",
        "执行 Android 单元测试": "./gradlew :app:testDebugUnitTest",
        "构建 Debug APK": "./gradlew :app:assembleDebug",
        "执行 Android lint": "./gradlew :app:lintDebug",
    }
    for name, fragment in expected_fragments.items():
        check(name, fragment in content, fragment)


def main() -> int:
    """运行全部完整性检查并返回适合 CI 使用的退出码。"""
    verify_wrapper()
    verify_properties()
    verify_workflow()

    print("\n== 结果 ==")
    if FAILURES:
        print(f"验证失败，共 {len(FAILURES)} 项")
        return 1
    print("Android 手动构建工作流完整性验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
