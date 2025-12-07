#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
核心配置管理模块
提供统一的配置接口和类型验证
"""
import os
from typing import Optional, Dict, Any, List
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import logging
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('config')
class ServerSettings(BaseSettings):
    """服务器配置"""
    port: int = Field(default=8000, description="服务器端口")
    host: str = Field(default="0.0.0.0", description="服务器主机")
    max_connections: int = Field(default=100, description="最大连接数")
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_SERVER_",
        extra="allow"
    )
class ModelSettings(BaseSettings):
    """模型配置"""
    model_dir: str = Field(default="models", description="模型目录")
    cache_dir: str = Field(default="cache", description="缓存目录")
    device: str = Field(default="cuda", description="设备类型(cpu/cuda)")
    max_memory: Optional[int] = Field(default=None, description="最大内存使用(MB)")
    name: str = Field(default="default_model", description="模型名称")
    text_path: Optional[str] = Field(default=None, description="文本模型路径")
    vision_path: Optional[str] = Field(default=None, description="视觉模型路径")
    image_gen_path: Optional[str] = Field(default=None, description="图像生成模型路径")
    whisper_path: Optional[str] = Field(default=None, description="Whisper模型路径")
    gpu_enabled: bool = Field(default=True, description="是否启用GPU")
    memory_limit: int = Field(default=16, description="内存限制(GB)")
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MODEL_",
        extra="allow"
    )
class LoggingSettings(BaseSettings):
    """日志配置"""
    level: str = Field(default="INFO", description="日志级别")
    log_dir: str = Field(default="logs", description="日志目录")
    log_file: str = Field(default="xiaoyou.log", description="日志文件")
    rotation_size: str = Field(default="50MB", description="日志轮转大小")
    rotation_backup_count: int = Field(default=5, description="日志备份数量")
    format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s", description="日志格式")
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_LOGGING_",
        extra="allow"
    )
class MemorySettings(BaseSettings):
    """内存管理配置"""
    max_history_length: int = Field(default=100, description="最大历史记录长度")
    auto_save_interval: int = Field(default=300, description="自动保存间隔(秒)")
    history_dir: str = Field(default="history", description="历史记录目录")
    enabled: bool = Field(default=True, description="是否启用内存管理")
    auto_save: bool = Field(default=True, description="是否自动保存")
    max_size: int = Field(default=1000, description="最大内存大小")
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MEMORY_",
        extra="allow"
    )
class RedisSettings(BaseSettings):
    """Redis配置"""
    enabled: bool = Field(default=False, description="是否启用Redis")
    host: str = Field(default="localhost", description="Redis主机")
    port: int = Field(default=6379, description="Redis端口")
    db: int = Field(default=0, description="Redis数据库")
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_REDIS_",
        extra="allow"
    )
class VirtualEnvSettings(BaseSettings):
    """虚拟环境配置"""
    base_path: str = Field(default="./venv_base", description="基础虚拟环境路径")
    tts_path: str = Field(default="./venv_tts", description="TTS虚拟环境路径")
    image_path: str = Field(default="./venv_img", description="图像虚拟环境路径")
    llm_path: str = Field(default="./venv_llm", description="LLM虚拟环境路径")
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_VENV_",
        extra="allow"
    )
class ImageSettings(BaseSettings):
    """图像生成配置"""
    width: int = Field(default=512, description="默认图像宽度")
    height: int = Field(default=512, description="默认图像高度")
    max_width: int = Field(default=1024, description="最大图像宽度")
    max_height: int = Field(default=1024, description="最大图像高度")
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_IMAGE_",
        extra="allow"
    )
class AppSettings(BaseSettings):
    """应用程序主配置"""
    # 应用基本信息
    app_name: str = Field(default="xiaoyou-core", description="应用名称")
    app_version: str = Field(default="0.1.0", description="应用版本")
    debug: bool = Field(default=False, description="调试模式")
    # 子配置
    server: ServerSettings = ServerSettings()
    model: ModelSettings = ModelSettings()
    logging: LoggingSettings = LoggingSettings()
    memory: MemorySettings = MemorySettings()
    redis: RedisSettings = RedisSettings()
    venv: VirtualEnvSettings = VirtualEnvSettings()
    image: ImageSettings = ImageSettings()
    # 工作目录
    project_root: Path = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 确保必要的目录存在
        self._ensure_directories()
    def _ensure_directories(self):
        """确保所有必要的目录存在"""
        directories = [
            self.model.model_dir,
            self.model.cache_dir,
            self.logging.log_dir,
            self.memory.history_dir
        ]
        for directory in directories:
            path = self.project_root / directory
            path.mkdir(parents=True, exist_ok=True)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )
# 创建全局配置实例
settings = AppSettings()
# 环境配置类
class EnvironmentManager:
    """虚拟环境管理器"""
    def __init__(self):
        self.project_root = settings.project_root
        self.venv_config = {
            'base': {
                'path': settings.venv.base_path,
                'packages': [
                    'asyncio', 'websockets', 'psutil', 'requests', 
                    'pydantic', 'pydantic-settings', 'python-dotenv'
                ]
            },
            'models': {
                'path': str(self.project_root / 'venv_models'),
                'packages': ['torch', 'transformers', 'accelerate']
            },
            'tts': {
                'path': settings.venv.tts_path,
                'packages': ['coqui-tts', 'pyaudio', 'soundfile']
            },
            'image': {
                'path': settings.venv.image_path,
                'packages': ['pillow', 'numpy', 'opencv-python']
            },
            'llm': {
                'path': settings.venv.llm_path,
                'packages': ['transformers', 'accelerate', 'bitsandbytes']
            }
        }
# 创建全局环境管理器实例
env_manager = EnvironmentManager()
__all__ = ['settings', 'env_manager', 'AppSettings', 'ServerSettings', 'ModelSettings', 'LoggingSettings', 'MemorySettings', 'RedisSettings', 'VirtualEnvSettings', 'ImageSettings', 'get_settings']