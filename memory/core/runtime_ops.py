from collections import defaultdict
import asyncio
import threading
import time
from typing import Any, Dict, List

from memory.core.lock_utils import get_read_lock, get_write_lock


def start_auto_save(manager: Any, *, logger: Any) -> None:
    if hasattr(manager, "auto_save_thread") and manager.auto_save_thread.is_alive():
        logger.warning(f"用户 {manager.user_id} 已存在运行中的自动保存线程，停止旧线程")
        manager._stop_event.set()
        try:
            if (
                hasattr(manager.auto_save_thread, "_started")
                and manager.auto_save_thread._started.is_set()
            ):
                manager.auto_save_thread.join(timeout=3.0)
        except RuntimeError as e:
            logger.error(f"停止旧自动保存线程时出错: {e}")

    manager._stop_event.clear()
    manager.auto_save_thread = threading.Thread(
        target=manager._auto_save_loop,
        daemon=True,
        name=f"auto-save-{manager.user_id[:8]}",
    )
    try:
        manager.auto_save_thread.start()
        logger.info(f"为用户 {manager.user_id} 启动自动保存线程，间隔 {manager.auto_save_interval} 秒")
    except RuntimeError as e:
        logger.error(f"启动自动保存线程失败: {e}")
        manager.auto_save_interval = 0


def start_async_save(manager: Any, *, logger: Any) -> None:
    if not manager._save_thread or not manager._save_thread.is_alive():
        manager._save_thread = threading.Thread(
            target=manager._async_save_loop,
            daemon=True,
            name=f"async-save-{manager.user_id[:8]}",
        )
        manager._save_thread.start()
        logger.info(f"为用户 {manager.user_id} 启动异步保存线程")


def async_save_loop(manager: Any, *, logger: Any) -> None:
    while not manager._stop_event.is_set():
        try:
            if manager._save_event.wait(timeout=manager._save_delay):
                manager._save_event.clear()
                time.sleep(min(manager._save_delay, 1.0))
                manager._process_save_queue()
        except Exception as e:
            logger.error(f"异步保存循环异常: {e}")
            if manager._stop_event.wait(timeout=60):
                break


def process_save_queue(manager: Any, *, logger: Any) -> None:
    if manager._is_saving:
        return

    manager._is_saving = True
    should_save = False
    try:
        with get_write_lock(manager):
            if not manager._save_queue and not manager._index_updated:
                return

            save_count = 0
            while manager._save_queue and save_count < manager._save_batch_size:
                save_count += 1
                try:
                    manager._save_queue.popleft()
                except IndexError:
                    break

            if manager._index_updated:
                manager._refresh_keyword_index_locked()
                manager._index_updated = False

            should_save = True

        if should_save:
            manager._safe_save_all()
            logger.debug("异步保存完成")
    finally:
        manager._is_saving = False


def schedule_save(manager: Any) -> None:
    if len(manager._save_queue) < manager._save_queue.maxlen:
        manager._save_queue.append(time.time())
        manager._start_async_save()
        manager._save_event.set()


def schedule_trim(manager: Any, *, logger: Any) -> None:
    if manager._trim_scheduled:
        return

    manager._trim_scheduled = True
    if manager._trim_timer:
        manager._trim_timer.cancel()

    manager._trim_timer = threading.Timer(manager._trim_delay, manager._delayed_trim)
    manager._trim_timer.daemon = True
    manager._trim_timer.start()
    logger.debug(f"已调度延迟修剪，延迟 {manager._trim_delay} 秒")


def delayed_trim(manager: Any, *, logger: Any) -> None:
    manager._trim_scheduled = False
    need_save = False
    removed_count = 0
    with get_write_lock(manager):
        try:
            removed = manager._trim_short_term_memory()
            if isinstance(removed, list):
                removed_count = len(removed)
            need_save = True
            logger.debug("延迟修剪完成")
        except Exception as e:
            logger.error(f"延迟修剪异常: {e}")
    if need_save:
        manager._schedule_save()

    if removed_count > 0:
        _trigger_immediate_distillation(manager, logger=logger, removed_count=removed_count)


def trim_short_term_memory(manager: Any, *, trim_short_term_memory_fn: Any, logger: Any) -> List[Dict[str, Any]]:
    removed_messages = []
    with get_write_lock(manager):
        trim_threshold = getattr(manager, 'trim_threshold', manager.max_short_term)
        trimmed, removed = trim_short_term_memory_fn(
            manager.short_term_memory,
            manager.max_short_term,
            manager._detect_topics,
            trim_threshold=trim_threshold,
        )
        manager.short_term_memory = trimmed
        removed_messages = removed

        if removed_messages:
            _preserve_removed_to_weighted(manager, removed_messages, logger=logger)

        # 仅在实际移除消息时输出 INFO 日志，避免空修剪产生误导性日志（如 "779/60 移除0条"）
        if removed_messages:
            logger.info(
                f"短期记忆已修剪，当前保留 {len(manager.short_term_memory)}/{trim_threshold} 条消息，移除 {len(removed_messages)} 条（修剪阈值 {trim_threshold}）"
            )
        else:
            logger.debug(
                f"短期记忆修剪检查通过，当前 {len(manager.short_term_memory)} 条，阈值 {trim_threshold}，无需移除"
            )
    return removed_messages


def _preserve_removed_to_weighted(manager: Any, removed_messages: List[Dict[str, Any]], *, logger: Any) -> None:
    preserved = 0
    for msg in removed_messages:
        mid = msg.get("id")
        if not mid:
            continue
        if mid in manager.weighted_memories:
            continue
        content = msg.get("content", "")
        if not content or len(content.strip()) < 5:
            continue
        manager.weighted_memories[mid] = msg
        preserved += 1
        if hasattr(manager, '_mark_keyword_index_dirty_locked'):
            manager._mark_keyword_index_dirty_locked(mid)
    if preserved > 0:
        logger.info(f"已将 {preserved} 条被修剪消息保存到加权记忆，等待蒸馏")


def _trigger_immediate_distillation(manager: Any, *, logger: Any, removed_count: int = 0) -> None:
    """
    修剪后立即在后台线程触发蒸馏（不再延迟60秒，不再防抖跳过）。
    
    被修剪的消息已由 _preserve_removed_to_weighted 保存到加权记忆，
    后台蒸馏线程会立即处理所有未蒸馏的加权记忆。
    """
    if manager._distillation_thread and manager._distillation_thread.is_alive():
        logger.debug("蒸馏线程已在运行，跳过调度")
        return

    undistilled_count = 0
    # 必须走读写锁（_rw_lock），不能用 manager.lock（threading.RLock）——
    # 生产环境 _use_rw_lock=True，写路径走的是 _rw_lock.write_lock()，
    # 这里若用 manager.lock 与写路径互不相干，会触发
    # "dictionary changed size during iteration"。
    with get_read_lock(manager):
        # 取 list 快照双重保险：即便未来有其他绕过锁的写入路径也不会崩
        for msg in list(manager.weighted_memories.values()):
            if not msg.get("is_distilled"):
                undistilled_count += 1

    if undistilled_count == 0:
        logger.debug("没有待蒸馏的记忆，跳过")
        return

    logger.info(
        f"修剪后立即触发蒸馏，发现 {undistilled_count} 条待蒸馏记忆"
        f"（本次修剪移除 {removed_count} 条）"
    )

    def _run_distillation():
        try:
            from memory.nightly.task_runner import NightlyTaskRunner

            runner = NightlyTaskRunner(
                {
                "distillation_enabled": True,
                "distillation_threshold_hours": 0,
                "max_distill_per_night": 30,
            }
            )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                distilled = loop.run_until_complete(
                    runner.distill_memories_async(manager.user_id, manager)
                )
                logger.info(f"修剪后蒸馏完成，蒸馏了 {distilled} 条记忆")
            finally:
                loop.close()

        except Exception as e:
            logger.error(f"修剪后蒸馏异常: {e}")

    manager._distillation_thread = threading.Thread(
        target=_run_distillation,
        daemon=True,
        name=f"distill-{manager.user_id[:8]}",
    )
    manager._distillation_thread.start()
    logger.info("已启动后台蒸馏线程")


def update_topic_index(manager: Any) -> None:
    new_topics = defaultdict(list)
    all_messages = list(manager.short_term_memory)
    if manager.weighted_memories:
        # 取 list 快照，避免 extend 期间 dict 被并发修改
        all_messages.extend(list(manager.weighted_memories.values()))
    for message in all_messages:
        for topic in message.get("topics", []):
            new_topics[topic].append(message)
    manager.topics = new_topics


def update_topic_index_incremental(manager: Any, memory: Dict[str, Any]) -> None:
    for topic in memory.get("topics", []):
        topic_text = str(topic).strip()
        if topic_text:
            manager.topics[topic_text].append(memory)


def extract_core_fields(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    core_fields = ["role", "content", "timestamp"]
    result = []
    for msg in messages:
        filtered_msg = {k: v for k, v in msg.items() if k in core_fields}
        result.append(filtered_msg)
    return result


def auto_save_loop(manager: Any, *, logger: Any) -> None:
    logger.info(f"自动保存循环启动，间隔 {manager.auto_save_interval} 秒")
    try:
        while not manager._stop_event.is_set():
            try:
                if manager._stop_event.wait(timeout=manager.auto_save_interval):
                    break

                current_time = time.time()
                with get_write_lock(manager):
                    should_save = (
                        current_time - manager.last_modified_time > 60
                        and current_time - manager.last_save_time > manager.auto_save_interval
                    )

                if should_save:
                    manager.save_memory()
                    logger.debug(f"[{time.ctime()}] 为用户 {manager.user_id} 自动保存记忆")

            except Exception as e:
                logger.error(f"自动保存循环异常: {e}")
                if manager._stop_event.wait(timeout=60):
                    break
    except SystemExit:
        logger.info("收到系统退出信号，停止自动保存循环")
    except KeyboardInterrupt:
        logger.info("收到键盘中断，停止自动保存循环")
    finally:
        try:
            current_time = time.time()
            should_final_save = False
            with get_write_lock(manager):
                should_final_save = current_time - manager.last_save_time > 300
            if should_final_save:
                logger.info("自动保存循环退出前执行最后一次保存")
                manager.save_memory()
        except Exception as final_save_error:
            logger.error(f"退出前保存失败: {final_save_error}")
        logger.info("自动保存循环已停止")


def save_memory(manager: Any) -> None:
    manager._schedule_save()


def sync_save_memory(manager: Any) -> None:
    manager._safe_save_all()
