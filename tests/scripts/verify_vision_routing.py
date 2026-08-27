#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证视觉路由(多模态主模型直通 / 纯文本主模型走 VL 中转)是否正确实现

检查项:
1. model_capabilities.py 的 is_vision_model() 能正确识别多模态模型
2. model_capabilities.py 的 has_image_content() 能正确检测图片消息
3. OpenAIClient 基类的 chat/stream_chat 入口调用了 _route_vision_if_needed
4. SiliconFlowClient 的 chat/stream_chat 走新路由(不再无脑用 VL 模型)
5. factory.py 给所有 OpenAIClient 子类注入了 VL 配置
6. ZhiPuClient._is_vision_model 委托给统一检测模块

运行: python tests/scripts/verify_vision_routing.py
"""
import ast
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _parse_file(path: Path) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=str(path))


def check_is_vision_model():
    """检查 is_vision_model 能识别多模态模型,不误判纯文本模型"""
    from core.llm.model_capabilities import is_vision_model, has_image_content

    # 多模态模型(应返回 True)
    multimodal = [
        "kimi-k3",
        "kimi-k2.6",
        "kimi-k2.7-code-highspeed",
        "Pro/moonshotai/Kimi-K2.6",
        "Qwen/Qwen3-VL-32B-Instruct",
        "Qwen/Qwen3-VL-235B-A22B-Thinking",
        "glm-4.6v",
        "glm-4.5v",
        "gpt-4o",
        "gpt-4o-mini",
        "doubao-vision-pro",
        "cloud:siliconflow:Qwen/Qwen3-VL-32B-Instruct",
        "cloud:siliconflow:Pro/moonshotai/Kimi-K2.6",
    ]
    failed_mm = []
    for m in multimodal:
        if not is_vision_model(m):
            failed_mm.append(m)

    # 纯文本模型(应返回 False)
    text_models = [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-chat",
        "qwen3-max-2025-09-23",
        "qwen3-plus",
        "MiniMax-M2.5",
        "M2-her",
        "glm-4.5-air",
        "glm-4.5",
        "doubao-seed-2-0-lite-260215",
        "nalang-xl-0826-16k",
        "Pro/deepseek-ai/DeepSeek-V3.2",
        "cloud:deepseek:deepseek-v4-flash",
        "cloud:siliconflow:Pro/MiniMaxAI/MiniMax-M2.5",
        "",
        None,
    ]
    failed_text = []
    for m in text_models:
        if is_vision_model(m):
            failed_text.append(m)

    # has_image_content 检测
    img_msg = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}}]}]
    text_msg = [{"role": "user", "content": "你好"}]
    has_img_ok = has_image_content(img_msg) and not has_image_content(text_msg)

    return failed_mm, failed_text, has_img_ok


def check_method_calls_route(path: Path, method_name: str) -> bool:
    """检查某个方法体内是否调用了 _route_vision_if_needed"""
    tree = _parse_file(path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Attribute) and func.attr == "_route_vision_if_needed":
                        return True
                    if isinstance(func, ast.Name) and func.id == "_route_vision_if_needed":
                        return True
    return False


def check_siliconflow_uses_unified_router():
    """检查 SiliconFlowClient 的 chat/stream_chat 是否使用了 is_vision_model 做路由"""
    sf_path = PROJECT_ROOT / "core" / "llm" / "siliconflow_client.py"
    tree = _parse_file(sf_path)
    found_is_vision_in_chat = False
    found_is_vision_in_stream = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in ("chat", "stream_chat"):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "is_vision_model":
                            if node.name == "chat":
                                found_is_vision_in_chat = True
                            else:
                                found_is_vision_in_stream = True
    return found_is_vision_in_chat, found_is_vision_in_stream


def check_factory_injects_vision():
    """检查 factory.py 是否有 _inject_vision_config 函数且在 _make_* 中被调用"""
    fac_path = PROJECT_ROOT / "core" / "llm" / "factory.py"
    tree = _parse_file(fac_path)
    has_inject_func = False
    inject_call_count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_inject_vision_config":
            has_inject_func = True
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "_inject_vision_config":
                inject_call_count += 1
    return has_inject_func, inject_call_count


def check_zhipu_delegates():
    """检查 ZhiPuClient._is_vision_model 是否委托给统一模块"""
    zhipu_path = PROJECT_ROOT / "core" / "llm" / "openai_compat" / "zhipu_client.py"
    tree = _parse_file(zhipu_path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_is_vision_model":
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Name) and func.id == "is_vision_model":
                        return True
    return False


def check_openai_client_chat_routes():
    """检查 OpenAIClient.chat 和 stream_chat 是否调用 _route_vision_if_needed"""
    client_path = PROJECT_ROOT / "core" / "llm" / "openai_compat" / "client.py"
    chat_ok = check_method_calls_route(client_path, "chat")
    stream_ok = check_method_calls_route(client_path, "stream_chat")
    return chat_ok, stream_ok


def main():
    print("=" * 70)
    print("视觉路由验证")
    print("=" * 70)

    all_pass = True

    # 1. is_vision_model 检测
    print("\n[1] 检查 is_vision_model / has_image_content 检测逻辑...")
    failed_mm, failed_text, has_img_ok = check_is_vision_model()
    if failed_mm:
        print("  [FAIL] 以下多模态模型未被识别为视觉模型:")
        for m in failed_mm:
            print(f"    - {m}")
        all_pass = False
    else:
        print("  [OK] 所有多模态模型都被正确识别")

    if failed_text:
        print("  [FAIL] 以下纯文本模型被误判为视觉模型:")
        for m in failed_text:
            print(f"    - {m}")
        all_pass = False
    else:
        print("  [OK] 所有纯文本模型都被正确排除")

    if not has_img_ok:
        print("  [FAIL] has_image_content 检测不正确")
        all_pass = False
    else:
        print("  [OK] has_image_content 检测正确")

    # 2. OpenAIClient 基类
    print("\n[2] 检查 OpenAIClient 基类 chat/stream_chat 是否接入视觉路由...")
    chat_ok, stream_ok = check_openai_client_chat_routes()
    if not chat_ok:
        print("  [FAIL] OpenAIClient.chat 未调用 _route_vision_if_needed")
        all_pass = False
    else:
        print("  [OK] OpenAIClient.chat 已接入视觉路由")
    if not stream_ok:
        print("  [FAIL] OpenAIClient.stream_chat 未调用 _route_vision_if_needed")
        all_pass = False
    else:
        print("  [OK] OpenAIClient.stream_chat 已接入视觉路由")

    # 3. SiliconFlowClient
    print("\n[3] 检查 SiliconFlowClient 是否使用统一路由(is_vision_model)...")
    sf_chat, sf_stream = check_siliconflow_uses_unified_router()
    if not sf_chat:
        print("  [FAIL] SiliconFlowClient.chat 未使用 is_vision_model 路由")
        all_pass = False
    else:
        print("  [OK] SiliconFlowClient.chat 使用统一路由")
    if not sf_stream:
        print("  [FAIL] SiliconFlowClient.stream_chat 未使用 is_vision_model 路由")
        all_pass = False
    else:
        print("  [OK] SiliconFlowClient.stream_chat 使用统一路由")

    # 4. factory.py 注入 VL 配置
    print("\n[4] 检查 factory.py 是否注入 VL 配置到所有客户端...")
    has_inject, call_count = check_factory_injects_vision()
    if not has_inject:
        print("  [FAIL] factory.py 缺少 _inject_vision_config 函数")
        all_pass = False
    elif call_count < 5:
        print(f"  [FAIL] _inject_vision_config 只被调用 {call_count} 次,应至少 5 次(deepseek/openai/aveline/ark/minimax/zhipu)")
        all_pass = False
    else:
        print(f"  [OK] _inject_vision_config 已在 {call_count} 个 _make_* 函数中被调用")

    # 5. ZhiPuClient 委托
    print("\n[5] 检查 ZhiPuClient._is_vision_model 是否委托统一模块...")
    if not check_zhipu_delegates():
        print("  [FAIL] ZhiPuClient._is_vision_model 未委托 is_vision_model")
        all_pass = False
    else:
        print("  [OK] ZhiPuClient._is_vision_model 已委托统一模块")

    # 总结
    print("\n" + "=" * 70)
    if all_pass:
        print("✅ 所有检查通过,视觉路由实现正确")
        print("   - 多模态主模型(kimi-k3 / Qwen3-VL / glm-4.6v 等)会走一阶段直通")
        print("   - 纯文本主模型(deepseek-v4-flash / MiniMax-M2.5 等)会走两阶段 VL 中转")
        sys.exit(0)
    else:
        print("❌ 存在失败项,请检查上述 [FAIL] 项")
        sys.exit(1)


if __name__ == "__main__":
    main()
