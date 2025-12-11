#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公共工具函数模块
包含字符串处理、文件操作、随机数生成等通用功能
"""

import os
import random
import string
from typing import List, Dict, Any, Tuple


def compare_strings(source: str, target: str) -> Tuple[int, List[Tuple[int, str, str]]]:
    """
    逐字对比两个字符串，返回错误数量和错误位置详情
    
    Args:
        source: 源字符串（正确答案）
        target: 目标字符串（用户输入）
    
    Returns:
        Tuple[int, List[Tuple[int, str, str]]]: (错误数量, 错误详情列表)
        错误详情格式: (位置索引, 正确字符, 用户输入字符)
    """
    errors = []
    max_len = max(len(source), len(target))
    
    for i in range(max_len):
        if i >= len(source):
            errors.append((i, "", target[i]))
        elif i >= len(target):
            errors.append((i, source[i], ""))
        elif source[i] != target[i]:
            errors.append((i, source[i], target[i]))
    
    return len(errors), errors


def highlight_errors(source: str, target: str) -> str:
    """
    高亮显示错误字符
    
    Args:
        source: 源字符串（正确答案）
        target: 目标字符串（用户输入）
    
    Returns:
        str: 高亮后的字符串，错误字符用【】包裹
    """
    _, errors = compare_strings(source, target)
    result = list(target)
    
    # 从后往前插入高亮标记，避免索引偏移
    for i, correct_char, user_char in sorted(errors, reverse=True):
        if i < len(result):
            result[i] = f"【{result[i]}】"
        else:
            result.append(f"【{user_char}】")
    
    return "".join(result)


def get_file_extension(file_path: str) -> str:
    """
    获取文件扩展名
    
    Args:
        file_path: 文件路径
    
    Returns:
        str: 文件扩展名（小写）
    """
    return os.path.splitext(file_path)[1].lower()


def check_file_exists(file_path: str) -> bool:
    """
    检查文件是否存在
    
    Args:
        file_path: 文件路径
    
    Returns:
        bool: 文件是否存在
    """
    return os.path.exists(file_path) and os.path.isfile(file_path)


def check_dir_exists(dir_path: str) -> bool:
    """
    检查目录是否存在
    
    Args:
        dir_path: 目录路径
    
    Returns:
        bool: 目录是否存在
    """
    return os.path.exists(dir_path) and os.path.isdir(dir_path)


def ensure_dir_exists(dir_path: str) -> None:
    """
    确保目录存在，不存在则创建
    
    Args:
        dir_path: 目录路径
    """
    if not check_dir_exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)


def random_sample(items: List[Any], sample_size: int, avoid_duplicates: bool = True) -> List[Any]:
    """
    随机抽取样本
    
    Args:
        items: 待抽取的列表
        sample_size: 抽取数量
        avoid_duplicates: 是否避免重复
    
    Returns:
        List[Any]: 抽取的样本列表
    """
    if not avoid_duplicates:
        return random.choices(items, k=sample_size)
    
    if sample_size > len(items):
        sample_size = len(items)
    
    return random.sample(items, sample_size)


def generate_unique_id(length: int = 8) -> str:
    """
    生成唯一ID
    
    Args:
        length: ID长度
    
    Returns:
        str: 唯一ID
    """
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


def sort_dict_by_value(d: Dict[Any, Any], reverse: bool = False) -> List[Tuple[Any, Any]]:
    """
    按值排序字典
    
    Args:
        d: 待排序字典
        reverse: 是否降序
    
    Returns:
        List[Tuple[Any, Any]]: 排序后的键值对列表
    """
    return sorted(d.items(), key=lambda x: x[1], reverse=reverse)


def filter_list_by_keywords(items: List[Dict[str, Any]], keywords: List[str], fields: List[str]) -> List[Dict[str, Any]]:
    """
    根据关键词过滤列表
    
    Args:
        items: 待过滤列表
        keywords: 关键词列表
        fields: 要匹配的字段列表
    
    Returns:
        List[Dict[str, Any]]: 过滤后的列表
    """
    result = []
    
    for item in items:
        match = True
        for keyword in keywords:
            keyword_match = False
            for field in fields:
                if keyword.lower() in str(item.get(field, "")).lower():
                    keyword_match = True
                    break
            if not keyword_match:
                match = False
                break
        if match:
            result.append(item)
    
    return result


def format_text(text: str, max_line_length: int = 80) -> str:
    """
    格式化文本，限制每行长度
    
    Args:
        text: 待格式化文本
        max_line_length: 每行最大长度
    
    Returns:
        str: 格式化后的文本
    """
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + len(current_line) <= max_line_length:
            current_line.append(word)
            current_length += len(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_length = len(word)
    
    if current_line:
        lines.append(" ".join(current_line))
    
    return "\n".join(lines)


def count_characters(text: str) -> Dict[str, int]:
    """
    统计字符出现次数
    
    Args:
        text: 待统计文本
    
    Returns:
        Dict[str, int]: 字符出现次数字典
    """
    char_count = {}
    for char in text:
        if char in char_count:
            char_count[char] += 1
        else:
            char_count[char] = 1
    
    return char_count


def remove_duplicates(items: List[Any]) -> List[Any]:
    """
    去除列表中的重复项，保持原有顺序
    
    Args:
        items: 待处理列表
    
    Returns:
        List[Any]: 去重后的列表
    """
    seen = set()
    result = []
    
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    
    return result


def normalize_string(s: str) -> str:
    """
    规范化字符串，去除前后空格和特殊字符
    
    Args:
        s: 待规范化字符串
    
    Returns:
        str: 规范化后的字符串
    """
    return s.strip().replace("\r", "").replace("\n", " ")


def split_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    将列表分割成指定大小的块
    
    Args:
        items: 待分割列表
        chunk_size: 每块大小
    
    Returns:
        List[List[Any]]: 分割后的列表
    """
    return [items[i:i+chunk_size] for i in range(0, len(items), chunk_size)]


def safe_float_convert(s: str) -> float:
    """
    安全转换为浮点数
    
    Args:
        s: 待转换字符串
    
    Returns:
        float: 转换后的浮点数，转换失败返回0.0
    """
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def safe_int_convert(s: str) -> int:
    """
    安全转换为整数
    
    Args:
        s: 待转换字符串
    
    Returns:
        int: 转换后的整数，转换失败返回0
    """
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0
