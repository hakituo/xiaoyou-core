#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调用来源提取

从调用栈里找出真正的业务层函数名（如 task_runner.py::distill_memories_async），
供 prompt 缓存命中率日志定位请求来源。
"""

import inspect
from typing import Optional


# 调用栈来源标签：跳过这些框架层，取真正的业务任务函数名
_SOURCE_SKIP = {
    "_caller_source", "stream_chat", "chat", "_do_chat", "_raw_chat",
    "build_payload", "rebuild_payload_for_system_order", "submit_llm_task",
}
# 这些目录/文件属于框架层（LLM 客户端、调度器、日志器），不作为来源
_FRAMEWORK_DIRS = ("openai_compat", "/llm/", "scheduler", "llm_logger.py")


def caller_source() -> Optional[str]:
    """返回 `文件名::函数名` 形式的业务调用来源，取不到时返回 None。"""
    try:
        for frame in inspect.stack()[1:]:
            name = frame.function
            if name in _SOURCE_SKIP:
                continue
            mod = frame.filename or ""
            if any(d in mod for d in _FRAMEWORK_DIRS):
                continue
            base = mod.replace("\\", "/").split("/")[-1]
            return f"{base}::{name}"
    except Exception:
        return None
    return None
