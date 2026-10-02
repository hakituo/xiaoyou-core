#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ComfyUI & Nunchaku Status Checker
用于验证 ComfyUI 连接状态及 Nunchaku 插件可用性
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from config.integrated_config import get_settings
from core.modules.comfy_client import ComfyClient
from core.utils.logger import get_logger

# 配置简单的控制台日志
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = get_logger("CheckComfy")

async def check_status():
    settings = get_settings()
    host = settings.model.comfy_host
    port = settings.model.comfy_port
    
    print(f"\n{'='*50}")
    print(f"正在连接 ComfyUI ({host}:{port})...")
    print(f"{'='*50}\n")

    client = ComfyClient(host=host, port=port)
    
    # 1. Check Connectivity
    try:
        is_alive = await client.ping()
        if is_alive:
            print("✅ ComfyUI 连接成功")
        else:
            print("❌ ComfyUI 连接失败 (无法访问 /system_stats)")
            print("   -> 请检查 ComfyUI 是否已启动")
            print("   -> 请检查主机和端口配置是否正确")
            return
    except Exception as e:
        print(f"❌ 连接异常: {e}")
        return

    # 2. Check Nunchaku
    print("\n正在检查 Nunchaku 插件状态...")
    try:
        has_nunchaku = await client.check_nunchaku_availability()
        if has_nunchaku:
            print("✅ 检测到 NunchakuFluxLoader 节点")
            print("   -> 状态: 可用")
            print("   -> 优势: FP4 量化将显著降低 Flux 模型显存占用并提升生成速度")
        else:
            print("⚠️ 未检测到 NunchakuFluxLoader 节点")
            print("   -> 状态: 将回退到标准 CheckpointLoaderSimple")
            print("   -> 建议: 安装 comfyanonymous/ComfyUI-Nunchaku 以获得 FP4 加速体验")
    except Exception as e:
        print(f"❌ 检查 Nunchaku 失败: {e}")

    print(f"\n{'='*50}")
    print("检查完成")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_status())
