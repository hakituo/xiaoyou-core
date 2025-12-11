#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学错题自动整理与分析工具
支持错题输入、分类、统计、可视化和导出等功能
"""

import os
import json
import random
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta
from collections import Counter
import matplotlib.pyplot as plt
from ..common.utils import generate_unique_id
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class MathErrorAnalyzer:
    """数学错题分析器"""
    
    def __init__(self):
        """初始化错题分析器"""
        self.errors = []  # 错题列表
        self.knowledge_points = {
            "三角函数": ["正弦定理", "余弦定理", "三角函数图像", "三角恒等变换"],
            "立体几何": ["空间几何体", "空间点线面关系", "空间角", "空间距离"],
            "概率统计": ["古典概型", "几何概型", "分布列", "数学期望", "方差"],
            "导数": ["导数计算", "单调性", "极值", "最值", "导数应用"],
            "解析几何": ["直线方程", "圆", "椭圆", "双曲线", "抛物线"],
            "数列": ["等差数列", "等比数列", "数列求和", "数列通项"],
            "不等式": ["不等式性质", "线性规划", "基本不等式"],
            "向量": ["平面向量", "空间向量", "向量运算"],
            "复数": ["复数概念", "复数运算"],
            "集合与逻辑": ["集合运算", "命题逻辑", "充要条件"]
        }
        
        self.error_reasons = ["知识点遗漏", "计算错误", "审题失误", "思路偏差"]
    
    def add_error(self, error_info: Dict[str, Any]) -> bool:
        """
        添加错题
        
        Args:
            error_info: 错题信息
        
        Returns:
            bool: 添加是否成功
        """
        try:
            # 验证必填字段
            required_fields = ["题干", "错误答案", "正确答案", "错误原因"]
            if not all(field in error_info for field in required_fields):
                return False
            
            # 生成唯一ID
            error_info["id"] = f"err_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000, 9999)}"
            
            # 添加默认字段
            error_info["添加时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            error_info["修改时间"] = error_info["添加时间"]
            error_info["复习次数"] = 0
            error_info["掌握程度"] = "未掌握"
            error_info["标记"] = ""
            
            # 自动分类知识点
            if "知识点" not in error_info or not error_info["知识点"]:
                # 简单的知识点匹配，后续可优化
                error_info["知识点"] = self._auto_classify_knowledge_point(error_info["题干"])
            
            self.errors.append(error_info)
            return True
        except Exception as e:
            print(f"添加错题失败: {e}")
            return False
    
    def _auto_classify_knowledge_point(self, problem: str) -> str:
        """
        自动分类知识点
        
        Args:
            problem: 题干
        
        Returns:
            str: 知识点
        """
        # 简单的关键词匹配
        for module, points in self.knowledge_points.items():
            for point in points:
                if point in problem:
                    return point
        return "未分类"
    
    def get_errors_by_knowledge_point(self, knowledge_point: str) -> List[Dict[str, Any]]:
        """
        根据知识点获取错题
        
        Args:
            knowledge_point: 知识点
        
        Returns:
            List[Dict[str, Any]]: 错题列表
        """
        return [error for error in self.errors if error.get("知识点") == knowledge_point]
    
    def get_errors_by_reason(self, reason: str) -> List[Dict[str, Any]]:
        """
        根据错误原因获取错题
        
        Args:
            reason: 错误原因
        
        Returns:
            List[Dict[str, Any]]: 错题列表
        """
        return [error for error in self.errors if error.get("错误原因") == reason]
    
    def get_error_stats(self) -> Dict[str, Any]:
        """
        获取错误统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        # 知识点错误频率
        knowledge_counter = Counter([error.get("知识点", "未分类") for error in self.errors])
        
        # 错误原因统计
        reason_counter = Counter([error.get("错误原因", "其他") for error in self.errors])
        
        # 薄弱知识点（错误3次以上）
        weak_points = [point for point, count in knowledge_counter.items() if count >= 3]
        
        return {
            "总错题数": len(self.errors),
            "知识点分布": dict(knowledge_counter),
            "错误原因分布": dict(reason_counter),
            "薄弱知识点": weak_points,
            "平均错误次数": sum(knowledge_counter.values()) / len(knowledge_counter) if knowledge_counter else 0
        }
    
    def generate_visualization(self, output_path: str) -> bool:
        """
        生成可视化图表
        
        Args:
            output_path: 输出路径
        
        Returns:
            bool: 生成是否成功
        """
        try:
            stats = self.get_error_stats()
            
            # 创建图表
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
            fig.suptitle("数学错题分析")
            
            # 柱状图：知识点错误分布
            knowledge_data = stats["知识点分布"]
            if knowledge_data:
                ax1.bar(range(len(knowledge_data)), list(knowledge_data.values()), align='center')
                ax1.set_xticks(range(len(knowledge_data)))
                ax1.set_xticklabels(list(knowledge_data.keys()), rotation=45, ha='right')
                ax1.set_title("各知识点错误次数")
                ax1.set_xlabel("知识点")
                ax1.set_ylabel("错误次数")
            
            # 饼图：错误原因占比
            reason_data = stats["错误原因分布"]
            if reason_data:
                ax2.pie(list(reason_data.values()), labels=list(reason_data.keys()), autopct='%1.1f%%')
                ax2.set_title("错误原因占比")
            
            # 保存图表
            plt.tight_layout()
            plt.savefig(output_path)
            plt.close()
            
            return True
        except Exception as e:
            print(f"生成图表失败: {e}")
            return False
    
    def export_errors(self, file_path: str, filter_criteria: Dict[str, str] = None) -> bool:
        """
        导出错题集
        
        Args:
            file_path: 文件路径
            filter_criteria: 筛选条件
        
        Returns:
            bool: 导出是否成功
        """
        try:
            # 筛选错题
            filtered_errors = self.errors
            if filter_criteria:
                for key, value in filter_criteria.items():
                    filtered_errors = [error for error in filtered_errors if error.get(key) == value]
            
            # 准备导出数据
            export_data = []
            for error in filtered_errors:
                export_data.append({
                    "序号": len(export_data) + 1,
                    "题干": error["题干"],
                    "错误答案": error["错误答案"],
                    "正确答案": error["正确答案"],
                    "错误原因": error["错误原因"],
                    "知识点": error["知识点"],
                    "添加时间": error["添加时间"],
                    "掌握程度": error["掌握程度"],
                    "标记": error["标记"]
                })
            
            # 导出数据
            DataIO.export_data(export_data, file_path, title="数学错题集")
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False
    
    def get_weak_points(self) -> List[Dict[str, Any]]:
        """
        获取薄弱知识点
        
        Returns:
            List[Dict[str, Any]]: 薄弱知识点列表
        """
        stats = self.get_error_stats()
        return stats["薄弱知识点"]
    
    def set_weekly_review_reminder(self, day_of_week: int = 0, time: str = "14:00") -> bool:
        """
        设置每周复盘提醒
        
        Args:
            day_of_week: 星期几（0-6，0表示周日）
            time: 提醒时间
        
        Returns:
            bool: 设置是否成功
        """
        try:
            # 简单实现，后续可添加系统提醒功能
            reminder_info = {
                "星期几": day_of_week,
                "时间": time,
                "设置时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "下一次提醒": self._calculate_next_reminder(day_of_week, time)
            }
            
            # 保存提醒设置
            with open("review_reminder.json", "w", encoding="utf-8") as f:
                json.dump(reminder_info, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"设置提醒失败: {e}")
            return False
    
    def _calculate_next_reminder(self, day_of_week: int, time: str) -> str:
        """
        计算下一次提醒时间
        
        Args:
            day_of_week: 星期几
            time: 提醒时间
        
        Returns:
            str: 下一次提醒时间
        """
        now = datetime.now()
        hour, minute = map(int, time.split(":"))
        
        # 获取当前星期几
        current_weekday = now.weekday()  # 0-6，0表示周一
        # 转换为用户使用的格式（0表示周日）
        current_weekday = 6 if current_weekday == 0 else current_weekday - 1
        
        # 计算天数差
        days_ahead = day_of_week - current_weekday
        if days_ahead <= 0:
            days_ahead += 7
        
        # 计算下一次提醒时间
        next_reminder = now + timedelta(days=days_ahead)
        next_reminder = next_reminder.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        return next_reminder.strftime("%Y-%m-%d %H:%M:%S")
    
    def update_error(self, error_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新错题信息
        
        Args:
            error_id: 错题ID
            updates: 更新的字段
        
        Returns:
            bool: 更新是否成功
        """
        for error in self.errors:
            if error["id"] == error_id:
                # 更新字段
                for field, value in updates.items():
                    if field in error and field != "id" and field != "添加时间":
                        error[field] = value
                
                # 更新修改时间
                error["修改时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return True
        
        return False
    
    def delete_error(self, error_id: str) -> bool:
        """
        删除错题
        
        Args:
            error_id: 错题ID
        
        Returns:
            bool: 删除是否成功
        """
        for i, error in enumerate(self.errors):
            if error["id"] == error_id:
                del self.errors[i]
                return True
        
        return False
    
    def get_all_errors(self) -> List[Dict[str, Any]]:
        """
        获取所有错题
        
        Returns:
            List[Dict[str, Any]]: 错题列表
        """
        return self.errors.copy()
    
    def search_errors(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """
        根据关键词搜索错题
        
        Args:
            keywords: 关键词列表
        
        Returns:
            List[Dict[str, Any]]: 搜索结果
        """
        if not keywords:
            return self.errors.copy()
        
        results = []
        for error in self.errors:
            match = True
            for keyword in keywords:
                found = False
                for field in ["题干", "知识点", "错误原因", "标记"]:
                    if keyword in str(error.get(field, "")):
                        found = True
                        break
                if not found:
                    match = False
                    break
            if match:
                results.append(error)
        
        return results


class MathErrorAnalyzerGUI(GUIApp):
    """数学错题分析器GUI界面"""
    
    def __init__(self):
        """
        初始化GUI界面
        """
        super().__init__("数学错题自动整理与分析工具", width=1000, height=700)
        self.analyzer = MathErrorAnalyzer()
        
        # 创建主界面
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导出错题集", "command": self.export_errors},
            {"label": "生成统计图表", "command": self.generate_chart},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
    
    def create_main_frame(self):
        """
        创建主界面
        """
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 左侧：错题列表和筛选
        left_frame = BaseFrame(self.main_frame, padding="5")
        left_frame.pack(side=tk.LEFT, fill=tk.Y, width=300)
        
        # 右侧：错题详情和操作
        right_frame = BaseFrame(self.main_frame, padding="5")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 左侧区域
        
        # 搜索框
        left_frame.create_label("关键词搜索：", 0, 0, sticky="w", pady=5)
        self.search_var = tk.StringVar(value="")
        search_entry = left_frame.create_entry(0, 1, width=25)
        search_entry.config(textvariable=self.search_var)
        search_button = left_frame.create_button("搜索", self.search_errors, 0, 2, sticky="w", padx=5)
        
        # 筛选条件
        left_frame.create_label("筛选条件", 1, 0, sticky="w", font=(".SF NS Text", 11, "bold"), pady=10)
        
        # 知识点筛选
        left_frame.create_label("知识点：", 2, 0, sticky="w")
        # 合并所有知识点
        all_knowledge_points = []
        for module, points in self.analyzer.knowledge_points.items():
            all_knowledge_points.extend(points)
        self.knowledge_var = tk.StringVar(value="")
        knowledge_combo = left_frame.create_combobox(all_knowledge_points, 2, 1, width=20)
        knowledge_combo.config(textvariable=self.knowledge_var)
        
        # 错误原因筛选
        left_frame.create_label("错误原因：", 3, 0, sticky="w", pady=5)
        self.reason_var = tk.StringVar(value="")
        reason_combo = left_frame.create_combobox(self.analyzer.error_reasons, 3, 1, width=20)
        reason_combo.config(textvariable=self.reason_var)
        
        # 筛选按钮
        filter_button = left_frame.create_button("筛选", self.filter_errors, 4, 0, columnspan=2, pady=10)
        reset_button = left_frame.create_button("重置", self.reset_filter, 4, 2, sticky="w")
        
        # 错题列表
        left_frame.create_label("错题列表", 5, 0, sticky="w", font=(".SF NS Text", 11, "bold"), pady=10)
        self.error_listbox = left_frame.create_listbox(6, 0, columnspan=3, height=25, sticky="nsew")
        self.error_listbox.bind("<<ListboxSelect>>", self.on_error_select)
        
        # 右侧区域
        
        # 错题详情标题
        right_frame.create_label("错题详情", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        
        # 错题信息显示
        self.detail_text = right_frame.create_text(1, 0, width=80, height=20, sticky="nsew")
        
        # 操作按钮
        button_frame = BaseFrame(right_frame, padding="5")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        
        self.add_button = button_frame.create_button("添加错题", self.add_error, 0, 0, sticky="w")
        self.edit_button = button_frame.create_button("编辑错题", self.edit_error, 0, 1, sticky="w", padx=10)
        self.delete_button = button_frame.create_button("删除错题", self.delete_error, 0, 2, sticky="w", padx=10)
        self.export_button = button_frame.create_button("导出错题集", self.export_errors, 0, 3, sticky="w", padx=10)
        self.chart_button = button_frame.create_button("生成图表", self.generate_chart, 0, 4, sticky="w", padx=10)
        
        # 统计信息
        stat_frame = BaseFrame(right_frame, padding="5")
        stat_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.stat_label = stat_frame.create_label("总错题数：0 | 薄弱知识点：0", 0, 0, sticky="w", font=(".SF NS Text", 11, "bold"))
        
        # 更新列表和统计
        self.update_error_list()
        self.update_statistics()
    
    def update_error_list(self, errors: List[Dict[str, Any]] = None):
        """
        更新错题列表
        
        Args:
            errors: 错题列表，None表示显示所有
        """
        # 清空列表
        self.error_listbox.delete(0, tk.END)
        
        if errors is None:
            errors = self.analyzer.get_all_errors()
        
        # 添加到列表
        for error in errors:
            self.error_listbox.insert(tk.END, f"{error['题干'][:50]}... - {error['知识点']}")
        
        # 保存当前显示的错题
        self.current_displayed_errors = errors
    
    def update_statistics(self):
        """
        更新统计信息
        """
        stats = self.analyzer.get_error_stats()
        weak_count = len(stats["薄弱知识点"])
        self.stat_label.config(text=f"总错题数：{stats['总错题数']} | 薄弱知识点：{weak_count}")
    
    def on_error_select(self, event=None):
        """
        错题选择事件
        """
        selection = self.error_listbox.curselection()
        if selection:
            index = selection[0]
            if 0 <= index < len(self.current_displayed_errors):
                error = self.current_displayed_errors[index]
                self.show_error_detail(error)
    
    def show_error_detail(self, error: Dict[str, Any]):
        """
        显示错题详情
        
        Args:
            error: 错题数据
        """
        self.detail_text.delete("1.0", tk.END)
        
        detail = "错题详情：\n\n"
        for field, value in error.items():
            detail += f"{field}：{value}\n"
        
        self.detail_text.insert(tk.END, detail)
    
    def add_error(self):
        """
        添加错题
        """
        # 创建添加错题窗口
        add_window = tk.Toplevel(self.root)
        add_window.title("添加错题")
        add_window.geometry("800x600")
        add_window.resizable(True, True)
        
        # 创建添加错题框架
        add_frame = BaseFrame(add_window, padding="10")
        add_frame.pack(fill=tk.BOTH, expand=True)
        
        # 错题字段
        fields = [
            ("题干", tk.Text, 0, 0, 70, 5),
            ("错误答案", tk.Text, 1, 0, 70, 3),
            ("正确答案", tk.Text, 2, 0, 70, 3),
            ("错误原因", ttk.Combobox, 3, 0, 68, self.analyzer.error_reasons),
            ("知识点", ttk.Combobox, 4, 0, 68, [point for points in self.analyzer.knowledge_points.values() for point in points]),
            ("标记", tk.Entry, 5, 0, 70)
        ]
        
        # 创建字段组件
        field_widgets = {}
        for field_name, widget_type, row, column, width, *args in fields:
            add_frame.create_label(f"{field_name}：", row, column, sticky="nw", pady=5)
            
            if widget_type == tk.Entry:
                widget = tk.Entry(add_frame, width=width)
                widget.grid(row=row, column=column+1, sticky="ew", pady=5)
            elif widget_type == ttk.Combobox:
                values = args[0] if args else []
                widget = ttk.Combobox(add_frame, values=values, width=width-2, state="readonly")
                widget.grid(row=row, column=column+1, sticky="ew", pady=5)
            elif widget_type == tk.Text:
                height = args[0] if args else 3
                widget = tk.Text(add_frame, width=width, height=height, wrap=tk.WORD)
                widget.grid(row=row, column=column+1, sticky="ew", pady=5)
                
                # 添加滚动条
                scrollbar = ttk.Scrollbar(add_frame, orient=tk.VERTICAL, command=widget.yview)
                scrollbar.grid(row=row, column=column+2, sticky="ns", pady=5)
                widget.config(yscrollcommand=scrollbar.set)
            
            field_widgets[field_name] = widget
        
        # 确定按钮
        def confirm_add():
            # 收集错题数据
            error_data = {}
            for field_name, widget in field_widgets.items():
                if isinstance(widget, tk.Entry) or isinstance(widget, ttk.Combobox):
                    error_data[field_name] = widget.get()
                elif isinstance(widget, tk.Text):
                    error_data[field_name] = widget.get("1.0", tk.END).strip()
            
            # 添加错题
            if self.analyzer.add_error(error_data):
                MessageBox.info("成功", "错题添加成功")
                add_window.destroy()
                self.update_error_list()
                self.update_statistics()
            else:
                MessageBox.error("失败", "错题添加失败，请检查必填字段")
        
        confirm_button = add_frame.create_button("确定添加", confirm_add, 6, 0, columnspan=3, sticky="ew", pady=15)
        
        # 取消按钮
        cancel_button = add_frame.create_button("取消", add_window.destroy, 6, 1, columnspan=3, sticky="ew")
    
    def edit_error(self):
        """
        编辑错题
        """
        selection = self.error_listbox.curselection()
        if not selection:
            MessageBox.warning("提示", "请先选择要编辑的错题")
            return
        
        index = selection[0]
        if 0 <= index < len(self.current_displayed_errors):
            error = self.current_displayed_errors[index]
            
            # 创建编辑错题窗口
            edit_window = tk.Toplevel(self.root)
            edit_window.title("编辑错题")
            edit_window.geometry("800x600")
            edit_window.resizable(True, True)
            
            # 创建编辑错题框架
            edit_frame = BaseFrame(edit_window, padding="10")
            edit_frame.pack(fill=tk.BOTH, expand=True)
            
            # 错题字段
            fields = [
                ("题干", tk.Text, 0, 0, 70, 5),
                ("错误答案", tk.Text, 1, 0, 70, 3),
                ("正确答案", tk.Text, 2, 0, 70, 3),
                ("错误原因", ttk.Combobox, 3, 0, 68, self.analyzer.error_reasons),
                ("知识点", ttk.Combobox, 4, 0, 68, [point for points in self.analyzer.knowledge_points.values() for point in points]),
                ("标记", tk.Entry, 5, 0, 70)
            ]
            
            # 创建字段组件并填充数据
            field_widgets = {}
            for field_name, widget_type, row, column, width, *args in fields:
                edit_frame.create_label(f"{field_name}：", row, column, sticky="nw", pady=5)
                
                if widget_type == tk.Entry:
                    widget = tk.Entry(edit_frame, width=width)
                    widget.insert(0, error.get(field_name, ""))
                    widget.grid(row=row, column=column+1, sticky="ew", pady=5)
                elif widget_type == ttk.Combobox:
                    values = args[0] if args else []
                    widget = ttk.Combobox(edit_frame, values=values, width=width-2, state="readonly")
                    widget.set(error.get(field_name, ""))
                    widget.grid(row=row, column=column+1, sticky="ew", pady=5)
                elif widget_type == tk.Text:
                    height = args[0] if args else 3
                    widget = tk.Text(edit_frame, width=width, height=height, wrap=tk.WORD)
                    widget.insert("1.0", error.get(field_name, ""))
                    widget.grid(row=row, column=column+1, sticky="ew", pady=5)
                    
                    # 添加滚动条
                    scrollbar = ttk.Scrollbar(edit_frame, orient=tk.VERTICAL, command=widget.yview)
                    scrollbar.grid(row=row, column=column+2, sticky="ns", pady=5)
                    widget.config(yscrollcommand=scrollbar.set)
                
                field_widgets[field_name] = widget
            
            # 确定按钮
            def confirm_edit():
                # 收集更新数据
                update_data = {}
                for field_name, widget in field_widgets.items():
                    if isinstance(widget, tk.Entry) or isinstance(widget, ttk.Combobox):
                        new_value = widget.get()
                    elif isinstance(widget, tk.Text):
                        new_value = widget.get("1.0", tk.END).strip()
                    
                    # 只有当值发生变化时才更新
                    if new_value != error.get(field_name, ""):
                        update_data[field_name] = new_value
                
                # 更新错题
                if update_data:
                    if self.analyzer.update_error(error["id"], update_data):
                        MessageBox.info("成功", "错题更新成功")
                        edit_window.destroy()
                        self.update_error_list()
                        self.update_statistics()
                        # 更新当前显示
                        if self.current_displayed_errors[index]["id"] == error["id"]:
                            self.current_displayed_errors[index] = self.analyzer.get_all_errors()[index]
                            self.show_error_detail(self.current_displayed_errors[index])
                    else:
                        MessageBox.error("失败", "错题更新失败")
                else:
                    MessageBox.info("提示", "没有修改任何内容")
                    edit_window.destroy()
            
            confirm_button = edit_frame.create_button("确定更新", confirm_edit, 6, 0, columnspan=3, sticky="ew", pady=15)
            
            # 取消按钮
            cancel_button = edit_frame.create_button("取消", edit_window.destroy, 6, 1, columnspan=3, sticky="ew")
    
    def delete_error(self):
        """
        删除错题
        """
        selection = self.error_listbox.curselection()
        if not selection:
            MessageBox.warning("提示", "请先选择要删除的错题")
            return
        
        index = selection[0]
        if 0 <= index < len(self.current_displayed_errors):
            error = self.current_displayed_errors[index]
            if MessageBox.question("确认", f"确定要删除这道错题吗？"):
                if self.analyzer.delete_error(error["id"]):
                    MessageBox.info("成功", "错题删除成功")
                    self.update_error_list()
                    self.update_statistics()
                    self.detail_text.delete("1.0", tk.END)
                else:
                    MessageBox.error("失败", "错题删除失败")
    
    def search_errors(self):
        """
        搜索错题
        """
        keywords = self.search_var.get().strip().split()
        results = self.analyzer.search_errors(keywords)
        self.update_error_list(results)
    
    def filter_errors(self):
        """
        筛选错题
        """
        knowledge = self.knowledge_var.get()
        reason = self.reason_var.get()
        
        filter_criteria = {}
        if knowledge:
            filter_criteria["知识点"] = knowledge
        if reason:
            filter_criteria["错误原因"] = reason
        
        # 应用筛选
        filtered = self.analyzer.get_all_errors()
        for key, value in filter_criteria.items():
            filtered = [error for error in filtered if error.get(key) == value]
        
        self.update_error_list(filtered)
    
    def reset_filter(self):
        """
        重置筛选条件
        """
        self.search_var.set("")
        self.knowledge_var.set("")
        self.reason_var.set("")
        self.update_error_list()
    
    def export_errors(self):
        """
        导出错题集
        """
        if not self.analyzer.get_all_errors():
            MessageBox.warning("提示", "没有错题可以导出")
            return
        
        # 选择导出路径
        file_path = FileDialog.save_file(
            title="导出错题集",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            # 获取当前筛选条件
            knowledge = self.knowledge_var.get()
            reason = self.reason_var.get()
            
            filter_criteria = {}
            if knowledge:
                filter_criteria["知识点"] = knowledge
            if reason:
                filter_criteria["错误原因"] = reason
            
            if self.analyzer.export_errors(file_path, filter_criteria):
                MessageBox.info("成功", f"错题集已导出到 {file_path}")
            else:
                MessageBox.error("失败", "导出错题集失败")
    
    def generate_chart(self):
        """
        生成统计图表
        """
        if not self.analyzer.get_all_errors():
            MessageBox.warning("提示", "没有错题数据可以生成图表")
            return
        
        # 选择导出路径
        file_path = FileDialog.save_file(
            title="生成统计图表",
            defaultextension=".png",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("PDF文件", "*.pdf")]
        )
        
        if file_path:
            if self.analyzer.generate_visualization(file_path):
                MessageBox.info("成功", f"统计图表已生成到 {file_path}")
            else:
                MessageBox.error("失败", "生成统计图表失败")


if __name__ == "__main__":
    # 测试代码
    app = MathErrorAnalyzerGUI()
    app.run()
