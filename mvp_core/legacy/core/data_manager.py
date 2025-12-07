#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据管理模块
负责配置持久化、模型文件管理和日志管理
"""
import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DataManager:
    """
    数据管理器
    负责数据层的各种操作
    """
    
    def __init__(self, data_dir: str):
        """
        初始化数据管理器
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir
        self.config_file = os.path.join(data_dir, "config.json")
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        logger.info(f"DataManager initialized with data_dir: {data_dir}")
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """
        保存配置到文件
        
        Args:
            config: 配置字典
            
        Returns:
            是否保存成功
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"Config saved to {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def load_config(self) -> Optional[Dict[str, Any]]:
        """
        从文件加载配置
        
        Returns:
            配置字典或None
        """
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config: Dict[str, Any] = json.load(f)
                logger.info(f"Config loaded from {self.config_file}")
                return config
            logger.info(f"Config file not found: {self.config_file}")
            return None
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return None
    
    def get_data_path(self, filename: str) -> str:
        """
        获取数据文件的完整路径
        
        Args:
            filename: 文件名
            
        Returns:
            完整路径
        """
        return os.path.join(self.data_dir, filename)
    
    def list_data_files(self, extension: Optional[str] = None) -> list:
        """
        列出数据目录中的文件
        
        Args:
            extension: 文件扩展名，如".json"，None表示所有文件
            
        Returns:
            文件列表
        """
        files = []
        try:
            for file in os.listdir(self.data_dir):
                file_path = os.path.join(self.data_dir, file)
                if os.path.isfile(file_path):
                    if extension is None or file.endswith(extension):
                        files.append({
                            "name": file,
                            "path": file_path,
                            "size": os.path.getsize(file_path),
                            "modified_time": os.path.getmtime(file_path)
                        })
            return files
        except Exception as e:
            logger.error(f"Failed to list data files: {e}")
            return []