from collections import OrderedDict
from typing import Any, Dict, Optional

from memory.core.lock_utils import get_write_lock


class LRUCache:
    """基于 OrderedDict 的 LRU 缓存，淘汰复杂度 O(1)"""

    def __init__(self, max_size: int):
        self._max_size = max(0, max_size)
        self._data: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, value: Dict[str, Any]) -> None:
        if self._max_size <= 0:
            return
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = value
        else:
            self._data[key] = value
            if len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def remove(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()


def update_cache(manager: Any, memory_id: str, memory: Dict[str, Any]) -> None:
    uc = getattr(manager, '_unified_cache', None)
    if uc is not None:
        uc.update_memory_access(memory_id, memory.copy())
        manager._cache["access_count"][memory_id] = (
            manager._cache["access_count"].get(memory_id, 0) + 1
        )
    else:
        with get_write_lock(manager):
            manager._cache["access_count"][memory_id] = (
                manager._cache["access_count"].get(memory_id, 0) + 1
            )
            manager._cache["l1"].put(memory_id, memory.copy())
            manager._cache["l2"].put(memory_id, memory.copy())


def get_from_cache(manager: Any, memory_id: str) -> Optional[Dict[str, Any]]:
    uc = getattr(manager, '_unified_cache', None)
    if uc is not None:
        val = uc.get_memory(memory_id)
        if val is not None:
            manager._cache["access_count"][memory_id] = (
                manager._cache["access_count"].get(memory_id, 0) + 1
            )
            return val.copy()
        return None
    else:
        with get_write_lock(manager):
            l1_hit = manager._cache["l1"].get(memory_id)
            if l1_hit is not None:
                manager._cache["access_count"][memory_id] = (
                    manager._cache["access_count"].get(memory_id, 0) + 1
                )
                return l1_hit.copy()

            l2_hit = manager._cache["l2"].get(memory_id)
            if l2_hit is not None:
                manager._cache["access_count"][memory_id] = (
                    manager._cache["access_count"].get(memory_id, 0) + 1
                )
                manager._cache["l1"].put(memory_id, l2_hit.copy())
                return l2_hit.copy()

            return None
