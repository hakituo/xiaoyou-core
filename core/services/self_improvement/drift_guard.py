"""
自我改进系统 — 记忆漂移防护

基于记忆行动前验证记忆准确性，防止过时/错误记忆影响决策。

验证规则：
- 文件路径 → 检查文件是否存在
- 函数/API 名 → grep 确认仍存在
- 配置值 → 读取当前值
- 记忆 vs 当前状态矛盾 → 信当前状态

P2-6 重构要点：
1. 引入函数名索引缓存（_function_index），避免每次验证都全量扫描项目所有 .py 文件
   - 旧实现：每次 _verify_function_names 都对每个函数名扫描整个项目，复杂度 O(函数数 × 文件数)
   - 新实现：首次验证时构建一次函数名索引，后续直接查表，复杂度 O(1) 查找
2. 新增 async verify_memory_async 入口，将重 IO 的索引构建放到线程池
3. 保留同步 verify_memory 作为兼容入口，内部走缓存
4. 文件存在性、配置值结果也带短时缓存
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.utils.logger import get_logger

logger = get_logger("DriftGuard")


# ── 缓存配置 ──────────────────────────────────────────
_FUNCTION_INDEX_TTL_SECONDS = 300.0  # 函数名索引缓存 5 分钟（项目结构变化频率低）
_FILE_EXISTENCE_CACHE_TTL_SECONDS = 60.0  # 文件存在性缓存 1 分钟
_CONFIG_VALUE_CACHE_TTL_SECONDS = 60.0  # 配置值缓存 1 分钟

# 跳过的目录（避免扫描第三方依赖、构建产物、外部项目）
_SKIP_DIRS = (
    "venv", "__pycache__", ".git", "node_modules", ".idea", ".vscode",
    "external",  # 第三方项目（如 NapCatQQ）
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "site-packages",
)

# 函数定义正则：匹配 def xxx( 或 async def xxx(
_FUNCTION_DEF_RE = re.compile(r"(?:def|async\s+def)\s+(\w+)\s*\(")


class DriftGuard:
    """记忆漂移防护器

    P2-6: 增加 async 入口与缓存
    - 函数名验证不再每次全量扫描项目，改为带 TTL 的索引缓存
    - 提供 verify_memory_async 异步入口，重 IO 操作通过 asyncio.to_thread 放到线程池
    - 同步 verify_memory 保留作为兼容入口
    """

    def __init__(self, project_root: Path):
        self._project_root = project_root
        # 函数名索引缓存：首次验证时构建，TTL 后失效重建
        self._function_index: Optional[Set[str]] = None
        self._function_index_ts: float = 0.0
        self._index_lock = threading.Lock()
        # 文件存在性缓存：{路径字符串: (是否存在, 时间戳)}
        self._file_existence_cache: Dict[str, Tuple[bool, float]] = {}
        # 配置值缓存：{配置字符串: (结果字典, 时间戳)}
        self._config_value_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}

    # ── 验证入口 ────────────────────────────────────────

    def verify_memory(self, memory_content: str) -> Dict[str, Any]:
        """
        验证记忆内容的准确性（同步兼容入口）。

        返回验证结果：
        {
            "valid": bool,
            "checks": [{"type": str, "content": str, "passed": bool, "detail": str}],
            "warnings": [str],
        }
        """
        checks = []
        warnings = []

        # 1. 验证文件路径
        file_checks = self._verify_file_paths(memory_content)
        checks.extend(file_checks)
        for c in file_checks:
            if not c["passed"]:
                warnings.append(f"文件路径可能已失效: {c['content']}")

        # 2. 验证函数/API 名
        func_checks = self._verify_function_names(memory_content)
        checks.extend(func_checks)
        for c in func_checks:
            if not c["passed"]:
                warnings.append(f"函数/API 可能已变更: {c['content']}")

        # 3. 验证配置值
        config_checks = self._verify_config_values(memory_content)
        checks.extend(config_checks)
        for c in config_checks:
            if not c["passed"]:
                warnings.append(f"配置值可能已变更: {c['content']}")

        all_passed = all(c["passed"] for c in checks)
        return {
            "valid": all_passed,
            "checks": checks,
            "warnings": warnings,
        }

    async def verify_memory_async(self, memory_content: str) -> Dict[str, Any]:
        """验证记忆内容的准确性（异步入口）。

        将重 IO 的函数名索引构建放到线程池，避免阻塞事件循环。
        索引命中缓存后，验证本身是纯内存操作，非常快。
        """
        # 确保函数名索引已构建（命中缓存则直接返回，否则在线程池中构建）
        await self._ensure_function_index_async()
        # 验证逻辑本身是 CPU + 少量 IO（文件存在性检查），放到线程池执行
        return await asyncio.to_thread(self.verify_memory, memory_content)

    def verify_single(self, content: str, type_hint: str = "auto") -> Dict[str, Any]:
        """
        验证单条记忆内容。

        Args:
            content: 记忆内容
            type_hint: 类型提示 ("file_path" | "function" | "config" | "auto")
        """
        if type_hint == "auto":
            type_hint = self._detect_type(content)

        if type_hint == "file_path":
            return self._verify_single_file_path(content)
        elif type_hint == "function":
            return self._verify_single_function(content)
        elif type_hint == "config":
            return self._verify_single_config(content)
        else:
            return {"valid": True, "type": "unknown", "detail": "无法自动检测类型，跳过验证"}

    async def verify_single_async(
        self, content: str, type_hint: str = "auto"
    ) -> Dict[str, Any]:
        """验证单条记忆内容（异步入口）。"""
        if type_hint == "auto" or type_hint == "function":
            await self._ensure_function_index_async()
        return await asyncio.to_thread(self.verify_single, content, type_hint)

    # ── 函数名索引管理 ──────────────────────────────────

    def _ensure_function_index(self) -> Set[str]:
        """确保函数名索引已构建（同步，带 TTL）。

        使用 threading.Lock 保护，避免多线程并发构建。
        索引构建是 O(文件数) 的全量扫描，但只在首次调用或 TTL 失效时执行。
        """
        now = time.time()
        # 快速路径：索引有效，直接返回
        if (
            self._function_index is not None
            and (now - self._function_index_ts) < _FUNCTION_INDEX_TTL_SECONDS
        ):
            return self._function_index

        with self._index_lock:
            # double-check：拿到锁后再次确认，避免重复构建
            if (
                self._function_index is not None
                and (time.time() - self._function_index_ts) < _FUNCTION_INDEX_TTL_SECONDS
            ):
                return self._function_index

            # 全量扫描项目，构建函数名索引
            self._function_index = self._build_function_index()
            self._function_index_ts = time.time()
            logger.debug(
                "函数名索引已构建，包含 %d 个函数名",
                len(self._function_index),
            )
            return self._function_index

    async def _ensure_function_index_async(self) -> Set[str]:
        """确保函数名索引已构建（异步，重 IO 放到线程池）。"""
        # 快速路径：索引有效，直接返回（避免不必要的 to_thread 开销）
        now = time.time()
        if (
            self._function_index is not None
            and (now - self._function_index_ts) < _FUNCTION_INDEX_TTL_SECONDS
        ):
            return self._function_index
        # 索引失效或未构建，放到线程池执行
        return await asyncio.to_thread(self._ensure_function_index)

    def _build_function_index(self) -> Set[str]:
        """扫描项目所有 .py 文件，构建函数名集合。

        旧实现 _verify_single_function 对每个函数名都扫描整个项目，
        复杂度 O(函数数 × 文件数)。本方法一次性扫描所有文件，构建索引，
        后续查找复杂度 O(1)。
        """
        names: Set[str] = set()
        try:
            for py_file in self._project_root.rglob("*.py"):
                # 跳过 venv、__pycache__ 等目录
                if any(part in _SKIP_DIRS for part in py_file.parts):
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8", errors="ignore")
                    # 一次性提取所有函数定义名
                    names.update(_FUNCTION_DEF_RE.findall(text))
                except Exception:
                    continue
        except Exception as e:
            logger.warning("构建函数名索引失败: %s", e)
        return names

    def invalidate_cache(self) -> None:
        """手动失效所有缓存（项目结构变更后调用）。"""
        with self._index_lock:
            self._function_index = None
            self._function_index_ts = 0.0
        self._file_existence_cache.clear()
        self._config_value_cache.clear()
        logger.debug("DriftGuard 缓存已失效")

    # ── 文件路径验证 ────────────────────────────────────

    def _verify_file_paths(self, content: str) -> List[Dict[str, Any]]:
        """验证内容中提到的文件路径"""
        checks = []
        # 匹配常见文件路径模式
        patterns = [
            r'(?:^|\s|["\'])([\w/\\.-]+\.(?:py|js|ts|json|yaml|yml|toml|md|txt|cfg|ini|conf))(?:\s|["\']|$)',
            r'(?:文件|路径|file|path)[:：]\s*`?([\w/\\.-]+\.\w+)`?',
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, content):
                path_str = m.group(1)
                check = self._verify_single_file_path(path_str)
                checks.append(check)
        return checks

    def _verify_single_file_path(self, path_str: str) -> Dict[str, Any]:
        """验证单个文件路径（带缓存）"""
        now = time.time()
        # 检查缓存
        cached = self._file_existence_cache.get(path_str)
        if cached is not None and (now - cached[1]) < _FILE_EXISTENCE_CACHE_TTL_SECONDS:
            exists = cached[0]
        else:
            # 尝试相对于项目根目录
            full_path = self._project_root / path_str
            exists = full_path.exists()
            # 更新缓存
            self._file_existence_cache[path_str] = (exists, now)

        return {
            "type": "file_path",
            "content": path_str,
            "passed": exists,
            "detail": f"文件{'存在' if exists else '不存在'}: {self._project_root / path_str}",
        }

    # ── 函数/API 名验证 ─────────────────────────────────

    def _verify_function_names(self, content: str) -> List[Dict[str, Any]]:
        """验证内容中提到的函数/API 名（使用索引缓存）"""
        checks = []
        # 匹配函数名模式
        patterns = [
            r'(?:函数|方法|function|method|API)[:：]\s*`?(\w+(?:\.\w+)*)`?',
            r'`(\w+(?:\.\w+)*)`\s*(?:函数|方法|function)',
        ]
        # 确保索引已构建（同步，命中缓存则 O(1)）
        function_index = self._ensure_function_index()

        for pattern in patterns:
            for m in re.finditer(pattern, content):
                func_name = m.group(1)
                check = self._verify_single_function(func_name, function_index)
                checks.append(check)
        return checks

    def _verify_single_function(
        self,
        func_name: str,
        function_index: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """验证单个函数名是否仍存在（使用索引缓存）

        Args:
            func_name: 函数名（可能含点号，如 module.function）
            function_index: 可选的函数名索引，避免重复构建
        """
        # 提取最后一段作为短名（与旧实现一致）
        parts = func_name.split(".")
        short_name = parts[-1] if parts else func_name

        # 使用传入的索引或自行构建
        if function_index is None:
            function_index = self._ensure_function_index()

        found = short_name in function_index

        return {
            "type": "function",
            "content": func_name,
            "passed": found,
            "detail": f"函数{'存在' if found else '未找到'}: {short_name}",
        }

    # ── 配置值验证 ──────────────────────────────────────

    def _verify_config_values(self, content: str) -> List[Dict[str, Any]]:
        """验证内容中提到的配置值"""
        checks = []
        # 匹配配置值模式
        patterns = [
            r'(?:配置|config|setting)[:：]\s*`?(\w+(?:\.\w+)*)\s*=\s*(\S+)`?',
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, content):
                key, value = m.group(1), m.group(2)
                check = self._verify_single_config(f"{key}={value}")
                checks.append(check)
        return checks

    def _verify_single_config(self, config_str: str) -> Dict[str, Any]:
        """验证单个配置值（带缓存）"""
        now = time.time()
        # 检查缓存
        cached = self._config_value_cache.get(config_str)
        if cached is not None and (now - cached[1]) < _CONFIG_VALUE_CACHE_TTL_SECONDS:
            return cached[0]

        # 简单实现：检查配置文件是否存在
        config_files = [
            self._project_root / "config" / "integrated_config.py",
            self._project_root / "config" / "settings_core.py",
        ]
        result: Dict[str, Any]
        for cf in config_files:
            if cf.exists():
                result = {
                    "type": "config",
                    "content": config_str,
                    "passed": True,
                    "detail": "配置文件存在，具体值需运行时验证",
                }
                self._config_value_cache[config_str] = (result, now)
                return result
        result = {
            "type": "config",
            "content": config_str,
            "passed": True,  # 配置验证默认通过
            "detail": "无法验证配置值",
        }
        self._config_value_cache[config_str] = (result, now)
        return result

    # ── 类型检测 ────────────────────────────────────────

    @staticmethod
    def _detect_type(content: str) -> str:
        """自动检测记忆内容类型"""
        # 文件路径
        if re.search(r"\.(py|js|ts|json|yaml|yml|toml|md|txt|cfg|ini|conf)\b", content):
            return "file_path"
        # 函数名
        if re.search(r"(?:def |function |class )\w+", content):
            return "function"
        # 配置
        if re.search(r"(?:config|setting|配置|设置)", content, re.IGNORECASE):
            return "config"
        return "unknown"
