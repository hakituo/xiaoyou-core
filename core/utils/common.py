#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用工具函数模块
提供各种常用的工具函数
"""

import hashlib
import logging
import os
import shutil
import threading
import time
from typing import Any, Dict, Optional, Callable, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar('T')
R = TypeVar('R')


def ensure_directory(directory_path: str) -> bool:
    """确保目录存在，如果不存在则创建
    
    Args:
        directory_path: 目录路径
        
    Returns:
        是否成功创建或目录已存在
    """
    try:
        os.makedirs(directory_path, exist_ok=True)
        logger.debug(f"确保目录存在: {directory_path}")
        return True
    except Exception as e:
        logger.error(f"创建目录失败: {directory_path}, 错误: {e}")
        return False


def safe_file_operation(func: Callable[..., R], *args, **kwargs) -> Optional[R]:
    """安全的文件操作装饰器
    
    Args:
        func: 要执行的文件操作函数
        *args: 位置参数
        **kwargs: 关键字参数
        
    Returns:
        函数执行结果，如果出错则返回None
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"文件操作失败: {e}")
        return None


def generate_hash(data: Union[str, bytes], algorithm: str = "md5") -> str:
    """生成数据的哈希值
    
    Args:
        data: 要哈希的数据
        algorithm: 哈希算法，支持md5, sha1, sha256等
        
    Returns:
        哈希值的十六进制字符串
    """
    try:
        if isinstance(data, str):
            data = data.encode("utf-8")
        
        if algorithm.lower() == "md5":
            hash_obj = hashlib.md5()
        elif algorithm.lower() == "sha1":
            hash_obj = hashlib.sha1()
        elif algorithm.lower() == "sha256":
            hash_obj = hashlib.sha256()
        else:
            logger.warning(f"不支持的哈希算法: {algorithm}，使用md5替代")
            hash_obj = hashlib.md5()
        
        hash_obj.update(data)
        return hash_obj.hexdigest()
    except Exception as e:
        logger.error(f"生成哈希值失败: {e}")
        return ""


def run_in_thread(func: Callable[..., R], *args, **kwargs) -> threading.Thread:
    """在新线程中运行函数
    
    Args:
        func: 要在新线程中运行的函数
        *args: 位置参数
        **kwargs: 关键字参数
        
    Returns:
        创建的线程对象
    """
    def thread_func():
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"线程执行失败: {e}")
    
    thread = threading.Thread(target=thread_func, daemon=True)
    thread.start()
    return thread


def merge_dicts(dict1: Dict[Any, Any], dict2: Dict[Any, Any], 
                deep: bool = False) -> Dict[Any, Any]:
    """合并两个字典
    
    Args:
        dict1: 第一个字典
        dict2: 第二个字典
        deep: 是否深度合并
        
    Returns:
        合并后的字典
    """
    result = dict1.copy()
    
    if deep:
        # 深度合并
        for key, value in dict2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_dicts(result[key], value, deep=True)
            else:
                result[key] = value
    else:
        # 浅度合并
        result.update(dict2)
    
    return result


def safe_remove(path: str) -> bool:
    """安全删除文件或目录
    
    Args:
        path: 要删除的文件或目录路径
        
    Returns:
        是否删除成功
    """
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.debug(f"文件已删除: {path}")
        elif os.path.isdir(path):
            shutil.rmtree(path)
            logger.debug(f"目录已删除: {path}")
        else:
            logger.warning(f"路径不存在: {path}")
        return True
    except Exception as e:
        logger.error(f"删除失败: {path}, 错误: {e}")
        return False


def get_file_size(file_path: str) -> Optional[int]:
    """获取文件大小
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件大小（字节），如果出错则返回None
    """
    try:
        return os.path.getsize(file_path)
    except Exception as e:
        logger.error(f"获取文件大小失败: {file_path}, 错误: {e}")
        return None


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读的字符串
    
    Args:
        size_bytes: 文件大小（字节）
        
    Returns:
        格式化后的文件大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def retry(func: Callable[..., R], max_retries: int = 3, 
          delay: float = 1.0, exceptions: tuple = (Exception,)) -> Optional[R]:
    """重试装饰器
    
    Args:
        func: 要重试的函数
        max_retries: 最大重试次数
        delay: 重试间隔（秒）
        exceptions: 要捕获的异常类型
        
    Returns:
        函数执行结果，如果所有重试都失败则返回None
    """
    for attempt in range(max_retries):
        try:
            return func()
        except exceptions as e:
            logger.warning(f"尝试 {attempt + 1}/{max_retries} 失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(delay)
    
    logger.error(f"所有 {max_retries} 次尝试都失败了")
    return None


def timeit(func: Callable[..., R]) -> Callable[..., R]:
    """计时装饰器
    
    Args:
        func: 要计时的函数
        
    Returns:
        包装后的函数
    """
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.debug(f"函数 {func.__name__} 执行时间: {end_time - start_time:.4f} 秒")
        return result
    
    return wrapper


def singleton(cls):
    """单例模式装饰器
    
    Args:
        cls: 要转换为单例的类
        
    Returns:
        单例类
    """
    instances = {}
    lock = threading.RLock()
    
    def get_instance(*args, **kwargs):
        with lock:
            if cls not in instances:
                instances[cls] = cls(*args, **kwargs)
            return instances[cls]
    
    return get_instance


def validate_file_path(file_path: str, must_exist: bool = False) -> bool:
    """验证文件路径是否有效
    
    Args:
        file_path: 文件路径
        must_exist: 是否必须存在
        
    Returns:
        路径是否有效
    """
    try:
        # 检查路径是否有效
        dir_path = os.path.dirname(file_path)
        if dir_path and not os.path.exists(dir_path):
            return False
        
        # 检查文件是否存在（如果要求）
        if must_exist and not os.path.isfile(file_path):
            return False
        
        return True
    except Exception as e:
        logger.error(f"验证文件路径失败: {file_path}, 错误: {e}")
        return False


def load_json_file(file_path: str) -> Optional[Dict[Any, Any]]:
    """加载JSON文件
    
    Args:
        file_path: JSON文件路径
        
    Returns:
        JSON数据，如果出错则返回None
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载JSON文件失败: {file_path}, 错误: {e}")
        return None


def save_json_file(file_path: str, data: Dict[Any, Any], 
                   indent: Optional[int] = 2) -> bool:
    """保存数据到JSON文件
    
    Args:
        file_path: JSON文件路径
        data: 要保存的数据
        indent: 缩进空格数
        
    Returns:
        是否保存成功
    """
    try:
        # 确保目录存在
        ensure_directory(os.path.dirname(file_path))
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        
        logger.debug(f"JSON文件已保存: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存JSON文件失败: {file_path}, 错误: {e}")
        return False

# 添加json导入
import json