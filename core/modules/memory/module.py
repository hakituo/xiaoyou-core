import os
import json
import aiofiles
from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.utils.data_paths import get_user_weighted_history_dir
from core.cache.async_cache_manager import AsyncCacheManager

# 配置日志
logger = get_logger("MEMORY_MODULE")


class MemoryModule:
    """
    记忆管理模块
    整合了原来的memory包功能，提供统一的记忆接口
    **[优化]** 引入 AsyncCacheManager 实现 L1/L2 缓存加速
    """

    def __init__(self, config=None):
        self.settings = get_settings()
        self.config = config or {}
        self.cache_manager = AsyncCacheManager()

        # 使用统一的 history 目录
        self.memory_dir = str(get_user_weighted_history_dir())

        # 尝试初始化子组件
        try:
            # 修正导入路径: memory/weighted_memory_manager.py
            from memory.weighted_memory_manager import WeightedMemoryManager

            # MemoryModule 目前作为通用接口，不直接实例化特定用户的 Manager
            # self.manager = WeightedMemoryManager()
            self.manager_cls = WeightedMemoryManager
            self.manager = None
        except ImportError as e:
            self.manager_cls = None
            self.manager = None
            logger.warning(f"WeightedMemoryManager 导入失败: {e}")

    async def save_memory(self, key, value):
        """保存记忆 (异步)"""
        try:
            # 1. 写入磁盘文件 (持久化)
            os.makedirs(self.memory_dir, exist_ok=True)
            file_path = os.path.join(self.memory_dir, f"{key}.json")
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(value, ensure_ascii=False, indent=2))

            # 2. 更新缓存 (写穿 Write-Through)
            cache_key = f"memory_module:{key}"
            await self.cache_manager.set(cache_key, value, ttl=600)  # 缓存10分钟

            return True
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")
            return False

    async def load_memory(self, key):
        """加载记忆 (异步)"""
        try:
            # 1. 尝试从缓存读取 (Cache Aside)
            cache_key = f"memory_module:{key}"
            cached_val = await self.cache_manager.get(cache_key)
            if cached_val is not None:
                logger.debug(f"Memory Cache Hit: {key}")
                return cached_val

            # 2. 缓存未命中，从磁盘读取
            file_path = os.path.join(self.memory_dir, f"{key}.json")
            if not os.path.exists(file_path):
                return None

            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                data = json.loads(content)

                # 3. 回填缓存
                await self.cache_manager.set(cache_key, data, ttl=600)
                return data
        except Exception as e:
            logger.error(f"加载记忆失败: {e}")
            return None

    # 同步兼容接口 (如果需要)
    def save_memory_sync(self, key, value):
        """保存记忆 (同步)"""
        try:
            os.makedirs(self.memory_dir, exist_ok=True)
            file_path = os.path.join(self.memory_dir, f"{key}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")
            return False
