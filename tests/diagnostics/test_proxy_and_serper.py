#!/usr/bin/env python3
"""
代理与Serper API测试脚本

测试：
1. 当前Python环境是否能使用代理
2. Serper API（Google搜索）是否能通过代理访问

用法：
    # 先在PowerShell设置代理环境变量
    $env:HTTP_PROXY = "http://127.0.0.1:7890"
    $env:HTTPS_PROXY = "http://127.0.0.1:7890"

    # 然后运行
    python tests/diagnostics/test_proxy_and_serper.py
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

import aiohttp


def get_proxy_config():
    """获取代理配置"""
    http_proxy = os.environ.get("HTTP_PROXY", "")
    https_proxy = os.environ.get("HTTPS_PROXY", "")

    # 如果没设置，尝试常见端口
    if not http_proxy:
        common_ports = [7890, 1080, 8080, 10809]
        for port in common_ports:
            proxy = f"http://127.0.0.1:{port}"
            # 不主动设置，只是提示
            return None, None

    return http_proxy, https_proxy


async def test_direct_connection():
    """测试直接访问国外网站"""
    print("=" * 60)
    print("【直接连接测试】")
    print("=" * 60)

    http_proxy = os.environ.get("HTTP_PROXY", "")
    https_proxy = os.environ.get("HTTPS_PROXY", "")

    print(f"HTTP_PROXY: {http_proxy or '未设置'}")
    print(f"HTTPS_PROXY: {https_proxy or '未设置'}")
    print("-" * 40)

    # 测试访问Google（需要代理）
    test_urls = [
        ("Google", "https://www.google.com"),
        ("Serper API", "https://api.serper.dev"),
        ("Tavily API", "https://api.tavily.com"),
    ]

    results = []

    for name, url in test_urls:
        print(f"\n测试 {name}: {url}")
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            connector = aiohttp.TCPConnector()

            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                start = asyncio.get_event_loop().time()
                try:
                    async with session.get(url) as resp:
                        elapsed = asyncio.get_event_loop().time() - start
                        print(f"  状态: {resp.status}, 时间: {elapsed:.2f}s")
                        results.append((name, resp.status == 200, f"{resp.status}"))
                except aiohttp.ClientConnectorError as e:
                    print(f"  ❌ 连接失败: {e}")
                    results.append((name, False, "连接失败"))
                except asyncio.TimeoutError:
                    print(f"  ❌ 超时")
                    results.append((name, False, "超时"))

        except Exception as e:
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results.append((name, False, str(e)))

    return results


async def test_with_explicit_proxy():
    """测试显式使用代理"""
    print()
    print("=" * 60)
    print("【显式代理测试】")
    print("=" * 60)

    http_proxy = os.environ.get("HTTP_PROXY", "")

    if not http_proxy:
        print("⚠️ 未设置 HTTP_PROXY 环境变量")
        print()
        print("请在运行前设置代理环境变量：")
        print("  PowerShell:")
        print("    $env:HTTP_PROXY = 'http://127.0.0.1:7890'")
        print("    $env:HTTPS_PROXY = 'http://127.0.0.1:7890'")
        print()
        print("  或者检查你的代理软件端口（常见：7890, 1080, 8080）")
        return []

    print(f"使用代理: {http_proxy}")
    print("-" * 40)

    # 通过代理访问Google
    test_urls = [
        ("Google", "https://www.google.com"),
        ("Serper API", "https://api.serper.dev"),
    ]

    results = []

    for name, url in test_urls:
        print(f"\n测试 {name}: {url}")
        try:
            # 显式使用代理
            connector = aiohttp.TCPConnector()

            # aiohttp 使用环境变量中的代理
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start = asyncio.get_event_loop().time()
                try:
                    async with session.get(url) as resp:
                        elapsed = asyncio.get_event_loop().time() - start
                        print(f"  ✅ 状态: {resp.status}, 时间: {elapsed:.2f}s")
                        results.append((name, True, f"{resp.status}"))
                except Exception as e:
                    print(f"  ❌ 失败: {type(e).__name__}: {e}")
                    results.append((name, False, str(e)))

        except Exception as e:
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results.append((name, False, str(e)))

    return results


async def test_serper_api():
    """测试Serper API（需要API Key）"""
    print()
    print("=" * 60)
    print("【Serper API 搜索测试】")
    print("=" * 60)

    # Serper有免费额度，可以注册获取API Key
    # https://serper.dev 注册后获取
    serper_api_key = os.environ.get("SERPER_API_KEY", "")

    if not serper_api_key:
        print("⚠️ SERPER_API_KEY 未配置")
        print()
        print("Serper.dev 提供2500次免费搜索/月")
        print("获取步骤：")
        print("  1. 访问 https://serper.dev")
        print("  2. 注册账号")
        print("  3. 在Dashboard获取API Key")
        print("  4. 在 .env 文件添加: SERPER_API_KEY=xxx")
        print()
        return False, "API Key未配置"

    print(f"API Key: {serper_api_key[:20]}...")
    print()

    url = "https://google.serper.dev/search"

    headers = {
        "X-API-KEY": serper_api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "q": "2025年AI大模型最新进展",
    }

    print(f"请求URL: {url}")
    print(f"搜索内容: {payload['q']}")
    print("-" * 40)

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start = asyncio.get_event_loop().time()
            async with session.post(url, json=payload, headers=headers) as resp:
                elapsed = asyncio.get_event_loop().time() - start

                print(f"响应状态: {resp.status}")
                print(f"响应时间: {elapsed:.2f}s")

                if resp.status == 200:
                    data = await resp.json()
                    organic = data.get("organic", [])
                    if organic:
                        print(f"✅ 搜索成功")
                        print(f"返回结果数: {len(organic)}条")
                        # 显示第一条
                        first = organic[0]
                        print(f"第一条标题: {first.get('title', 'N/A')}")
                        print(f"第一条链接: {first.get('link', 'N/A')[:50]}...")
                        return True, "搜索成功"
                    else:
                        print("⚠️ 返回空结果")
                        return True, "无结果"
                else:
                    error = await resp.text()
                    print(f"❌ 失败: {error[:200]}")
                    return False, f"HTTP {resp.status}"

    except aiohttp.ClientConnectorError as e:
        print(f"❌ 连接失败（可能需要代理）: {e}")
        return False, "需要代理"
    except asyncio.TimeoutError:
        print("❌ 超时")
        return False, "超时"
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}: {e}")
        return False, str(e)


async def main():
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + " 代理与国外API连通性测试 ".center(54) + "    ║")
    print("║" + f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}".center(54) + "    ║")
    print("╚" + "═" * 58 + "╝")
    print()

    # 检查代理配置
    http_proxy = os.environ.get("HTTP_PROXY", "")
    https_proxy = os.environ.get("HTTPS_PROXY", "")

    if not http_proxy:
        print("【提示】未检测到代理环境变量")
        print()
        print("如果你开了系统代理，需要在终端设置环境变量让Python使用：")
        print()
        print("PowerShell方式：")
        print("  $env:HTTP_PROXY = 'http://127.0.0.1:端口'")
        print("  $env:HTTPS_PROXY = 'http://127.0.0.1:端口'")
        print()
        print("常见代理端口：")
        print("  Clash: 7890")
        print("  V2Ray: 1080 或 10809")
        print("  SSR: 1080")
        print()
        print("设置后重新运行此脚本")
        print("=" * 60)

    # 测试直接连接
    direct_results = await test_direct_connection()

    # 如果设置了代理，测试代理连接
    if http_proxy:
        proxy_results = await test_with_explicit_proxy()

    # 测试Serper
    serper_ok, serper_msg = await test_serper_api()

    # 汇总
    print()
    print("=" * 60)
    print("【汇总报告】")
    print("=" * 60)

    print("\n直接连接测试结果:")
    for name, ok, msg in direct_results:
        status = "✅" if ok else "❌"
        print(f"  {name}: {status} {msg}")

    if http_proxy:
        print("\n代理连接测试结果:")
        for name, ok, msg in proxy_results:
            status = "✅" if ok else "❌"
            print(f"  {name}: {status} {msg}")