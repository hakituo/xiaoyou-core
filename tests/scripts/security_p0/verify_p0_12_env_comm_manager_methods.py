"""P0-12 验证脚本：env_communication_manager.py 调用不存在方法

验证目标：
1. MessageQueue.put(message) 方法存在并可调用，不再抛 AttributeError
2. FileBasedSharedStorage.list_keys(env_id) 方法存在并返回正确结果
3. _process_message 调用 queue.put() 不再失败
4. check_messages_from_shared_storage 能完整执行（list_keys + read + write 全链路）
5. put 方法不仅入队，还会通知订阅者

修复要点：
- MessageQueue 新增 put(message) 方法：内部 queue.put + _notify_subscribers
- MessageQueue 新增 get(timeout) / subscribe(topic, callback) 辅助方法
- FileBasedSharedStorage 新增 list_keys(env_id)：扫描 env 目录下的 .json 文件名
"""
import asyncio
import inspect
import os
import shutil
import sys
import tempfile
import time
from typing import List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def check_message_queue_has_put_method() -> list[str]:
    """场景1：MessageQueue 必须定义 put 方法。"""
    issues: list[str] = []
    from core.env.env_communication_manager import MessageQueue, Message

    if not hasattr(MessageQueue, "put"):
        issues.append("MessageQueue 缺少 put 方法")
        return issues

    if not callable(getattr(MessageQueue, "put")):
        issues.append("MessageQueue.put 不是可调用方法")
        return issues

    # 实际调用一次，确保不抛 AttributeError
    mq = MessageQueue("test_queue")
    msg = Message(source="a", target="b", topic="test", data={"x": 1})
    try:
        mq.put(msg)
    except AttributeError as e:
        issues.append(f"mq.put(message) 抛 AttributeError: {e}")
    except Exception as e:
        issues.append(f"mq.put(message) 抛意外异常: {type(e).__name__}: {e}")

    # 确认消息真的进入了内部 queue
    if mq.queue.qsize() != 1:
        issues.append(f"put 后内部 queue.qsize()={mq.queue.qsize()}，期望 1")

    return issues


def check_file_storage_has_list_keys() -> list[str]:
    """场景2：FileBasedSharedStorage 必须定义 list_keys 方法。"""
    issues: list[str] = []
    from core.env.env_communication_manager import FileBasedSharedStorage

    if not hasattr(FileBasedSharedStorage, "list_keys"):
        issues.append("FileBasedSharedStorage 缺少 list_keys 方法")
        return issues

    if not callable(getattr(FileBasedSharedStorage, "list_keys")):
        issues.append("FileBasedSharedStorage.list_keys 不是可调用方法")
        return issues

    # 用临时目录测试
    tmpdir = tempfile.mkdtemp(prefix="xiaoyou_test_storage_")
    try:
        storage = FileBasedSharedStorage(storage_dir=tmpdir)
        # 写入 3 个 key
        async def seed():
            await storage.write("key1", {"v": 1}, env_id="env_a")
            await storage.write("key2", {"v": 2}, env_id="env_a")
            await storage.write("key3", {"v": 3}, env_id="env_b")
        asyncio.run(seed())

        # list_keys 应返回 env_a 下的 2 个 key
        keys_a = storage.list_keys(env_id="env_a")
        keys_b = storage.list_keys(env_id="env_b")
        keys_empty = storage.list_keys(env_id="nonexistent")

        if set(keys_a) != {"key1", "key2"}:
            issues.append(f"env_a 的 keys 应为 {{key1, key2}}，实际 {keys_a}")
        if set(keys_b) != {"key3"}:
            issues.append(f"env_b 的 keys 应为 {{key3}}，实际 {keys_b}")
        if keys_empty != []:
            issues.append(f"不存在的 env 应返回 []，实际 {keys_empty}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return issues


def check_process_message_does_not_raise() -> list[str]:
    """场景3：_process_message 调用 queue.put() 不再抛 AttributeError。"""
    issues: list[str] = []
    from core.env.env_communication_manager import (
        EnvironmentCommunicationManager,
        Message,
    )

    manager = EnvironmentCommunicationManager(env_id="test_env")
    msg = Message(
        source="src",
        target="test_env",  # 匹配 manager.env_id，走本地处理分支
        topic="test_topic",
        data={"hello": "world"},
    )

    try:
        manager._process_message(msg)
    except AttributeError as e:
        issues.append(f"_process_message 抛 AttributeError: {e}")
    except Exception as e:
        issues.append(f"_process_message 抛意外异常: {type(e).__name__}: {e}")

    # 消息应该进入名为 test_topic 的队列
    if "test_topic" not in manager.message_queues:
        issues.append("消息处理后未创建 test_topic 队列")
    else:
        q = manager.message_queues["test_topic"]
        if q.queue.qsize() != 1:
            issues.append(f"队列 test_topic 大小应为 1，实际 {q.queue.qsize()}")

    return issues


def check_check_messages_from_shared_storage_full_chain() -> list[str]:
    """场景4：check_messages_from_shared_storage 全链路（list_keys + read + write）。"""
    issues: list[str] = []
    from core.env.env_communication_manager import (
        EnvironmentCommunicationManager,
        FileBasedSharedStorage,
        Message,
    )

    tmpdir = tempfile.mkdtemp(prefix="xiaoyou_test_chain_")
    try:
        manager = EnvironmentCommunicationManager(env_id="chain_env")
        # 替换 shared_storage 为临时目录版本
        manager.shared_storage = FileBasedSharedStorage(storage_dir=tmpdir)

        # 预写一条 pending 消息
        msg = Message(
            source="src",
            target="chain_env",
            topic="chain.topic",
            data={"n": 1},
        )
        async def seed():
            await manager.shared_storage.write(
                key=f"msg_{msg.message_id}",
                data={
                    "message_id": msg.message_id,
                    "source": msg.source,
                    "target": msg.target,
                    "topic": msg.topic,
                    "data": msg.data,
                    "timestamp": msg.timestamp,
                    "response_to": msg.response_to,
                    "priority": msg.priority,
                    "status": "pending",
                },
                env_id="chain_env",
            )
        asyncio.run(seed())

        # 调用 check_messages_from_shared_storage，应完整跑通
        try:
            asyncio.run(manager.check_messages_from_shared_storage())
        except AttributeError as e:
            issues.append(f"check_messages_from_shared_storage 抛 AttributeError: {e}")
            return issues
        except Exception as e:
            issues.append(f"check_messages_from_shared_storage 抛意外异常: {type(e).__name__}: {e}")
            return issues

        # 消息应被处理：进入队列 chain（topic split by '.'）
        if "chain" not in manager.message_queues:
            issues.append("处理后未创建 'chain' 队列（topic 应按 '.' 切分）")
        else:
            q = manager.message_queues["chain"]
            if q.queue.qsize() != 1:
                issues.append(f"'chain' 队列大小应为 1，实际 {q.queue.qsize()}")

        # 消息状态应被更新为 processed
        async def read_back():
            return await manager.shared_storage.read(
                key=f"msg_{msg.message_id}", env_id="chain_env"
            )
        updated = asyncio.run(read_back())
        if not updated or updated.get("status") != "processed":
            issues.append(
                f"消息状态应为 'processed'，实际 {updated.get('status') if updated else 'None'}"
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return issues


def check_put_notifies_subscribers() -> list[str]:
    """场景5：put 方法应触发 _notify_subscribers，调用订阅者回调。"""
    issues: list[str] = []
    from core.env.env_communication_manager import MessageQueue, Message

    mq = MessageQueue("subscriber_test")
    received: List[Message] = []
    mq.subscribe("topic_x", lambda m: received.append(m))

    msg = Message(source="a", target="b", topic="topic_x", data={"i": 1})
    mq.put(msg)

    if len(received) != 1:
        issues.append(f"订阅者应收到 1 条消息，实际 {len(received)}")
    elif received[0].message_id != msg.message_id:
        issues.append("订阅者收到的消息 ID 不匹配")

    # 订阅了别的 topic 不应被触发
    received.clear()
    other_msg = Message(source="a", target="b", topic="topic_y", data={"i": 2})
    mq.put(other_msg)
    if received:
        issues.append(f"订阅 topic_x 的回调不应因 topic_y 消息被触发，实际收到 {len(received)} 条")

    return issues


def check_get_method_returns_message() -> list[str]:
    """场景6：get 方法能从队列取回消息。"""
    issues: list[str] = []
    from core.env.env_communication_manager import MessageQueue, Message

    mq = MessageQueue("get_test")
    msg = Message(source="a", target="b", topic="t", data={"x": 1})
    mq.put(msg)

    got = mq.get(timeout=1.0)
    if got is None:
        issues.append("get(timeout=1.0) 应返回消息，实际返回 None")
    elif got.message_id != msg.message_id:
        issues.append("get 返回的消息 ID 不匹配")

    # 队列空时 get 应立即返回 None
    empty = mq.get(timeout=0.1)
    if empty is not None:
        issues.append(f"空队列 get 应返回 None，实际 {empty}")

    return issues


def main() -> int:
    print("=" * 70)
    print("P0-12 验证：env_communication_manager.py 调用不存在方法")
    print("=" * 70)

    all_issues: list[str] = []
    checks = [
        ("MessageQueue.put 方法存在且可调用", check_message_queue_has_put_method),
        ("FileBasedSharedStorage.list_keys 方法存在且正确", check_file_storage_has_list_keys),
        ("_process_message 不再抛 AttributeError", check_process_message_does_not_raise),
        ("check_messages_from_shared_storage 全链路跑通", check_check_messages_from_shared_storage_full_chain),
        ("put 方法触发订阅者通知", check_put_notifies_subscribers),
        ("get 方法能取回消息", check_get_method_returns_message),
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
