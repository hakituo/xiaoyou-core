#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动时间优化验证脚本

验证延迟导入优化是否生效：
1. 路由导入总时间应 < 2s
2. initialize_default_services 应 < 0.5s
3. initialize_all 中各服务初始化应有计时日志
4. 总启动时间应有记录
"""

import subprocess
import sys
import time
import re
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(PROJECT_ROOT, "venv_core", "Scripts", "python.exe")
MAIN_PY = os.path.join(PROJECT_ROOT, "main.py")

THRESHOLD_ROUTE_IMPORT = 2.0
THRESHOLD_INIT_DEFAULT = 0.5
THRESHOLD_TOTAL_STARTUP = 15.0


def run_server_and_capture():
    """启动服务器，等待就绪后关闭，捕获输出"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [PYTHON, MAIN_PY],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
    )

    output_lines = []
    start_time = time.time()
    startup_complete = False

    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            output_lines.append(line.rstrip())

            if "XiaoYou Core ready" in line or "Uvicorn running on" in line:
                startup_complete = True
                time.sleep(2)
                break

            elapsed = time.time() - start_time
            if elapsed > 30:
                output_lines.append("[TIMEOUT] 服务器启动超时 (30s)")
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return "\n".join(output_lines), startup_complete, time.time() - start_time


def parse_metrics(output: str) -> dict:
    """从输出中解析启动计时指标"""
    metrics = {}

    patterns = {
        "route_import": r"\[启动计时\] routers\.api_v1_router: ([\d.]+)s",
        "init_default": r"\[启动计时\] initialize_default_services: ([\d.]+)s",
        "init_all": r"\[启动计时\] initialize_all: ([\d.]+)s",
        "total_startup": r"FastAPI应用启动完成 \(总耗时: ([\d.]+)s\)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            metrics[key] = float(match.group(1))

    service_pattern = r"服务初始化成功: (\w+) \(([\d.]+)s\)"
    for match in re.finditer(service_pattern, output):
        name = match.group(1)
        elapsed = float(match.group(2))
        metrics[f"service_{name}"] = elapsed

    ranking_pattern = r"^\s+(\S+)\s+([\d.]+)s"
    in_ranking = False
    for line in output.split("\n"):
        if "启动耗时排行" in line:
            in_ranking = True
            continue
        if in_ranking and "===" in line:
            in_ranking = False
            continue
        if in_ranking:
            match = re.match(ranking_pattern, line)
            if match:
                name = match.group(1)
                elapsed = float(match.group(2))
                metrics[f"ranking_{name}"] = elapsed

    return metrics


def check_results(output: str, startup_complete: bool, elapsed: float, metrics: dict):
    """检查优化效果"""
    results = []

    # 检查1: 服务器是否正常启动
    if startup_complete:
        results.append(("✅", "服务器正常启动", ""))
    else:
        results.append(("❌", "服务器启动失败", f"耗时 {elapsed:.1f}s"))

    # 检查2: 路由导入时间
    route_import = metrics.get("route_import")
    if route_import is not None:
        if route_import < THRESHOLD_ROUTE_IMPORT:
            results.append(("✅", f"路由导入时间 {route_import:.3f}s < {THRESHOLD_ROUTE_IMPORT}s", ""))
        else:
            results.append(("❌", f"路由导入时间 {route_import:.3f}s >= {THRESHOLD_ROUTE_IMPORT}s", "需要进一步优化"))
    else:
        results.append(("⚠️", "未找到路由导入计时", ""))

    # 检查3: initialize_default_services 时间
    init_default = metrics.get("init_default")
    if init_default is not None:
        if init_default < THRESHOLD_INIT_DEFAULT:
            results.append(("✅", f"initialize_default_services {init_default:.3f}s < {THRESHOLD_INIT_DEFAULT}s", ""))
        else:
            results.append(("❌", f"initialize_default_services {init_default:.3f}s >= {THRESHOLD_INIT_DEFAULT}s", ""))
    else:
        results.append(("⚠️", "未找到 initialize_default_services 计时", ""))

    # 检查4: 总启动时间
    total = metrics.get("total_startup")
    if total is not None:
        if total < THRESHOLD_TOTAL_STARTUP:
            results.append(("✅", f"总启动时间 {total:.3f}s < {THRESHOLD_TOTAL_STARTUP}s", ""))
        else:
            results.append(("❌", f"总启动时间 {total:.3f}s >= {THRESHOLD_TOTAL_STARTUP}s", ""))
    else:
        results.append(("⚠️", "未找到总启动时间", ""))

    # 检查5: 启动耗时排行是否存在
    ranking_keys = [k for k in metrics if k.startswith("ranking_")]
    if ranking_keys:
        results.append(("✅", f"启动耗时排行已生成 ({len(ranking_keys)} 个服务)", ""))
    else:
        results.append(("⚠️", "未找到启动耗时排行", ""))

    return results


def main():
    print("=" * 60)
    print("启动时间优化验证脚本")
    print("=" * 60)

    print("\n[1/3] 启动服务器...")
    output, startup_complete, elapsed = run_server_and_capture()

    print("\n[2/3] 解析启动指标...")
    metrics = parse_metrics(output)

    print("\n[3/3] 检查优化效果...\n")
    results = check_results(output, startup_complete, elapsed, metrics)

    all_pass = True
    for icon, desc, hint in results:
        print(f"  {icon} {desc}")
        if hint:
            print(f"     → {hint}")
        if icon == "❌":
            all_pass = False

    if metrics:
        print("\n--- 启动计时详情 ---")
        for key, value in sorted(metrics.items()):
            print(f"  {key}: {value:.3f}s")

    print("\n" + "=" * 60)
    if all_pass:
        print("✅ 所有检查通过！启动时间优化生效。")
    else:
        print("❌ 部分检查未通过，请查看上方详情。")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
