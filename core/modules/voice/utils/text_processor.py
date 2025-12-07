# -*- coding: utf-8 -*-
"""
文本处理器，用于处理TTS引擎的文本输入
"""

import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class TextProcessor:
    """
    文本处理器，提供文本规范化、分段等功能
    """
    
    # 中文字符匹配正则表达式
    CHINESE_CHAR_PATTERN = re.compile(r'[\u4e00-\u9fa5]')
    
    # 标点符号优先级列表（用于分段）
    PUNCTUATION_PRIORITY = {
        '，': 1, ',': 1,  # 逗号
        '。': 2, '.': 2, '！': 2, '!': 2, '？': 2, '?': 2,  # 句点
        '；': 3, ';': 3,  # 分号
        '：': 4, ':': 4,  # 冒号
        '（': 5, '(': 5, '）': 5, ')': 5,  # 括号
        '【': 5, '[': 5, '】': 5, ']': 5,  # 方括号
        '\n': 6,  # 换行符
    }
    
    # 配对标点符号
    MATCHING_PUNCTUATION = {
        '(': ')',
        '[': ']',
        '{': '}',
        '（': '）',
        '【': '】',
        '《': '》',
    }
    
    def __init__(self, max_segment_length: int = 500, overlap: int = 0):
        """
        初始化文本处理器
        
        Args:
            max_segment_length: 最大分段长度
            overlap: 分段重叠字符数
        """
        self.max_segment_length = max_segment_length
        self.overlap = overlap
    
    def normalize_text(self, text: str) -> str:
        """
        规范化文本，处理特殊字符和格式
        
        Args:
            text: 原始文本
            
        Returns:
            规范化后的文本
        """
        # 去除多余空格
        text = re.sub(r'\s+', ' ', text)
        
        # 去除首尾空格
        text = text.strip()
        
        # 替换全角空格为半角空格
        text = text.replace('　', ' ')
        
        # 处理重复标点
        # TODO: 根据需要添加更多规范化规则
        
        return text
    
    def detect_language(self, text: str) -> str:
        """
        检测文本语言
        
        Args:
            text: 要检测的文本
            
        Returns:
            语言代码，如'zh'（中文）、'en'（英文）、'mix'（混合）
        """
        has_chinese = bool(self.CHINESE_CHAR_PATTERN.search(text))
        has_latin = bool(re.search(r'[a-zA-Z]', text))
        
        if has_chinese and not has_latin:
            return 'zh'
        elif has_latin and not has_chinese:
            return 'en'
        else:
            return 'mix'
    
    def split_text(self, text: str, max_length: Optional[int] = None) -> List[str]:
        """
        将文本分割为多个段落，每个段落长度不超过最大长度
        
        Args:
            text: 要分割的文本
            max_length: 最大段落长度，默认使用初始化时设置的值
            
        Returns:
            分割后的文本段落列表
        """
        if max_length is None:
            max_length = self.max_segment_length
        
        if len(text) <= max_length:
            return [text]
        
        segments = []
        start = 0
        
        while start < len(text):
            end = min(start + max_length, len(text))
            
            # 如果不是文本末尾，尝试在合适的标点符号处分割
            if end < len(text):
                # 从max_length位置向前查找合适的标点符号
                best_split_pos = self._find_best_split_position(text, start, end)
                if best_split_pos > start:
                    end = best_split_pos
            
            # 添加段落
            segments.append(text[start:end])
            
            # 更新起始位置，考虑重叠
            start = end - self.overlap
            if start < 0:
                start = 0
        
        return segments
    
    def _find_best_split_position(self, text: str, start: int, end: int) -> int:
        """
        查找最佳分割位置
        
        Args:
            text: 文本
            start: 起始位置
            end: 结束位置
            
        Returns:
            最佳分割位置
        """
        best_priority = -1
        best_position = end
        
        # 跟踪括号等配对标点
        stack = []
        
        # 从end向前搜索
        for i in range(end, start, -1):
            char = text[i-1]
            
            # 检查是否为闭合括号
            if char in self.MATCHING_PUNCTUATION.values():
                # 找到对应的开括号
                for opening, closing in self.MATCHING_PUNCTUATION.items():
                    if closing == char:
                        stack.append(opening)
                        break
            
            # 检查是否为开括号
            elif char in self.MATCHING_PUNCTUATION.keys():
                # 如果栈不为空且与栈顶匹配，弹出栈顶
                if stack and stack[-1] == char:
                    stack.pop()
                else:
                    stack.append(char)
            
            # 检查标点符号优先级
            if char in self.PUNCTUATION_PRIORITY and not stack:
                priority = self.PUNCTUATION_PRIORITY[char]
                if priority > best_priority:
                    best_priority = priority
                    best_position = i
        
        return best_position
    
    def extract_markers(self, text: str) -> tuple:
        """
        提取文本中的标记，如语速、音高、风格等
        
        Args:
            text: 原始文本
            
        Returns:
            (清理后的文本, 标记字典)
        """
        markers = {}
        pattern = re.compile(r"\[\s*([a-zA-Z_]+)\s*=\s*([^\]]+)\]")
        def _repl(m):
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            try:
                if key in ("speed", "pitch", "emotion"):
                    markers[key] = float(val)
                elif key == "style":
                    try:
                        markers[key] = int(val)
                    except Exception:
                        markers[key] = str(val).lower()
                elif key in ("emotion_key", "emotion_label"):
                    markers["emotion_key"] = str(val).lower()
                else:
                    markers[key] = val
            except Exception:
                markers[key] = val
            return ""
        cleaned = re.sub(pattern, _repl, text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned, markers

    def remove_bracketed(self, text: str) -> str:
        s = text
        patterns = [
            r"\([^)]*\)",
            r"（[^）]*）",
            r"\{[^}]*\}",
            r"\[[^\]]*\]"
        ]
        for _ in range(3):
            for p in patterns:
                s = re.sub(p, " ", s)
            s = re.sub(r"\s{2,}", " ", s).strip()
        return s
