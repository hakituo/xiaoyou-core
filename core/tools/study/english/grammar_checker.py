#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英语语法错误自动检测器
支持高考核心语法错误检测、批量处理、修改建议、错误分析报告
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Optional
from language_tool_python import LanguageTool
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class GrammarChecker:
    """语法错误检测器"""
    
    def __init__(self):
        """初始化语法检测器"""
        # 使用公共远程服务器以避免下载本地Java服务器（解决下载慢的问题）
        # 注意：公共服务器可能有请求限制
        try:
            self.tool = LanguageTool('en-US', remote_server='https://api.languagetool.org/v2/')
        except Exception as e:
            print(f"Warning: Failed to connect to LanguageTool remote server: {e}. Falling back to local/default.")
            self.tool = LanguageTool('en-US')
            
        self.config = {
            "detect_chinese_english": True,  # 检测中式英语
            "error_types": {
                "时态": True,
                "主谓一致": True,
                "非谓语": True,
                "冠词": True,
                "介词": True,
                "从句连接词": True,
                "代词": True,
                "比较级": True,
                "被动语态": True,
                "虚拟语气": True,
                "倒装句": True,
                "强调句": True,
                "并列句": True,
                "省略句": True,
                "固定搭配": True
            },
            "output_mode": "显示错误+修改建议"
        }
        self.error_history = []  # 错误历史记录
    
    def check_text(self, text: str) -> List[Dict[str, Any]]:
        """
        检查文本中的语法错误
        
        Args:
            text: 要检查的文本
        
        Returns:
            List[Dict[str, Any]]: 错误列表
        """
        if not text.strip():
            return []
        
        try:
            matches = self.tool.check(text)
            errors = []
            
            for match in matches:
                error = self._parse_error(match)
                if error:
                    errors.append(error)
            
            # 检测中式英语表达
            if self.config["detect_chinese_english"]:
                chinese_english_errors = self._detect_chinese_english(text)
                errors.extend(chinese_english_errors)
            
            # 记录错误历史
            self.error_history.append({
                "文本": text,
                "错误列表": errors,
                "检测时间": ""
            })
            
            return errors
        except Exception as e:
            print(f"语法检查失败: {e}")
            return []
    
    def _parse_error(self, match) -> Optional[Dict[str, Any]]:
        """
        解析错误匹配结果
        
        Args:
            match: LanguageTool匹配结果
        
        Returns:
            Optional[Dict[str, Any]]: 解析后的错误信息
        """
        error_type = self._classify_error(match)
        if not error_type or not self.config["error_types"].get(error_type, True):
            return None
        
        error = {
            "错误类型": error_type,
            "错误文本": match.context.text,
            "错误位置": {
                "开始": match.offset,
                "结束": match.offset + match.errorLength,
                "行号": 1,  # LanguageTool不提供行号，需要手动计算
                "列号": match.offset + 1
            },
            "错误描述": match.message,
            "修改建议": [suggestion.replace(" ", "") for suggestion in match.replacements if suggestion.strip()],
            "置信度": "高" if match.ruleId.startswith('MORFOLOGIK') else "中",
            "语法规则": match.ruleId,
            "对比例句": ""
        }
        
        # 计算行号和列号
        lines = match.context.text[:match.offset].split('\n')
        error["错误位置"]["行号"] = len(lines)
        error["错误位置"]["列号"] = len(lines[-1]) + 1
        
        return error
    
    def _classify_error(self, match) -> str:
        """
        将LanguageTool错误分类为高考核心语法类型
        
        Args:
            match: LanguageTool匹配结果
        
        Returns:
            str: 分类后的错误类型
        """
        rule_id = match.ruleId.lower()
        message = match.message.lower()
        
        # 时态相关错误
        if any(keyword in rule_id or keyword in message for keyword in ['tense', 'verb form', 'past', 'present', 'future']):
            return "时态"
        # 主谓一致
        elif any(keyword in rule_id or keyword in message for keyword in ['subject-verb', 'agreement']):
            return "主谓一致"
        # 非谓语动词
        elif any(keyword in rule_id or keyword in message for keyword in ['infinitiv', 'participle', 'gerund', 'verbing']):
            return "非谓语"
        # 冠词
        elif any(keyword in rule_id or keyword in message for keyword in ['article', 'a/an/the']):
            return "冠词"
        # 介词
        elif any(keyword in rule_id or keyword in message for keyword in ['preposition', 'wrong preposition']):
            return "介词"
        # 从句连接词
        elif any(keyword in rule_id or keyword in message for keyword in ['conjunction', 'clause', 'relative pronoun', 'subordinator']):
            return "从句连接词"
        # 代词
        elif any(keyword in rule_id or keyword in message for keyword in ['pronoun', 'reflexive', 'possessive']):
            return "代词"
        # 比较级
        elif any(keyword in rule_id or keyword in message for keyword in ['comparative', 'superlative']):
            return "比较级"
        # 被动语态
        elif "passive" in rule_id or "passive" in message:
            return "被动语态"
        # 虚拟语气
        elif "subjunctive" in rule_id or "subjunctive" in message:
            return "虚拟语气"
        # 固定搭配
        elif any(keyword in rule_id or keyword in message for keyword in ['collocation', 'idiom', 'phrasal verb']):
            return "固定搭配"
        
        return "其他"
    
    def _detect_chinese_english(self, text: str) -> List[Dict[str, Any]]:
        """
        检测中式英语表达
        
        Args:
            text: 要检查的文本
        
        Returns:
            List[Dict[str, Any]]: 中式英语错误列表
        """
        chinese_english_patterns = [
            {
                "pattern": r"although.*but",
                "error_type": "并列句",
                "description": "中式英语表达：同时使用although和but",
                "suggestion": "删除although或but",
                "example": "Although he is young, but he is very mature. → Although he is young, he is very mature."
            },
            {
                "pattern": r"because.*so",
                "error_type": "并列句",
                "description": "中式英语表达：同时使用because和so",
                "suggestion": "删除because或so",
                "example": "Because it rained, so we stayed at home. → Because it rained, we stayed at home."
            },
            {
                "pattern": r"very.*much",
                "error_type": "副词",
                "description": "中式英语表达：very和much错误搭配",
                "suggestion": "根据形容词/副词类型调整",
                "example": "I very much like it. → I like it very much."
            },
            {
                "pattern": r"many.*people think",
                "error_type": "固定搭配",
                "description": "中式英语表达：many people think",
                "suggestion": "改为Many people believe/hold",
                "example": "Many people think that... → Many people believe that..."
            }
        ]
        
        import re
        errors = []
        
        for pattern_info in chinese_english_patterns:
            matches = re.finditer(pattern_info["pattern"], text, re.IGNORECASE)
            for match in matches:
                error = {
                    "错误类型": pattern_info["error_type"],
                    "错误文本": match.group(),
                    "错误位置": {
                        "开始": match.start(),
                        "结束": match.end(),
                        "行号": text[:match.start()].count('\n') + 1,
                        "列号": match.start() - text.rfind('\n', 0, match.start())
                    },
                    "错误描述": pattern_info["description"],
                    "修改建议": [pattern_info["suggestion"]],
                    "置信度": "高",
                    "语法规则": "CHINESE_ENGLISH",
                    "对比例句": pattern_info["example"]
                }
                errors.append(error)
        
        return errors
    
    def generate_error_report(self, errors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成错误分析报告
        
        Args:
            errors: 错误列表
        
        Returns:
            Dict[str, Any]: 错误分析报告
        """
        if not errors:
            return {
                "总错误数": 0,
                "错误分布": {},
                "主要错误类型": [],
                "错误密度": 0.0
            }
        
        # 统计错误分布
        error_distribution = {}
        for error in errors:
            error_type = error["错误类型"]
            error_distribution[error_type] = error_distribution.get(error_type, 0) + 1
        
        # 计算错误密度（错误数/单词数）
        total_words = sum(1 for error in errors for word in error["错误文本"].split())
        error_density = len(errors) / total_words if total_words > 0 else 0
        
        # 主要错误类型（按数量排序）
        main_error_types = sorted(error_distribution.items(), key=lambda x: x[1], reverse=True)[:5]
        
        report = {
            "总错误数": len(errors),
            "错误分布": error_distribution,
            "主要错误类型": main_error_types,
            "错误密度": round(error_density, 3)
        }
        
        return report
    
    def fix_text(self, text: str, errors: List[Dict[str, Any]]) -> str:
        """
        根据错误列表修复文本
        
        Args:
            text: 原始文本
            errors: 错误列表
        
        Returns:
            str: 修复后的文本
        """
        fixed_text = text
        offset = 0
        
        # 按错误位置排序，从后往前修复
        sorted_errors = sorted(errors, key=lambda x: x["错误位置"]["开始"], reverse=True)
        
        for error in sorted_errors:
            start = error["错误位置"]["开始"] + offset
            end = error["错误位置"]["结束"] + offset
            
            if start >= len(fixed_text) or end > len(fixed_text):
                continue
            
            if error["修改建议"]:
                # 使用第一个修改建议
                fixed_text = fixed_text[:start] + error["修改建议"][0] + fixed_text[end:]
                offset += len(error["修改建议"][0]) - (end - start)
        
        return fixed_text
    
    def import_file(self, file_path: str) -> Optional[str]:
        """
        导入文件内容
        
        Args:
            file_path: 文件路径
        
        Returns:
            Optional[str]: 文件内容
        """
        try:
            data = DataIO.import_data(file_path)
            if isinstance(data, list):
                # 处理列表数据
                text = "\n".join([str(item) if not isinstance(item, dict) else str(item.get("text", "")) for item in data])
            else:
                text = str(data)
            return text
        except Exception as e:
            print(f"导入文件失败: {e}")
            return None
    
    def export_result(self, original_text: str, errors: List[Dict[str, Any]], file_path: str) -> bool:
        """
        导出检查结果
        
        Args:
            original_text: 原始文本
            errors: 错误列表
            file_path: 导出文件路径
        
        Returns:
            bool: 导出是否成功
        """
        try:
            # 生成修复后的文本
            fixed_text = self.fix_text(original_text, errors)
            
            # 生成报告
            report = self.generate_error_report(errors)
            
            # 准备导出数据
            export_data = {
                "原始文本": original_text,
                "修复后文本": fixed_text,
                "错误列表": errors,
                "错误分析报告": report,
                "导出时间": ""
            }
            
            DataIO.export_data([export_data], file_path, title="语法检查结果")
            return True
        except Exception as e:
            print(f"导出结果失败: {e}")
            return False


class GrammarCheckerGUI(GUIApp):
    """语法检测器GUI界面"""
    
    def __init__(self):
        """初始化GUI界面"""
        super().__init__("英语语法错误自动检测器", width=1000, height=700)
        self.checker = GrammarChecker()
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导入文本文件", "command": self.import_file},
            {"label": "导出结果", "command": self.export_result},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("检查", [
            {"label": "开始检查", "command": self.start_check},
            {"label": "修复文本", "command": self.fix_text},
            {"label": "清空内容", "command": self.clear_content}
        ])
        
        self.add_menu("设置", [
            {"label": "配置检查选项", "command": self.configure_options}
        ])
    
    def create_main_frame(self):
        """创建主界面"""
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 文本输入区域
        input_frame = BaseFrame(self.main_frame, padding="10")
        input_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        input_frame.create_label("输入要检查的文本：", 0, 0, sticky="w")
        
        # 文本输入框
        self.text_input = input_frame.create_text(1, 0, width=50, height=30, sticky="nsew")
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(input_frame, orient=tk.VERTICAL, command=self.text_input.yview)
        self.text_input.config(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")
        
        # 按钮区域
        button_frame = BaseFrame(input_frame, padding="10")
        button_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        
        button_frame.create_button("开始检查", self.start_check, 0, 0, width=12, padx=5)
        button_frame.create_button("修复文本", self.fix_text, 0, 1, width=12, padx=5)
        button_frame.create_button("导入文件", self.import_file, 0, 2, width=12, padx=5)
        button_frame.create_button("清空内容", self.clear_content, 0, 3, width=12, padx=5)
        
        # 结果显示区域
        result_frame = BaseFrame(self.main_frame, padding="10")
        result_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 结果标签
        result_frame.create_label("检查结果：", 0, 0, sticky="w")
        
        # 结果显示文本框
        self.result_text = result_frame.create_text(1, 0, width=50, height=25, sticky="nsew")
        
        # 结果滚动条
        result_scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.result_text.yview)
        self.result_text.config(yscrollcommand=result_scrollbar.set)
        result_scrollbar.grid(row=1, column=1, sticky="ns")
        
        # 错误统计区域
        stats_frame = BaseFrame(result_frame, padding="10")
        stats_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        
        self.stats_var = tk.StringVar(value="未检查文本")
        stats_label = stats_frame.create_label(self.stats_var.get(), 0, 0, sticky="w")
        stats_label.config(textvariable=self.stats_var)
        
        # 调整布局
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(1, weight=1)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(1, weight=1)
    
    def start_check(self):
        """开始检查文本"""
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            MessageBox.warning("提示", "请先输入要检查的文本")
            return
        
        # 开始检查
        errors = self.checker.check_text(text)
        
        # 显示结果
        self._display_errors(errors, text)
        
        # 更新统计信息
        report = self.checker.generate_error_report(errors)
        stats_text = f"共检测到 {report['总错误数']} 个错误，错误密度：{report['错误密度']} 个错误/单词"
        self.stats_var.set(stats_text)
        
        MessageBox.info("检查完成", f"共检测到 {len(errors)} 个错误")
    
    def _display_errors(self, errors: List[Dict[str, Any]], original_text: str):
        """
        显示错误结果
        
        Args:
            errors: 错误列表
            original_text: 原始文本
        """
        self.result_text.delete("1.0", tk.END)
        
        if not errors:
            self.result_text.insert(tk.END, "未检测到语法错误！\n", "correct")
            return
        
        # 根据输出模式显示结果
        if self.checker.config["output_mode"] == "仅显示错误":
            for i, error in enumerate(errors, 1):
                self.result_text.insert(tk.END, f"{i}. 错误类型：{error['错误类型']}\n", "error_type")
                self.result_text.insert(tk.END, f"   位置：第{error['错误位置']['行号']}行，第{error['错误位置']['列号']}列\n")
                self.result_text.insert(tk.END, f"   错误文本：{error['错误文本']}\n", "error_text")
                self.result_text.insert(tk.END, "\n")
        else:  # 显示错误+修改建议
            for i, error in enumerate(errors, 1):
                self.result_text.insert(tk.END, f"{i}. 错误类型：{error['错误类型']}\n", "error_type")
                self.result_text.insert(tk.END, f"   位置：第{error['错误位置']['行号']}行，第{error['错误位置']['列号']}列\n")
                self.result_text.insert(tk.END, f"   错误文本：{error['错误文本']}\n", "error_text")
                self.result_text.insert(tk.END, f"   错误描述：{error['错误描述']}\n")
                self.result_text.insert(tk.END, f"   置信度：{error['置信度']}\n")
                if error['修改建议']:
                    self.result_text.insert(tk.END, f"   修改建议：{', '.join(error['修改建议'])}\n", "suggestion")
                if error['对比例句']:
                    self.result_text.insert(tk.END, f"   对比例句：{error['对比例句']}\n", "example")
                self.result_text.insert(tk.END, "\n")
        
        # 配置文本样式
        self.result_text.tag_config("correct", foreground="green", font=(".SF NS Text", 12, "bold"))
        self.result_text.tag_config("error_type", foreground="red", font=(".SF NS Text", 11, "bold"))
        self.result_text.tag_config("error_text", foreground="orange", font=(".SF NS Text", 10, "italic"))
        self.result_text.tag_config("suggestion", foreground="blue", font=(".SF NS Text", 10))
        self.result_text.tag_config("example", foreground="purple", font=(".SF NS Text", 9, "italic"))
    
    def fix_text(self):
        """修复文本"""
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            MessageBox.warning("提示", "请先输入要检查的文本")
            return
        
        errors = self.checker.check_text(text)
        if not errors:
            MessageBox.info("提示", "未检测到语法错误，无需修复")
            return
        
        # 修复文本
        fixed_text = self.checker.fix_text(text, errors)
        
        # 创建修复结果窗口
        fix_window = tk.Toplevel(self.root)
        fix_window.title("修复后的文本")
        fix_window.geometry("800x600")
        
        fix_frame = BaseFrame(fix_window, padding="10")
        fix_frame.pack(fill=tk.BOTH, expand=True)
        
        fix_frame.create_label("修复后的文本：", 0, 0, sticky="w")
        
        # 显示修复后的文本
        text_widget = fix_frame.create_text(1, 0, width=80, height=30, sticky="nsew")
        text_widget.insert(tk.END, fixed_text)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(fix_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")
        
        # 按钮
        button_frame = BaseFrame(fix_window, padding="10")
        button_frame.pack(fill=tk.X)
        
        button_frame.create_button("复制到剪贴板", lambda: self._copy_to_clipboard(fixed_text, fix_window), 0, 0, width=15, padx=5)
        button_frame.create_button("替换原文本", lambda: self._replace_original_text(fixed_text, fix_window), 0, 1, width=15, padx=5)
        button_frame.create_button("关闭", fix_window.destroy, 0, 2, width=15, padx=5)
    
    def _copy_to_clipboard(self, text: str, window: tk.Toplevel):
        """
        复制文本到剪贴板
        
        Args:
            text: 要复制的文本
            window: 窗口对象
        """
        window.clipboard_clear()
        window.clipboard_append(text)
        MessageBox.info("成功", "文本已复制到剪贴板")
    
    def _replace_original_text(self, text: str, window: tk.Toplevel):
        """
        替换原文本
        
        Args:
            text: 修复后的文本
            window: 窗口对象
        """
        self.text_input.delete("1.0", tk.END)
        self.text_input.insert("1.0", text)
        window.destroy()
        MessageBox.info("成功", "已替换原文本")
    
    def import_file(self):
        """导入文件"""
        file_path = FileDialog.open_file(
            title="导入文本文件",
            filetypes=[("文本文件", "*.txt"), ("Word文件", "*.docx"), ("Excel文件", "*.xlsx;*.xls"), ("所有文件", "*.*")]
        )
        
        if file_path:
            text = self.checker.import_file(file_path)
            if text:
                self.text_input.delete("1.0", tk.END)
                self.text_input.insert("1.0", text)
                MessageBox.info("成功", f"已导入文件：{os.path.basename(file_path)}")
            else:
                MessageBox.error("失败", "导入文件失败，请检查文件格式")
    
    def export_result(self):
        """
        导出结果
        """
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            MessageBox.warning("提示", "请先输入要检查的文本")
            return
        
        errors = self.checker.check_text(text)
        if not errors:
            MessageBox.warning("提示", "未检测到语法错误，无需导出")
            return
        
        # 选择导出路径
        file_path = FileDialog.save_file(
            title="导出检查结果",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            if self.checker.export_result(text, errors, file_path):
                MessageBox.info("成功", f"检查结果已导出到 {file_path}")
            else:
                MessageBox.error("失败", "导出结果失败")
    
    def clear_content(self):
        """
        清空内容
        """
        if MessageBox.question("确认", "确定要清空所有内容吗？"):
            self.text_input.delete("1.0", tk.END)
            self.result_text.delete("1.0", tk.END)
            self.stats_var.set("未检查文本")
    
    def configure_options(self):
        """
        配置检查选项
        """
        # 创建配置窗口
        config_window = tk.Toplevel(self.root)
        config_window.title("配置检查选项")
        config_window.geometry("600x500")
        
        config_frame = BaseFrame(config_window, padding="10")
        config_frame.pack(fill=tk.BOTH, expand=True)
        
        # 检测中式英语选项
        config_frame.create_label("检测选项", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        
        self.chinese_english_var = tk.BooleanVar(value=self.checker.config["detect_chinese_english"])
        config_frame.create_checkbutton("检测中式英语表达", self.chinese_english_var, 1, 0, sticky="w")
        
        # 错误类型选项
        config_frame.create_label("\n检测的错误类型", 2, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        
        row = 3
        for error_type, enabled in self.checker.config["error_types"].items():
            var = tk.BooleanVar(value=enabled)
            setattr(self, f"{error_type}_var", var)  # 动态保存变量
            config_frame.create_checkbutton(error_type, var, row, 0, sticky="w")
            row += 1
        
        # 输出模式选项
        config_frame.create_label("\n输出模式", row, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        row += 1
        
        self.output_mode_var = tk.StringVar(value=self.checker.config["output_mode"])
        config_frame.create_radiobutton("仅显示错误", self.output_mode_var, "仅显示错误", row, 0, sticky="w")
        row += 1
        config_frame.create_radiobutton("显示错误+修改建议", self.output_mode_var, "显示错误+修改建议", row, 0, sticky="w")
        
        # 保存按钮
        button_frame = BaseFrame(config_window, padding="10")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        button_frame.create_button("保存配置", lambda: self._save_config(config_window), 0, 0, width=12)
        button_frame.create_button("取消", config_window.destroy, 0, 1, width=12, padx=10)
    
    def _save_config(self, window: tk.Toplevel):
        """
        保存配置
        
        Args:
            window: 配置窗口
        """
        # 更新检测中式英语选项
        self.checker.config["detect_chinese_english"] = self.chinese_english_var.get()
        
        # 更新错误类型选项
        for error_type in self.checker.config["error_types"]:
            var = getattr(self, f"{error_type}_var", None)
            if var:
                self.checker.config["error_types"][error_type] = var.get()
        
        # 更新输出模式
        self.checker.config["output_mode"] = self.output_mode_var.get()
        
        MessageBox.info("成功", "配置已保存")
        window.destroy()


if __name__ == "__main__":
    app = GrammarCheckerGUI()
    app.run()