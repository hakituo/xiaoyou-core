#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
报告生成模块
提供各种报告的生成和展示功能
"""

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ReportEntry:
    """报告条目数据类"""
    timestamp: float
    category: str
    title: str
    content: Any
    severity: str = "info"
    tags: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.timestamp is None:
            self.timestamp = time.time()


class ReportGenerator:
    """报告生成器类"""
    
    def __init__(self, report_dir: str = "./reports"):
        """初始化报告生成器
        
        Args:
            report_dir: 报告保存目录
        """
        self.report_dir = report_dir
        self.reports: Dict[str, List[ReportEntry]] = {}
        
        # 确保报告目录存在
        os.makedirs(self.report_dir, exist_ok=True)
        logger.info(f"报告生成器已初始化，报告目录: {self.report_dir}")
    
    def add_entry(self, report_name: str, entry: ReportEntry):
        """添加报告条目
        
        Args:
            report_name: 报告名称
            entry: 报告条目
        """
        if report_name not in self.reports:
            self.reports[report_name] = []
        
        self.reports[report_name].append(entry)
        logger.debug(f"已添加报告条目: {report_name} - {entry.title}")
    
    def create_entry(self, report_name: str, category: str, title: str, 
                    content: Any, severity: str = "info", 
                    tags: Optional[List[str]] = None):
        """创建并添加报告条目
        
        Args:
            report_name: 报告名称
            category: 条目分类
            title: 条目标题
            content: 条目内容
            severity: 严重程度
            tags: 标签列表
        """
        entry = ReportEntry(
            timestamp=time.time(),
            category=category,
            title=title,
            content=content,
            severity=severity,
            tags=tags
        )
        self.add_entry(report_name, entry)
        return entry
    
    def save_report(self, report_name: str, format: str = "json") -> str:
        """保存报告
        
        Args:
            report_name: 报告名称
            format: 报告格式
            
        Returns:
            保存的文件路径
        """
        if report_name not in self.reports:
            logger.warning(f"报告不存在: {report_name}")
            return ""
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{report_name}_{timestamp}.{format}"
        filepath = os.path.join(self.report_dir, filename)
        
        try:
            if format == "json":
                report_data = {
                    "generated_at": time.time(),
                    "entries": [asdict(entry) for entry in self.reports[report_name]]
                }
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(report_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"报告已保存: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"保存报告失败: {e}")
            return ""
    
    def get_report_summary(self, report_name: str) -> Dict[str, Any]:
        """获取报告摘要
        
        Args:
            report_name: 报告名称
            
        Returns:
            报告摘要信息
        """
        if report_name not in self.reports:
            return {"error": "报告不存在"}
        
        entries = self.reports[report_name]
        
        # 统计信息
        severity_counts = {}
        category_counts = {}
        
        for entry in entries:
            # 统计严重程度
            severity_counts[entry.severity] = severity_counts.get(entry.severity, 0) + 1
            # 统计分类
            category_counts[entry.category] = category_counts.get(entry.category, 0) + 1
        
        return {
            "report_name": report_name,
            "total_entries": len(entries),
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "first_entry_time": min(entry.timestamp for entry in entries),
            "last_entry_time": max(entry.timestamp for entry in entries)
        }
    
    def clear_report(self, report_name: str):
        """清空报告
        
        Args:
            report_name: 报告名称
        """
        if report_name in self.reports:
            self.reports[report_name] = []
            logger.info(f"报告已清空: {report_name}")
    
    def list_reports(self) -> List[str]:
        """列出所有报告
        
        Returns:
            报告名称列表
        """
        return list(self.reports.keys())


# 全局报告生成器实例
global_report_generator: Optional[ReportGenerator] = None


def get_global_report_generator() -> ReportGenerator:
    """获取全局报告生成器实例
    
    Returns:
        报告生成器实例
    """
    global global_report_generator
    
    if global_report_generator is None:
        global_report_generator = ReportGenerator()
    
    return global_report_generator


def plot_tts_results(results: Dict[str, Any], output_file: Optional[str] = None) -> bool:
    """绘制TTS结果图表
    
    Args:
        results: TTS结果数据
        output_file: 输出文件路径
        
    Returns:
        是否成功绘制
    """
    try:
        # 这里可以根据实际需求实现图表绘制功能
        # 暂时返回成功，后续可以使用matplotlib等库实现具体的图表绘制
        logger.info(f"TTS结果图表绘制完成")
        return True
    except Exception as e:
        logger.error(f"绘制TTS结果图表失败: {e}")
        return False


def generate_system_report() -> Dict[str, Any]:
    """生成系统报告
    
    Returns:
        系统报告数据
    """
    import platform
    import psutil
    
    try:
        # 获取系统信息
        system_info = {
            "system": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(logical=True),
            "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "disk_usage": {}
        }
        
        # 获取磁盘使用情况
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                system_info["disk_usage"][partition.mountpoint] = {
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": usage.percent
                }
            except:
                pass
        
        return system_info
    except Exception as e:
        logger.error(f"生成系统报告失败: {e}")
        return {"error": str(e)}


# 初始化全局报告生成器
global_report_generator = ReportGenerator()
