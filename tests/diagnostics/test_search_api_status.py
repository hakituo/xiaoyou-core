#!/usr/bin/env python3
"""
搜索API状态检测脚本

检测项目中使用的三个搜索API：
1. Serper Google搜索API - 默认搜索provider
2. 智谱(ZhiPu)代理搜索 - 通过glm-4.5-air模型调用web_search工具
3. 博查(Bocha)搜索 - 备用搜索API

用法：
    python tests/diagnostics/test_search_api_status.py
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

import aiohttp


async def test_serper_search():
    """测试Serper Google搜索API"""
    print("=" * 60)
    print("【Serper Google搜索测试】")
    print("=" * 60)

    serper_api_key = os.environ.get("SERPER_API_KEY")
    if not serper_api_key:
        print("❌ SERPER_API_KEY 未配置")
        return False, "API Key未配置"

    print(f"API Key: {serper_api_key[:20]}...")

    url = "https://google.serper.dev/search"

    headers = {
        "X-API-KEY": serper_api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "q": "2025年7月中国最新科技新闻",
        "gl": "cn",
        "hl": "zh-cn",
        "num": 3,
    }

    print(f"请求URL: {url}")
    print(f"请求时间: {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 40)

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start_time = asyncio.get_event_loop().time()
            async with session.post(url, json=payload, headers=headers) as response:
                elapsed = asyncio.get_event_loop().time() - start_time

                print(f"响应状态: {response.status}")
                print(f"响应时间: {elapsed:.2f}s")

                if response.status == 200:
                    data = await response.json()
                    organic = data.get("organic", [])
                    kg = data.get("knowledgeGraph", {})

                    if organic or kg:
                        print(f"✅ 搜索成功")
                        print(f"搜索结果数: {len(organic)}条")
                        if kg:
                            print(f"知识图谱: {kg.get('title', 'N/A')}")
                        if organic:
                            first = organic[0]
                            print(f"第一条标题: {first.get('title', 'N/A')}")
                            print(f"第一条链接: {first.get('link', 'N/A')[:50]}...")
                        return True, "搜索成功"
                    else:
                        print("⚠️ 返回空结果")
                        return True, "响应正常但无结果"
                else:
                    error_text = await response.text()
                    print(f"❌ 请求失败")
                    print(f"错误信息: {error_text[:300]}")
                    if "额度" in error_text or "quota" in error_text.lower() or "余额" in error_text:
                        return False, "API额度已耗尽"
                    if "invalid" in error_text.lower() and "key" in error_text.lower():
                        return False, "API Key无效"
                    return False, f"HTTP {response.status}"

    except asyncio.TimeoutError:
        print("❌ 请求超时（30s）- 可能需要代理")
        return False, "超时"
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}: {e}")
        return False, str(e)


async def test_zhipu_search():
    """测试智谱代理搜索API"""
    print()
    print("=" * 60)
    print("【智谱(ZhiPu)代理搜索测试】")
    print("=" * 60)

    zhipu_api_key = os.environ.get("ZHIPU_API_KEY")
    if not zhipu_api_key:
        print("❌ ZHIPU_API_KEY 未配置")
        return False, "API Key未配置"

    print(f"API Key: {zhipu_api_key[:20]}...")

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    model = "glm-4.5-air"

    messages = [
        {"role": "system", "content": "你是一个搜索助手，搜索并整理关键事实。"},
        {"role": "user", "content": "搜索2025年7月中国最新的科技新闻"},
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "stream": False,
        "tools": [{"type": "web_search", "web_search": {"enable": True}}],
    }

    headers = {
        "Authorization": f"Bearer {zhipu_api_key}",
        "Content-Type": "application/json",
    }

    print(f"请求模型: {model}")
    print(f"请求时间: {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 40)

    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start_time = asyncio.get_event_loop().time()
            async with session.post(url, json=payload, headers=headers) as response:
                elapsed = asyncio.get_event_loop().time() - start_time

                print(f"响应状态: {response.status}")
                print(f"响应时间: {elapsed:.2f}s")

                if response.status == 200:
                    data = await response.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        if content and len(content) > 50:
                            print(f"✅ 搜索成功")
                            print(f"返回内容长度: {len(content)}字")
                            print(f"内容预览: {content[:200]}...")
                            return True, "搜索成功"
                        else:
                            print("⚠️ 返回内容过短，可能未执行搜索")
                            return True, "响应正常但内容异常"
                    else:
                        print("❌ 响应格式异常：无choices")
                        return False, "响应格式异常"
                else:
                    error_text = await response.text()
                    print(f"❌ 请求失败")
                    print(f"错误信息: {error_text[:300]}")
                    if "额度" in error_text or "quota" in error_text.lower() or "余额" in error_text:
                        return False, "API额度已耗尽"
                    if "rate limit" in error_text.lower():
                        return False, "请求频率限制"
                    return False, f"HTTP {response.status}"

    except asyncio.TimeoutError:
        print("❌ 请求超时（45s）")
        return False, "超时"
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}: {e}")
        return False, str(e)


async def test_bocha_search():
    """测试博查搜索API"""
    print()
    print("=" * 60)
    print("【博查(Bocha)搜索测试】")
    print("=" * 60)

    bocha_api_key = os.environ.get("BOCHA_API_KEY")
    if not bocha_api_key:
        print("❌ BOCHA_API_KEY 未配置")
        return False, "API Key未配置"

    print(f"API Key: {bocha_api_key[:20]}...")

    url = "https://api.bochaai.com/v1/web-search"

    headers = {
        "Authorization": f"Bearer {bocha_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": "2025年7月中国科技新闻",
        "freshness": "noLimit",
        "summary": True,
        "count": 3,
    }

    print(f"请求URL: {url}")
    print(f"请求时间: {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 40)

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start_time = asyncio.get_event_loop().time()
            async with session.post(url, json=payload, headers=headers) as response:
                elapsed = asyncio.get_event_loop().time() - start_time

                print(f"响应状态: {response.status}")
                print(f"响应时间: {elapsed:.2f}s")

                if response.status == 200:
                    data = await response.json()
                    web_pages = data.get("data", {}).get("webPages", {}).get("value", [])

                    if web_pages and len(web_pages) > 0:
                        print(f"✅ 搜索成功")
                        print(f"返回结果数: {len(web_pages)}条")
                        first = web_pages[0]
                        print(f"第一条标题: {first.get('name', 'N/A')}")
                        print(f"第一条链接: {first.get('url', 'N/A')[:50]}...")
                        return True, "搜索成功"
                    else:
                        print("⚠️ 返回空结果")
                        return True, "响应正常但无结果"
                else:
                    error_text = await response.text()
                    print(f"❌ 请求失败")
                    print(f"错误信息: {error_text[:300]}")
                    if "额度" in error_text or "quota" in error_text.lower() or "余额" in error_text:
                        return False, "API额度已耗尽"
                    if "invalid" in error_text.lower() and "key" in error_text.lower():
                        return False, "API Key无效"
                    return False, f"HTTP {response.status}"

    except asyncio.TimeoutError:
        print("❌ 请求超时（30s）")
        return False, "超时"
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}: {e}")
        return False, str(e)


async def main():
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + " 搜索API状态检测报告".center(54) + "    ║")
    print("║" + f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}".center(54) + "    ║")
    print("╚" + "═" * 58 + "╝")
    print()

    results = {}

    # 测试Serper搜索（当前默认）
    serper_ok, serper_msg = await test_serper_search()
    results["Serper"] = {"ok": serper_ok, "msg": serper_msg}

    # 测试智谱搜索
    zhipu_ok, zhipu_msg = await test_zhipu_search()
    results["智谱(ZhiPu)"] = {"ok": zhipu_ok, "msg": zhipu_msg}

    # 测试博查搜索
    bocha_ok, bocha_msg = await test_bocha_search()
    results["博查(Bocha)"] = {"ok": bocha_ok, "msg": bocha_msg}

    # 汇总报告
    print()
    print("=" * 60)
    print("【汇总报告】")
    print("=" * 60)

    for name, r in results.items():
        status = "✅ 正常" if r["ok"] else "❌ 异常"
        print(f"{name}: {status} - {r['msg']}")

    print()
    print("-" * 60)

    # 给出建议
    print("【建议】")
    if serper_ok:
        print("1. Serper搜索可用（当前默认），Google搜索结果质量高")
        print("   注册赠送2500次免费额度，足够日常使用")
    else:
        print("1. Serper搜索不可用，检查网络或API Key")

    if zhipu_ok and not serper_ok:
        print("2. 智谱搜索可用，可临时回退到智谱搜索")
    elif zhipu_ok:
        print("2. 智谱搜索可用（备用方案）")

    if not serper_ok and not zhipu_ok:
        print("2. 两个主要搜索API都不可用，需要排查网络或API额度")

    print()
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
