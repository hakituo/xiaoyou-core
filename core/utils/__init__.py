"""
Core Utils Package

为避免历史代码 `from core.utils.<old_module> import ...` 与
`import core.utils.<old_module> as x` 全部失效，本文件在分组重构后
将子包内的模块以旧名重新绑定到 sys.modules，并提供常用顶层符号的兼容转发。

分组映射（旧模块名 -> 新位置）：
  - async_locks / async_subprocess / async_tasks / resource_lock / singleton / saga_manager
        -> core.utils.concurrency.*
  - error_collector / error_handler / error_handlers / log_sanitizer
        -> core.utils.errors.*
  - time_utils / timestamp_utils
        -> core.utils.time.*
  - data_paths / data_paths_migrations / scope_registry / conversation_labels
        -> core.utils.data.*
"""

import sys
import importlib

# 顶层常用符号（原 core.utils 直接导出）
from core.utils.logger import (
    get_logger,
    get_module_logger,
    init_logging_system,
)
from core.utils.concurrency.singleton import (
    SingletonFactory,
    singleton,
)
from core.utils.concurrency.async_locks import LazyAsyncLock
from core.utils.concurrency.async_subprocess import run_subprocess_with_timeout
from core.utils.concurrency.async_tasks import spawn_bg_task
from core.utils.concurrency.resource_lock import (
    GlobalResourceLock,
    get_resource_lock,
)
from core.utils.concurrency.saga_manager import (
    SagaStep,
    SagaTransaction,
)

# 子包（可通过 core.utils.concurrency / errors / time / data 访问）
from core.utils import concurrency, errors, logging, time, data  # noqa: F401

# ---------------------------------------------------------------------------
# 旧模块名 -> 新模块对象 的兼容绑定
# 让 `from core.utils.data_paths import X` 与 `import core.utils.data_paths as dp`
# 继续解析到重构后的真实模块。
# ---------------------------------------------------------------------------
# 注意：必须用 importlib.import_module 按完整模块名强制导入子模块，
# 不能用 `import core.utils.concurrency.singleton as _m` —— 因为 concurrency/__init__
# 把同名函数 singleton 导入了包命名空间，属性访问会拿到函数而非模块。
_m_async_locks = importlib.import_module("core.utils.concurrency.async_locks")
_m_async_subprocess = importlib.import_module("core.utils.concurrency.async_subprocess")
_m_async_tasks = importlib.import_module("core.utils.concurrency.async_tasks")
_m_resource_lock = importlib.import_module("core.utils.concurrency.resource_lock")
_m_singleton = importlib.import_module("core.utils.concurrency.singleton")
_m_saga_manager = importlib.import_module("core.utils.concurrency.saga_manager")

_m_error_collector = importlib.import_module("core.utils.errors.error_collector")
_m_error_handler = importlib.import_module("core.utils.errors.error_handler")
_m_error_handlers = importlib.import_module("core.utils.errors.error_handlers")
_m_log_sanitizer = importlib.import_module("core.utils.errors.log_sanitizer")

_m_time_utils = importlib.import_module("core.utils.time.time_utils")
_m_timestamp_utils = importlib.import_module("core.utils.time.timestamp_utils")

_m_data_paths = importlib.import_module("core.utils.data.data_paths")
_m_data_paths_migrations = importlib.import_module("core.utils.data.data_paths_migrations")
_m_scope_registry = importlib.import_module("core.utils.data.scope_registry")
_m_conversation_labels = importlib.import_module("core.utils.data.conversation_labels")

_LEGACY_MODULE_BINDINGS = {
    "core.utils.async_locks": _m_async_locks,
    "core.utils.async_subprocess": _m_async_subprocess,
    "core.utils.async_tasks": _m_async_tasks,
    "core.utils.resource_lock": _m_resource_lock,
    "core.utils.singleton": _m_singleton,
    "core.utils.saga_manager": _m_saga_manager,
    "core.utils.error_collector": _m_error_collector,
    "core.utils.error_handler": _m_error_handler,
    "core.utils.error_handlers": _m_error_handlers,
    "core.utils.log_sanitizer": _m_log_sanitizer,
    "core.utils.time_utils": _m_time_utils,
    "core.utils.timestamp_utils": _m_timestamp_utils,
    "core.utils.data_paths": _m_data_paths,
    "core.utils.data_paths_migrations": _m_data_paths_migrations,
    "core.utils.scope_registry": _m_scope_registry,
    "core.utils.conversation_labels": _m_conversation_labels,
}

for _legacy_name, _real_module in _LEGACY_MODULE_BINDINGS.items():
    sys.modules[_legacy_name] = _real_module

__all__ = [
    "get_logger",
    "get_module_logger",
    "init_logging_system",
    "SingletonFactory",
    "singleton",
    "LazyAsyncLock",
    "run_subprocess_with_timeout",
    "spawn_bg_task",
    "GlobalResourceLock",
    "get_resource_lock",
    "SagaStep",
    "SagaTransaction",
    "concurrency",
    "errors",
    "logging",
    "time",
    "data",
]
