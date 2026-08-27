"""P0-14 验证脚本：image_service_client.py 缓存键 + 超时

验证目标：
1. _get_prompt_hash 包含 instance_id，不同 instance_id 产生不同缓存键
2. generate_image 在 future 上添加整体超时，不会永久阻塞
3. process_image 在 future 上添加整体超时，不会永久阻塞
4. _execute_task 在 set_result 前检查 future.done()，避免 InvalidStateError

修复要点：
- _get_prompt_hash 新增 instance_id 参数并参与哈希
- _generate_image_impl 和 generate_image 调用时传入 instance_id
- generate_image / process_image 用 asyncio.wait_for 包装 await future
- _execute_task 的 set_result 调用前增加 future.done() 检查
"""
import asyncio
import inspect
import os
import sys
import time
from typing import Any, Dict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def check_cache_key_includes_instance_id() -> list[str]:
    """场景1：相同 prompt+尺寸+步数+guidance 但不同 instance_id 应产生不同缓存键。"""
    issues: list[str] = []
    from core.image.image_service_client import ImageServiceClient

    client = ImageServiceClient.__new__(ImageServiceClient)

    key_a = client._get_prompt_hash(
        prompt="a cat", width=1024, height=1024,
        num_inference_steps=20, guidance_scale=7.5, instance_id="default",
    )
    key_b = client._get_prompt_hash(
        prompt="a cat", width=1024, height=1024,
        num_inference_steps=20, guidance_scale=7.5, instance_id="lora_v2",
    )
    key_c = client._get_prompt_hash(
        prompt="a cat", width=1024, height=1024,
        num_inference_steps=20, guidance_scale=7.5, instance_id="default",
    )

    if key_a == key_b:
        issues.append(
            f"不同 instance_id 的缓存键相同（a={key_a}, b={key_b}），会导致缓存污染"
        )
    if key_a != key_c:
        issues.append(
            f"相同 instance_id 的缓存键应一致（a={key_a}, c={key_c}），缓存键不稳定"
        )

    return issues


def check_cache_key_signature_has_instance_id() -> list[str]:
    """场景2：_get_prompt_hash 函数签名应包含 instance_id 参数。"""
    issues: list[str] = []
    from core.image.image_service_client import ImageServiceClient

    sig = inspect.signature(ImageServiceClient._get_prompt_hash)
    params = list(sig.parameters.keys())
    # 参数应包含：self, prompt, width, height, num_inference_steps, guidance_scale, instance_id
    if "instance_id" not in params:
        issues.append(f"_get_prompt_hash 签名缺少 instance_id 参数，实际参数: {params}")

    return issues


def check_generate_image_has_overall_timeout() -> list[str]:
    """场景3：generate_image 不应使用裸 await future（必须包装 wait_for）。"""
    issues: list[str] = []
    import re
    from core.image.image_service_client import ImageServiceClient

    src = inspect.getsource(ImageServiceClient.generate_image)

    # 必须存在 asyncio.wait_for 调用
    if "asyncio.wait_for" not in src:
        issues.append("generate_image 源码中未找到 asyncio.wait_for，缺少整体超时")
        return issues

    # 必须有某个 wait_for 调用的参数中包含 'future'（用正则跨行匹配）
    # 模式：asyncio.wait_for( 后面 100 字符内出现 future
    pattern = re.compile(r"asyncio\.wait_for\s*\((.{0,100}?)\)", re.DOTALL)
    found_future_wait = False
    for m in pattern.finditer(src):
        if "future" in m.group(1):
            found_future_wait = True
            break
    if not found_future_wait:
        issues.append(
            "generate_image 的 asyncio.wait_for 调用未作用于 future（仅作用于 queue.put）"
        )

    # 不应再有裸 `return await future`（无 wait_for 包装）
    if "return await future\n" in src:
        issues.append("generate_image 仍存在裸 `return await future`，未加超时")

    return issues


def check_process_image_has_overall_timeout() -> list[str]:
    """场景4：process_image 不应使用裸 await future（必须包装 wait_for）。"""
    issues: list[str] = []
    import re
    from core.image.image_service_client import ImageServiceClient

    src = inspect.getsource(ImageServiceClient.process_image)
    if "asyncio.wait_for" not in src:
        issues.append("process_image 源码中未找到 asyncio.wait_for，缺少整体超时")
        return issues

    pattern = re.compile(r"asyncio\.wait_for\s*\((.{0,100}?)\)", re.DOTALL)
    found_future_wait = False
    for m in pattern.finditer(src):
        if "future" in m.group(1):
            found_future_wait = True
            break
    if not found_future_wait:
        issues.append(
            "process_image 的 asyncio.wait_for 调用未作用于 future（仅作用于 queue.put）"
        )

    if "return await future\n" in src:
        issues.append("process_image 仍存在裸 `return await future`，未加超时")

    return issues


def check_execute_task_checks_done_before_set_result() -> list[str]:
    """场景5：_execute_task 在 set_result 前应检查 future.done()。"""
    issues: list[str] = []
    from core.image.image_service_client import ImageServiceClient

    src = inspect.getsource(ImageServiceClient._execute_task)
    # 统计 set_result 出现次数和 future.done() 检查次数
    set_result_count = src.count("future.set_result")
    done_check_count = src.count("if not future.done()")

    if set_result_count == 0:
        issues.append("_execute_task 源码中未找到 future.set_result 调用")
    elif done_check_count < set_result_count:
        issues.append(
            f"_execute_task 中 set_result 出现 {set_result_count} 次，"
            f"但 future.done() 检查只有 {done_check_count} 次，"
            "每次 set_result 前都应检查 done()"
        )

    return issues


def check_generate_image_timeout_actually_fires() -> list[str]:
    """场景6：generate_image 在 worker 卡死时应在超时后抛 RuntimeError，不永久阻塞。"""
    issues: list[str] = []
    from core.image.image_service_client import ImageServiceClient

    async def run():
        # 构造一个客户端，但不启动真正的 worker
        client = ImageServiceClient.__new__(ImageServiceClient)
        client.websocket_client = None
        client.connected = False
        client.request_timeout = 0.3  # 缩短超时，加速测试
        client.session_id = "test"
        client.requests = {}
        client.max_queue_size = 10
        client.queue = asyncio.Queue(maxsize=10)
        client.worker_task = None
        client.cache_size = 50
        client.cache = {}
        client.cache_lock = asyncio.Lock()

        # 替换 connect 避免真实连接
        async def fake_connect():
            return True
        client.connect = fake_connect

        # 启动一个不消费队列的 worker（模拟卡死）
        async def stuck_worker():
            await asyncio.sleep(60)
        client.worker_task = asyncio.create_task(stuck_worker())

        # 直接调用 generate_image，让它走完整路径
        # 由于 worker 不消费队列，future 永远不会被设置
        # generate_image 应在 request_timeout + 10 秒后抛 RuntimeError
        start = time.perf_counter()
        try:
            await client.generate_image(
                prompt="test",
                width=512,
                height=512,
                num_inference_steps=1,
                guidance_scale=0.0,
                instance_id="default",
                save_to_file=False,
            )
            elapsed = time.perf_counter() - start
            issues.append(
                f"generate_image 应抛 RuntimeError 但未抛出，耗时 {elapsed:.2f}s"
            )
        except RuntimeError as e:
            elapsed = time.perf_counter() - start
            if "整体超时" not in str(e):
                issues.append(f"RuntimeError 信息不匹配: {e}")
            # 应在 (request_timeout + 10) + 1 秒内返回
            max_expected = client.request_timeout + 10.0 + 2.0
            if elapsed > max_expected:
                issues.append(
                    f"超时返回耗时 {elapsed:.2f}s，超过预期 {max_expected:.2f}s"
                )
        except Exception as e:
            issues.append(f"意外异常类型: {type(e).__name__}: {e}")
        finally:
            client.worker_task.cancel()
            try:
                await client.worker_task
            except asyncio.CancelledError:
                pass

    try:
        asyncio.run(asyncio.wait_for(run(), timeout=20.0))
    except asyncio.TimeoutError:
        issues.append("run() 本身超时，generate_image 的超时未生效（可能永久阻塞）")

    return issues


def check_cache_uses_instance_id_in_generate_image_impl() -> list[str]:
    """场景7：_generate_image_impl 调用 _get_prompt_hash 时应传入 instance_id。"""
    issues: list[str] = []
    from core.image.image_service_client import ImageServiceClient

    src = inspect.getsource(ImageServiceClient._generate_image_impl)
    # 检查 _get_prompt_hash 调用是否包含 instance_id
    if "_get_prompt_hash" not in src:
        issues.append("_generate_image_impl 未调用 _get_prompt_hash")
        return issues

    # 截取 _get_prompt_hash 调用片段
    idx = src.index("_get_prompt_hash")
    call_snippet = src[idx:idx + 200]
    if "instance_id" not in call_snippet:
        issues.append(
            f"_generate_image_impl 调用 _get_prompt_hash 时未传入 instance_id，"
            f"调用片段: {call_snippet[:120]}"
        )

    return issues


def check_cache_uses_instance_id_in_generate_image() -> list[str]:
    """场景8：generate_image 调用 _get_prompt_hash 时也应传入 instance_id。"""
    issues: list[str] = []
    from core.image.image_service_client import ImageServiceClient

    src = inspect.getsource(ImageServiceClient.generate_image)
    if "_get_prompt_hash" not in src:
        # generate_image 可能直接复用 _generate_image_impl 的缓存逻辑
        # 但根据修复，generate_image 自己也做了缓存检查，应调用 _get_prompt_hash
        issues.append("generate_image 未调用 _get_prompt_hash（缓存检查可能缺失）")
        return issues

    idx = src.index("_get_prompt_hash")
    call_snippet = src[idx:idx + 200]
    if "instance_id" not in call_snippet:
        issues.append(
            f"generate_image 调用 _get_prompt_hash 时未传入 instance_id，"
            f"调用片段: {call_snippet[:120]}"
        )

    return issues


def main() -> int:
    print("=" * 70)
    print("P0-14 验证：image_service_client.py 缓存键 + 超时")
    print("=" * 70)

    all_issues: list[str] = []
    checks = [
        ("缓存键包含 instance_id，不同实例产生不同键", check_cache_key_includes_instance_id),
        ("_get_prompt_hash 签名包含 instance_id 参数", check_cache_key_signature_has_instance_id),
        ("generate_image 添加整体超时（asyncio.wait_for）", check_generate_image_has_overall_timeout),
        ("process_image 添加整体超时（asyncio.wait_for）", check_process_image_has_overall_timeout),
        ("_execute_task set_result 前检查 future.done()", check_execute_task_checks_done_before_set_result),
        ("generate_image 超时实际生效（worker 卡死场景）", check_generate_image_timeout_actually_fires),
        ("_generate_image_impl 传 instance_id 给 _get_prompt_hash", check_cache_uses_instance_id_in_generate_image_impl),
        ("generate_image 传 instance_id 给 _get_prompt_hash", check_cache_uses_instance_id_in_generate_image),
    ]

    for name, fn in checks:
        print(f"\n[检查] {name}")
        try:
            issues = fn()
        except Exception as e:
            issues = [f"检查本身抛异常: {type(e).__name__}: {e}"]

        if issues:
            for i in issues:
                print(f"  FAIL: {i}")
            all_issues.extend(issues)
        else:
            print("  PASS")

    print("\n" + "=" * 70)
    if all_issues:
        print(f"结果：失败（{len(all_issues)} 项问题）")
        return 1
    print("结果：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
