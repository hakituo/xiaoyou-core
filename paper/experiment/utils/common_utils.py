#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用工具模块
提供实验中常用的工具函数，包括文件操作、数据处理、图像操作等
"""

import os
import json
import shutil
import hashlib
import tempfile
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import threading

from .config_manager import get_config


class FileUtils:
    """文件操作工具类"""
    
    @staticmethod
    def ensure_directory(directory: str) -> bool:
        """确保目录存在"""
        try:
            os.makedirs(directory, exist_ok=True)
            return True
        except Exception as e:
            config = get_config()
            config.log_error(f"创建目录失败: {directory}", e)
            return False
    
    @staticmethod
    def safe_file_write(file_path: str, content: str, encoding: str = 'utf-8') -> bool:
        """安全写入文件（使用临时文件原子性替换）"""
        config = get_config()
        directory = os.path.dirname(file_path)
        
        # 确保目录存在
        if directory and not FileUtils.ensure_directory(directory):
            return False
        
        try:
            # 使用临时文件进行原子性写入
            temp_dir = directory if directory else '.'
            with tempfile.NamedTemporaryFile('w', delete=False, 
                                           dir=temp_dir, encoding=encoding) as temp_file:
                temp_file.write(content)
                temp_path = temp_file.name
            
            # 原子性替换
            os.replace(temp_path, file_path)
            return True
        except Exception as e:
            config.log_error(f"写入文件失败: {file_path}", e)
            # 清理临时文件
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return False
    
    @staticmethod
    def safe_json_dump(file_path: str, data: Any, indent: int = 2) -> bool:
        """安全保存JSON数据"""
        try:
            content = json.dumps(data, ensure_ascii=False, indent=indent)
            return FileUtils.safe_file_write(file_path, content)
        except Exception as e:
            config = get_config()
            config.log_error(f"保存JSON失败: {file_path}", e)
            return False
    
    @staticmethod
    def safe_json_load(file_path: str) -> Optional[Dict[str, Any]]:
        """安全加载JSON数据"""
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            config = get_config()
            config.log_error(f"加载JSON失败: {file_path}", e)
            return None
    
    @staticmethod
    def calculate_file_hash(file_path: str, algorithm: str = 'md5') -> Optional[str]:
        """计算文件哈希值"""
        if not os.path.exists(file_path):
            return None
        
        try:
            hash_obj = hashlib.new(algorithm)
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception as e:
            config = get_config()
            config.log_error(f"计算文件哈希失败: {file_path}", e)
            return None
    
    @staticmethod
    def delete_directory(directory: str, force: bool = False) -> bool:
        """删除目录"""
        if not os.path.exists(directory):
            return True
        
        if not force and os.listdir(directory):
            config = get_config()
            config.log_warning(f"目录不为空，不会删除: {directory}")
            return False
        
        try:
            shutil.rmtree(directory)
            return True
        except Exception as e:
            config = get_config()
            config.log_error(f"删除目录失败: {directory}", e)
            return False
    
    @staticmethod
    def list_files(directory: str, pattern: Optional[str] = None, 
                  recursive: bool = False) -> List[str]:
        """列出目录中的文件"""
        import glob
        
        if not os.path.exists(directory):
            return []
        
        search_pattern = os.path.join(directory, '**/*' if recursive else '*')
        if pattern:
            search_pattern = os.path.join(directory, f'**/{pattern}' if recursive else pattern)
        
        try:
            files = glob.glob(search_pattern, recursive=recursive)
            return [f for f in files if os.path.isfile(f)]
        except Exception as e:
            config = get_config()
            config.log_error(f"列出文件失败: {directory}", e)
            return []


class DataUtils:
    """数据处理工具类"""
    
    @staticmethod
    def format_bytes(size: Union[int, float]) -> str:
        """格式化字节大小"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    
    @staticmethod
    def format_duration(seconds: Union[int, float]) -> str:
        """格式化时长"""
        if seconds < 0.001:
            return f"{seconds * 1000000:.0f} μs"
        elif seconds < 1:
            return f"{seconds * 1000:.2f} ms"
        elif seconds < 60:
            return f"{seconds:.2f} s"
        elif seconds < 3600:
            minutes, seconds = divmod(seconds, 60)
            return f"{int(minutes)} m {seconds:.0f} s"
        else:
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{int(hours)} h {int(minutes)} m {seconds:.0f} s"
    
    @staticmethod
    def calculate_statistics(data: List[float]) -> Dict[str, float]:
        """计算统计数据"""
        if not data:
            return {
                'count': 0,
                'mean': 0.0,
                'median': 0.0,
                'min': 0.0,
                'max': 0.0,
                'std': 0.0,
            }
        
        import statistics
        
        return {
            'count': len(data),
            'mean': statistics.mean(data) if data else 0.0,
            'median': statistics.median(data) if data else 0.0,
            'min': min(data),
            'max': max(data),
            'std': statistics.stdev(data) if len(data) > 1 else 0.0,
        }
    
    @staticmethod
    def merge_dicts(dict1: Dict[Any, Any], dict2: Dict[Any, Any], 
                   deep: bool = False) -> Dict[Any, Any]:
        """合并字典"""
        result = dict1.copy()
        
        if not deep:
            result.update(dict2)
            return result
        
        for key, value in dict2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = DataUtils.merge_dicts(result[key], value, deep=True)
            else:
                result[key] = value
        
        return result
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """清理文件名，移除或替换非法字符"""
        import re
        # 移除或替换非法字符
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # 移除控制字符
        filename = ''.join(char for char in filename if ord(char) > 31)
        # 截断过长的文件名（Windows限制为260字符路径总长度）
        max_length = 200  # 留出一些空间给路径
        if len(filename) > max_length:
            name, ext = os.path.splitext(filename)
            filename = name[:max_length - len(ext)] + ext
        return filename


class ThreadSafeCounter:
    """线程安全的计数器"""
    
    def __init__(self, initial_value: int = 0):
        self._value = initial_value
        self._lock = threading.Lock()
    
    def increment(self, step: int = 1) -> int:
        """增加计数并返回新值"""
        with self._lock:
            self._value += step
            return self._value
    
    def decrement(self, step: int = 1) -> int:
        """减少计数并返回新值"""
        with self._lock:
            self._value -= step
            return self._value
    
    def get(self) -> int:
        """获取当前值"""
        with self._lock:
            return self._value
    
    def set(self, value: int) -> None:
        """设置计数器值"""
        with self._lock:
            self._value = value


class ThreadSafeDict(dict):
    """线程安全的字典"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.RLock()
    
    def __getitem__(self, key):
        with self._lock:
            return super().__getitem__(key)
    
    def __setitem__(self, key, value):
        with self._lock:
            return super().__setitem__(key, value)
    
    def __delitem__(self, key):
        with self._lock:
            return super().__delitem__(key)
    
    def get(self, key, default=None):
        with self._lock:
            return super().get(key, default)
    
    def update(self, *args, **kwargs):
        with self._lock:
            return super().update(*args, **kwargs)
    
    def clear(self):
        with self._lock:
            return super().clear()
    
    def copy(self):
        with self._lock:
            return dict(super().items())


class EnhancedImageCache:
    """增强型图片缓存管理器"""
    
    def __init__(self, max_size: int = 100, ttl: int = 300):
        """
        初始化图片缓存管理器
        
        Args:
            max_size: 最大缓存图片数量
            ttl: 缓存项过期时间（秒）
        """
        from PIL import Image as PILImage
        
        self._PILImage = PILImage
        self._cache = ThreadSafeDict()
        self._max_size = max_size
        self._ttl = ttl
        self._stats = ThreadSafeDict({
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_size': 0,
            'access_count': 0
        })
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # 清理间隔（秒）
        from .config_manager import get_config
        self._config = get_config()
    
    def _cleanup_expired(self):
        """清理过期的缓存项"""
        current_time = time.time()
        if current_time - self._last_cleanup < self._cleanup_interval:
            return
        
        expired_keys = []
        for key, (_, timestamp, _) in self._cache.items():
            if current_time - timestamp > self._ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            self._remove_key(key)
        
        self._last_cleanup = current_time
    
    def _remove_key(self, key):
        """移除指定的缓存项"""
        if key in self._cache:
            _, _, size = self._cache.pop(key)
            self._stats['total_size'] -= size
            self._stats['evictions'] += 1
    
    def _evict_if_needed(self):
        """当缓存达到最大容量时，驱逐最旧的项"""
        if len(self._cache) >= self._max_size:
            # 按时间戳排序，移除最旧的项
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k][1]
            )
            self._remove_key(oldest_key)
    
    def get_image(self, image_path: str) -> Optional[Any]:
        """
        从缓存获取图片，如果不存在则加载并缓存
        
        Args:
            image_path: 图片文件路径
            
        Returns:
            PIL.Image 对象或 None（如果加载失败）
        """
        self._cleanup_expired()
        self._stats['access_count'] += 1
        
        # 使用绝对路径作为缓存键，确保唯一性
        abs_path = os.path.abspath(image_path)
        
        # 检查缓存中是否存在
        if abs_path in self._cache:
            image, _, _ = self._cache[abs_path]
            # 更新时间戳
            self._cache[abs_path] = (image, time.time(), image.size[0] * image.size[1])
            self._stats['hits'] += 1
            return image
        
        # 缓存未命中，加载图片
        self._stats['misses'] += 1
        
        try:
            # 验证文件存在
            if not os.path.exists(abs_path):
                self._config.log_warning(f"图片文件不存在: {abs_path}")
                return None
            
            # 加载图片
            image = self._PILImage.open(abs_path)
            image.load()  # 确保图片完全加载到内存
            
            # 计算图片大小（粗略估计）
            image_size = image.size[0] * image.size[1]  # 像素数作为大小估计
            
            # 驱逐旧项（如果需要）
            self._evict_if_needed()
            
            # 缓存图片
            self._cache[abs_path] = (image, time.time(), image_size)
            self._stats['total_size'] += image_size
            
            return image
        except Exception as e:
            self._config.log_error(f"加载图片失败 {abs_path}", e)
            return None
    
    def get_stats(self) -> Dict[str, float]:
        """获取缓存统计信息"""
        # 计算命中率
        total = self._stats['hits'] + self._stats['misses']
        hit_rate = (self._stats['hits'] / total * 100) if total > 0 else 0
        
        return {
            'current_size': len(self._cache),
            'max_size': self._max_size,
            'hit_rate': hit_rate,
            'hits': self._stats['hits'],
            'misses': self._stats['misses'],
            'evictions': self._stats['evictions'],
            'total_size': self._stats['total_size'],
            'access_count': self._stats['access_count']
        }
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        self._stats['total_size'] = 0
        self._stats['evictions'] += len(self._cache)


# 添加必要的导入
import time

# 创建全局缓存实例
global_image_cache = EnhancedImageCache(max_size=50, ttl=600)


def get_image_cache() -> EnhancedImageCache:
    """获取全局图片缓存实例"""
    return global_image_cache


def format_time(timestamp: float) -> str:
    """格式化时间戳"""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')


def parse_time(time_str: str) -> float:
    """解析时间字符串为时间戳"""
    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        return dt.timestamp()
    except Exception as e:
        config = get_config()
        config.log_error(f"解析时间失败: {time_str}", e)
        return 0.0


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """安全除法"""
    if denominator == 0:
        return default
    return numerator / denominator