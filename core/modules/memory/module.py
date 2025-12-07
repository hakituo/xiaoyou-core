import os
import json
import asyncio
import aiofiles
from config.integrated_config import get_settings
from core.utils.logger import get_logger

# 配置日志
logger = get_logger("MEMORY_MODULE")

class MemoryModule:
    """
    记忆管理模块
    整合了原来的memory包功能，提供统一的记忆接口
    """
    def __init__(self, config=None):
        self.settings = get_settings()
        self.config = config or {}
        
        # 使用 integrated_config 中的配置，如果未设置则使用默认值
        self.memory_dir = self.settings.memory.history_dir
        if not self.memory_dir:
             self.memory_dir = self.config.get("memory_dir", "history")

        # 确保是绝对路径或者相对于工作目录
        if not os.path.isabs(self.memory_dir):
            self.memory_dir = os.path.join(os.getcwd(), self.memory_dir)
            
        if not os.path.exists(self.memory_dir):
            os.makedirs(self.memory_dir, exist_ok=True)
            
        # 尝试初始化子组件
        try:
            # 修正导入路径: memory/memory_manager.py
            from memory.memory_manager import MemoryManager
            self.manager = MemoryManager()
        except ImportError as e:
            self.manager = None
            logger.warning(f"MemoryManager 导入失败: {e}，部分功能可能不可用")

    async def save_memory(self, key, value):
        """保存记忆 (异步)"""
        try:
            file_path = os.path.join(self.memory_dir, f"{key}.json")
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(value, ensure_ascii=False, indent=2))
            return True
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")
            return False

    async def load_memory(self, key):
        """加载记忆 (异步)"""
        try:
            file_path = os.path.join(self.memory_dir, f"{key}.json")
            if not os.path.exists(file_path):
                return None
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except Exception as e:
            logger.error(f"加载记忆失败: {e}")
            return None
            
    # 同步兼容接口 (如果需要)
    def save_memory_sync(self, key, value):
        """保存记忆 (同步)"""
        try:
            file_path = os.path.join(self.memory_dir, f"{key}.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")
            return False
