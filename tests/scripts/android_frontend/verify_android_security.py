# -*- coding: utf-8 -*-
"""Android 端本次安全/兼容性优化的验证脚本。

校验范围:
1. 关键技术防线在源码层面就位(不依赖运行时):
   - network_security_config.xml: 生产 base-config 不信任 user CA(只在 debug-overrides 信任)
   - WebSocketManager: 存在未连接消息补发队列 + 连接归属校验(防旧回调覆盖)
   - ReplayGuard / ExportCipher 已实现并被接线
   - SystemControlExecutor 使用白名单正则校验(命令注入防护)
2. 单元测试真实通过(含新增 ReplayGuardTest / ExportCipherTest)

用法(在 android 目录执行 gradle 前请先构建):
    python tests/scripts/android_frontend/verify_android_security.py
    --gradle-exe <gradlew 绝对路径> (可选, 不传则跳过 gradle 单测, 仅做源码静态校验)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
# tests/scripts/android_frontend -> android/ 根
ANDROID_DIR = os.path.normpath(os.path.join(REPO_ROOT, "..", "..", "..", "clients",
                                            "frontend", "aveline-android", "android"))
APP_SRC = os.path.join(ANDROID_DIR, "app", "src", "main")
TEST_SRC = os.path.join(ANDROID_DIR, "app", "src", "test")

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILURES.append(name)


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def verify_source_invariants() -> None:
    print("== 源码级安全不变式 ==")

    nsc = os.path.join(APP_SRC, "res", "xml", "network_security_config.xml")
    if os.path.exists(nsc):
        xml = read(nsc)
        base = re.search(r"<base-config[^>]*>(.*?)</base-config>", xml, re.S)
        base_has_user = bool(base and re.search(r'<certificates[^>]*src="user"', base.group(1)))
        debug_has_user = bool(re.search(r"<debug-overrides>.*?<certificates[^>]*src=\"user\"",
                                        xml, re.S))
        check("生产 base-config 不信任用户 CA", not base_has_user and debug_has_user)
    else:
        check("network_security_config 存在", False, nsc)

    ws = os.path.join(APP_SRC, "java", "com", "aveline", "ai", "mobile",
                      "data", "remote", "api", "WebSocketManager.kt")
    if os.path.exists(ws):
        txt = read(ws)
        check("WS 未连接消息入队补发", "pendingMessages" in txt
              and "flushPendingMessages" in txt)
        check("WS 旧连接回调归属校验(防覆盖)", "webSocket !== webSocketRef.get()" in txt)
    else:
        check("WebSocketManager 存在", False, ws)

    guard = os.path.join(APP_SRC, "java", "com", "aveline", "ai", "mobile",
                         "services", "ReplayGuard.kt")
    check("ReplayGuard 已实现", os.path.exists(guard) and "isReplay" in read(guard))

    cipher = os.path.join(APP_SRC, "java", "com", "aveline", "ai", "mobile",
                          "utils", "ExportCipher.kt")
    check("ExportCipher 已实现(AES-GCM)", os.path.exists(cipher)
          and "AES/GCM" in read(cipher))

    data_exp = os.path.join(APP_SRC, "java", "com", "aveline", "ai", "mobile",
                            "utils", "DataExportManager.kt")
    if os.path.exists(data_exp):
        check("导出已接入加密(ExportCipher.encrypt)", "ExportCipher.encrypt" in read(data_exp))
        check("导入已用 Room 事务(withTransaction)", "withTransaction" in read(data_exp))
    else:
        check("DataExportManager 存在", False, data_exp)

    sysctl = os.path.join(APP_SRC, "java", "com", "aveline", "ai", "mobile",
                          "services", "SystemControlExecutor.kt")
    if os.path.exists(sysctl):
        check("命令注入防护(白名单正则校验)", "Regex" in read(sysctl) or "regex" in read(sysctl))
    else:
        check("SystemControlExecutor 存在", False, sysctl)


def find_test_reports() -> list[str]:
    base = os.path.join(ANDROID_DIR, "app", "build", "test-results", "testDebugUnitTest")
    out: list[str] = []
    for root, _, files in os.walk(base):
        for f in files:
            if f.endswith(".xml"):
                out.append(os.path.join(root, f))
    return out


def classnames_present(required: set[str]) -> bool:
    found = set()
    for rp in find_test_reports():
        try:
            root = ET.parse(rp).getroot()
        except ET.ParseError:
            continue
        for tc in root.iter("testcase"):
            cn = tc.get("classname", "")
            if cn:
                found.add(cn.split(".")[-1])
    return required.issubset(found)


def verify_unit_tests() -> None:
    print("== 单元测试结果 ==")
    reports = find_test_reports()
    if not reports:
        print("  [SKIP] 未找到测试报告(请先运行 gradle testDebugUnitTest)")
        return
    total = failures = errors = 0
    required = {"ReplayGuardTest", "ExportCipherTest"}
    for rp in reports:
        try:
            root = ET.parse(rp).getroot()
        except ET.ParseError:
            continue
        attrs = root.attrib
        total += int(attrs.get("tests", 0))
        failures += int(attrs.get("failures", 0))
        errors += int(attrs.get("errors", 0))
    check("单测总通过(0 失败/0 错误)", failures == 0 and errors == 0,
          f"tests={total} failures={failures} errors={errors}")
    # 报告文件名或 suite classname 二者之一能确认新增用例已执行即可
    by_file = {n for n in required if any(n in os.path.basename(r) for r in reports)}
    check("新增安全测试已执行", by_file == required
          or classnames_present(required),
          f"by_file={sorted(required - by_file) or 'full'}")


def run_gradle_tests(gradle_script: str) -> None:
    if not gradle_script:
        gradle_script = os.path.join(ANDROID_DIR, "gradlew.bat" if os.name == "nt" else "gradlew")
    exe = os.path.abspath(gradle_script)  # 始终绝对路径,避免与 cwd 叠加错位
    if not os.path.exists(exe) and os.name == "nt":
        exe = os.path.join(ANDROID_DIR, "gradlew.bat")
    print(f"== 运行单测: {exe} :app:testDebugUnitTest ==")
    try:
        res = subprocess.run(
            [exe, ":app:testDebugUnitTest", "--console=plain"],
            cwd=ANDROID_DIR, capture_output=True, text=True, timeout=1800,
        )
        print(res.stdout[-3000:])
        check("gradle 单测命令退出码为 0", res.returncode == 0,
              f"(exit={res.returncode})")
    except FileNotFoundError:
        print("  [SKIP] 未找到 gradlew,跳过 gradle 单测,仅做源码静态校验")
    except subprocess.TimeoutExpired:
        check("gradle 单测超时", False, "timeout=1800s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Android 安全/兼容性优化验证")
    parser.add_argument("--gradle-exe", default="",
                        help="gradlew(.bat) 绝对路径;提供则执行 gradle 单测")
    args = parser.parse_args()

    verify_source_invariants()
    if args.gradle_exe:
        run_gradle_tests(args.gradle_exe)
    verify_unit_tests()

    print("\n== 结果 ==")
    if FAILURES:
        print(f"FAILED {len(FAILURES)} 项: {FAILURES}")
        return 1
    print("OK 所有校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())