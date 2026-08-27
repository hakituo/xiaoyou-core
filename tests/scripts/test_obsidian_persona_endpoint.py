# -*- coding: utf-8 -*-
"""验证 Obsidian 专用端点 /obsidian/v1。

测试四件事：
1. /obsidian/v1/models 只列出 obsidian/ 目录下的人设（不含 qq/sensitive 等）
2. /obsidian/v1/chat/completions 非流式调用走通人设流程
3. /obsidian/v1/chat/completions 流式调用走通人设流程
4. 拒绝非 persona:obsidian/ 前缀的 model 名

用法：
    先启动后端：venv_core\\Scripts\\python.exe main.py
    再跑本脚本：venv_core\\Scripts\\python.exe tests\\scripts\\test_obsidian_persona_endpoint.py
"""

import json
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000/obsidian/v1"
# 默认测 Aveline_Obsidian 人设
PERSONA = "obsidian/Aveline_Obsidian"
MODEL_ID = f"persona:{PERSONA}"


def test_list_models():
    """测试 /obsidian/v1/models 是否只列出 obsidian 人设。"""
    print("=== 1. 测试 /obsidian/v1/models ===")
    try:
        req = urllib.request.Request(f"{BASE_URL}/models", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"[FAIL] 无法连接后端: {e}")
        return False

    models = data.get("data", [])
    if not models:
        print("[FAIL] /obsidian/v1/models 返回空列表")
        return False

    # 检查所有模型都是 persona:obsidian/ 前缀
    all_obsidian = all(
        isinstance(m.get("id"), str) and m["id"].startswith("persona:obsidian/")
        for m in models
    )
    if not all_obsidian:
        non_obsidian = [
            m["id"] for m in models
            if not (isinstance(m.get("id"), str) and m["id"].startswith("persona:obsidian/"))
        ]
        print(f"[FAIL] 发现非 obsidian 模型: {non_obsidian}")
        return False

    print(f"[OK] 找到 {len(models)} 个 obsidian 人设模型：")
    for m in models:
        print(f"     - {m['id']}  (display: {m.get('display_name', '-')})")

    if MODEL_ID not in [m["id"] for m in models]:
        print(f"[WARN] 目标模型 {MODEL_ID} 不在列表里，但仍可尝试调用")
    return True


def test_reject_non_obsidian():
    """测试拒绝非 persona:obsidian/ 前缀的 model 名。"""
    print("\n=== 2. 测试拒绝非 obsidian model 名 ===")
    payload = {
        "model": "persona:core_aveline",
        "messages": [{"role": "user", "content": "test"}],
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[FAIL] 应该拒绝但返回了 {resp.status}")
            return False
    except urllib.error.HTTPError as e:
        if e.code == 400:
            err_body = e.read().decode("utf-8", errors="replace")
            if "persona:obsidian/" in err_body:
                print(f"[OK] 正确拒绝非 obsidian model，返回 400")
                return True
            print(f"[FAIL] 返回 400 但错误消息不含 persona:obsidian/: {err_body[:200]}")
            return False
        print(f"[FAIL] 期望 400 但返回 {e.code}")
        return False


def test_non_stream():
    """测试非流式调用。"""
    print(f"\n=== 3. 非流式调用 {MODEL_ID} ===")
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "user", "content": "你好，简单介绍一下自己"},
        ],
        "max_tokens": 200,
        "temperature": 0.7,
        "user": "obsidian_test_user",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[FAIL] HTTP {e.code}: {err_body[:500]}")
        return False
    except urllib.error.URLError as e:
        print(f"[FAIL] 连接失败: {e}")
        return False

    elapsed = time.time() - t0
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        print(f"[FAIL] 返回内容为空，完整响应: {json.dumps(data, ensure_ascii=False)[:500]}")
        return False

    print(f"[OK] 耗时 {elapsed:.2f}s")
    print(f"     返回: {content[:200]}")
    return True


def test_stream():
    """测试流式调用。"""
    print(f"\n=== 4. 流式调用 {MODEL_ID} ===")
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "user", "content": "今天天气怎么样？随便聊聊"},
        ],
        "stream": True,
        "max_tokens": 200,
        "temperature": 0.7,
        "user": "obsidian_test_user",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    t0 = time.time()
    first_chunk_time = None
    chunks = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            buf = ""
            for raw in resp:
                buf += raw.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[6:].strip()
                    if payload_str == "[DONE]":
                        continue
                    try:
                        evt = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    if first_chunk_time is None:
                        first_chunk_time = time.time() - t0
                    delta = evt.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        chunks.append(delta)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[FAIL] HTTP {e.code}: {err_body[:500]}")
        return False
    except urllib.error.URLError as e:
        print(f"[FAIL] 连接失败: {e}")
        return False

    elapsed = time.time() - t0
    full = "".join(chunks)
    if not full:
        print("[FAIL] 流式返回内容为空")
        return False

    print(f"[OK] 首字节 {first_chunk_time:.2f}s, 总 {elapsed:.2f}s, {len(chunks)} chunks")
    print(f"     返回: {full[:200]}")
    return True


def test_flash_suffix():
    """测试 :flash 后缀模型切换。"""
    print(f"\n=== 5. 测试 :flash 后缀 ===")
    flash_model = f"{MODEL_ID}:flash"
    payload = {
        "model": flash_model,
        "messages": [
            {"role": "user", "content": "说一句话"},
        ],
        "max_tokens": 100,
        "temperature": 0.7,
        "user": "obsidian_test_user",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[FAIL] HTTP {e.code}: {err_body[:500]}")
        return False
    except urllib.error.URLError as e:
        print(f"[FAIL] 连接失败: {e}")
        return False

    elapsed = time.time() - t0
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        print(f"[FAIL] 返回内容为空")
        return False

    print(f"[OK] flash 模式调用成功，耗时 {elapsed:.2f}s")
    print(f"     返回: {content[:150]}")
    return True


def main():
    print(f"目标: {BASE_URL}")
    print(f"人设模型: {MODEL_ID}")
    print()

    ok1 = test_list_models()
    if not ok1:
        print("\n后端可能未启动。先确认后端在跑。")
        return

    ok2 = test_reject_non_obsidian()
    ok3 = test_non_stream()
    ok4 = test_stream()
    ok5 = test_flash_suffix()

    print("\n" + "=" * 50)
    print("汇总：")
    print(f"  /obsidian/v1/models 列表:    {'OK' if ok1 else 'FAIL'}")
    print(f"  拒绝非 obsidian model:       {'OK' if ok2 else 'FAIL'}")
    print(f"  非流式调用:                  {'OK' if ok3 else 'FAIL'}")
    print(f"  流式调用:                    {'OK' if ok4 else 'FAIL'}")
    print(f"  flash 后缀切换:              {'OK' if ok5 else 'FAIL'}")


if __name__ == "__main__":
    main()
