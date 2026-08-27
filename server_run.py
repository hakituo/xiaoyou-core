#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务器轻量化启动脚本 (2C8G 优化版)
Server Lightweight Startup Script

此脚本会自动设置环境变量以禁用重资源组件，适合在配置较低的云服务器上运行。
It sets environment variables to disable heavy components, suitable for low-spec cloud servers.
"""

import os
import sys
import subprocess


def main():
    print("==================================================")
    print("   Xiaoyou Core - Server Lightweight Mode")
    print("   小友核心 - 服务器轻量化模式")
    print("==================================================")
    print("正在配置服务器优化环境变量...")

    # 1. 禁用 C++ 调度器 (节省内存和CPU开销)
    os.environ["XIAOYOU_DISABLE_CPP_SCHEDULER"] = "1"
    print("[-] C++ Scheduler: Disabled (已禁用)")

    # 2. 禁用本地 LLM 加载 (使用云端 API)
    os.environ["XIAOYOU_DISABLE_LOCAL_LLM"] = "1"
    print("[-] Local LLM: Disabled (已禁用 - 请确保 .env 配置了云端 API)")

    # 3. 禁用本地生图 (节省显存/内存)
    os.environ["XIAOYOU_DISABLE_IMAGE"] = "1"
    print("[-] Local Image Gen: Disabled (已禁用)")

    # 4. 开启 SFW 模式 (仅加载安全人设)
    os.environ["XIAOYOU_SFW_ONLY"] = "1"
    print("[+] SFW Mode: Enabled (已开启 - 仅加载 SFW 人设)")

    # 5. 确保 TTS 开启 (Edge TTS 是 CPU 友好的)
    # os.environ["XIAOYOU_DISABLE_TTS"] = "0" # 默认开启
    print("[+] Edge TTS: Enabled (默认开启)")

    print("\nStarting main application...\n")

    # 获取当前 Python解释器路径
    python_exe = sys.executable
    script_path = os.path.join(os.path.dirname(__file__), "main.py")

    # 构建命令
    cmd = [python_exe, script_path]

    # 运行
    try:
        # 传递当前环境变量（包含我们刚刚设置的）
        subprocess.run(cmd, env=os.environ.copy(), check=False)
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
    except Exception as e:
        print(f"\nError running server: {e}")


if __name__ == "__main__":
    main()
