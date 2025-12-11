#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
易混概念对比记忆工具
支持概念分组、多种测试模式、记忆卡片生成等功能
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Optional
import random
from datetime import datetime
from collections import Counter
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class ConceptComparison:
    """易混概念对比记忆工具"""
    
    def __init__(self):
        """初始化概念对比工具"""
        self.concept_groups = []  # 概念组列表
        self.test_history = []  # 测试历史
        self.favorite_concepts = []  # 收藏的概念
        
        self.config = {
            "test_mode": "选择题",  # 测试模式：选择题/判断题/填空题
            "concept_count": 5,  # 每次测试的概念数量
            "difficulty": "全部",  # 难度：简单/中等/困难/全部
            "show_answer_immediately": True,  # 是否立即显示答案
            "randomize_options": True,  # 是否随机化选项顺序
            "test_scope": "全部",  # 测试范围：全部/收藏/未掌握
            "memory_card_style": "compact",  # 记忆卡片样式：compact/detailed
            "show_images": True,  # 是否显示图片
            "auto_save": True,  # 是否自动保存
            "save_interval": 60  # 自动保存间隔（秒）
        }
        
        # 测试模式配置
        self.test_mode_configs = {
            "选择题": {
                "options_count": 4,  # 选项数量
                "points_per_question": 2  # 每题分值
            },
            "判断题": {
                "points_per_question": 1  # 每题分值
            },
            "填空题": {
                "points_per_question": 3  # 每题分值
            }
        }
        
        # 难度等级
        self.difficulty_levels = {
            "简单": 1,
            "中等": 2,
            "困难": 3
        }
    
    def add_concept_group(self, group: Dict[str, Any]) -> bool:
        """
        添加概念组
        
        Args:
            group: 概念组信息
        
        Returns:
            bool: 添加是否成功
        """
        try:
            # 验证必填字段
            required_fields = ["组名", "概念列表"]
            if not all(field in group for field in required_fields):
                return False
            
            # 验证概念列表
            if not isinstance(group["概念列表"], list) or len(group["概念列表"]) < 2:
                return False
            
            # 规范化概念组
            normalized_group = self._normalize_concept_group(group)
            if normalized_group:
                self.concept_groups.append(normalized_group)
                return True
            return False
        except Exception as e:
            print(f"添加概念组失败: {e}")
            return False
    
    def _normalize_concept_group(self, group: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        规范化概念组
        
        Args:
            group: 原始概念组数据
        
        Returns:
            Optional[Dict[str, Any]]: 规范化后的概念组
        """
        try:
            normalized = {
                "组名": group["组名"].strip(),
                "概念列表": [],
                "分类": group.get("分类", "未分类").strip(),
                "难度": group.get("难度", "中等"),
                "创建时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "修改时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "测试次数": 0,
                "正确率": 0.0,
                "图片链接": group.get("图片链接", "").strip(),
                "描述": group.get("描述", "").strip(),
                "关键词": group.get("关键词", []),
                "关联知识点": group.get("关联知识点", [])
            }
            
            # 规范化概念
            for concept in group["概念列表"]:
                normalized_concept = self._normalize_concept(concept)
                if normalized_concept:
                    normalized["概念列表"].append(normalized_concept)
            
            return normalized
        except Exception as e:
            print(f"规范化概念组失败: {e}")
            return None
    
    def _normalize_concept(self, concept: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        规范化概念
        
        Args:
            concept: 原始概念数据
        
        Returns:
            Optional[Dict[str, Any]]: 规范化后的概念
        """
        try:
            required_fields = ["概念名称"]
            if not all(field in concept for field in required_fields):
                return None
            
            normalized = {
                "概念名称": concept["概念名称"].strip(),
                "定义": concept.get("定义", "").strip(),
                "核心特征": concept.get("核心特征", "").strip(),
                "适用范围": concept.get("适用范围", "").strip(),
                "典型例子": concept.get("典型例子", "").strip(),
                "关键区别": concept.get("关键区别", "").strip(),
                "易混点": concept.get("易混点", "").strip(),
                "图片链接": concept.get("图片链接", "").strip(),
                "记忆技巧": concept.get("记忆技巧", "").strip(),
                "掌握程度": "未掌握",
                "测试次数": 0,
                "正确次数": 0,
                "错误次数": 0,
                "最近测试时间": "",
                "错题记录": []
            }
            
            return normalized
        except Exception as e:
            print(f"规范化概念失败: {e}")
            return None
    
    def generate_test(self) -> List[Dict[str, Any]]:
        """
        生成测试题
        
        Returns:
            List[Dict[str, Any]]: 测试题列表
        """
        # 选择概念组
        filtered_groups = self._filter_concept_groups()
        if not filtered_groups:
            return []
        
        # 随机选择概念组
        selected_groups = random.sample(filtered_groups, min(len(filtered_groups), self.config["concept_count"]))
        
        # 生成测试题
        test_questions = []
        for group in selected_groups:
            question = self._generate_question(group)
            if question:
                test_questions.append(question)
        
        return test_questions
    
    def _filter_concept_groups(self) -> List[Dict[str, Any]]:
        """
        过滤概念组
        
        Returns:
            List[Dict[str, Any]]: 过滤后的概念组列表
        """
        filtered = []
        
        for group in self.concept_groups:
            # 按难度过滤
            if self.config["difficulty"] != "全部":
                if group["难度"] != self.config["difficulty"]:
                    continue
            
            # 按测试范围过滤
            if self.config["test_scope"] == "收藏":
                if group not in self.favorite_concepts:
                    continue
            elif self.config["test_scope"] == "未掌握":
                # 检查是否有未掌握的概念
                has_unmastered = any(concept["掌握程度"] == "未掌握" for concept in group["概念列表"])
                if not has_unmastered:
                    continue
            
            filtered.append(group)
        
        return filtered
    
    def _generate_question(self, group: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        生成单个测试题
        
        Args:
            group: 概念组
        
        Returns:
            Optional[Dict[str, Any]]: 测试题
        """
        if not group["概念列表"]:
            return None
        
        test_mode = self.config["test_mode"]
        
        if test_mode == "选择题":
            return self._generate_multiple_choice_question(group)
        elif test_mode == "判断题":
            return self._generate_true_false_question(group)
        elif test_mode == "填空题":
            return self._generate_fill_blank_question(group)
        
        return None
    
    def _generate_multiple_choice_question(self, group: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成选择题
        
        Args:
            group: 概念组
        
        Returns:
            Dict[str, Any]: 选择题
        """
        # 随机选择一个概念作为正确答案
        correct_concept = random.choice(group["概念列表"])
        
        # 生成问题
        question_types = [
            f"{correct_concept['概念名称']}的正确定义是？",
            f"以下哪项是{correct_concept['概念名称']}的核心特征？",
            f"{correct_concept['定义']}描述的是哪个概念？",
            f"{correct_concept['核心特征']}属于哪个概念的特征？"
        ]
        question_text = random.choice(question_types)
        
        # 生成选项
        options = [correct_concept["概念名称"]]
        
        # 添加干扰选项
        all_concepts = [concept for g in self.concept_groups for concept in g["概念列表"] if concept != correct_concept]
        random.shuffle(all_concepts)
        
        for i in range(self.test_mode_configs["选择题"]["options_count"] - 1):
            if i < len(all_concepts):
                options.append(all_concepts[i]["概念名称"])
        
        # 随机化选项顺序
        if self.config["randomize_options"]:
            random.shuffle(options)
        
        # 确定正确选项索引
        correct_index = options.index(correct_concept["概念名称"])
        
        question = {
            "类型": "选择题",
            "题目": question_text,
            "选项": options,
            "正确答案": correct_concept["概念名称"],
            "正确选项索引": correct_index,
            "概念组": group,
            "相关概念": correct_concept,
            "分值": self.test_mode_configs["选择题"]["points_per_question"]
        }
        
        return question
    
    def _generate_true_false_question(self, group: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成判断题
        
        Args:
            group: 概念组
        
        Returns:
            Dict[str, Any]: 判断题
        """
        # 随机选择两个概念
        concept1, concept2 = random.sample(group["概念列表"], 2)
        
        # 生成真命题或假命题
        is_true = random.choice([True, False])
        
        if is_true:
            # 生成真命题
            question_text = f"{concept1['概念名称']}的核心特征是{concept1['核心特征']}"
            correct_answer = "正确"
        else:
            # 生成假命题
            question_text = f"{concept1['概念名称']}的核心特征是{concept2['核心特征']}"
            correct_answer = "错误"
        
        question = {
            "类型": "判断题",
            "题目": question_text,
            "正确答案": correct_answer,
            "概念组": group,
            "相关概念": [concept1, concept2],
            "分值": self.test_mode_configs["判断题"]["points_per_question"]
        }
        
        return question
    
    def _generate_fill_blank_question(self, group: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成填空题
        
        Args:
            group: 概念组
        
        Returns:
            Dict[str, Any]: 填空题
        """
        # 随机选择一个概念
        concept = random.choice(group["概念列表"])
        
        # 生成填空题
        question_patterns = [
            f"______的定义是{concept['定义']}",
            f"{concept['概念名称']}的核心特征是______",
            f"{concept['定义']}描述的概念是______",
            f"______的典型例子是{concept['典型例子']}"
        ]
        question_text = random.choice(question_patterns)
        
        question = {
            "类型": "填空题",
            "题目": question_text,
            "正确答案": concept["概念名称"],
            "概念组": group,
            "相关概念": concept,
            "分值": self.test_mode_configs["填空题"]["points_per_question"]
        }
        
        return question
    
    def check_answer(self, question: Dict[str, Any], user_answer: str) -> Dict[str, Any]:
        """
        检查答案
        
        Args:
            question: 题目
            user_answer: 用户答案
        
        Returns:
            Dict[str, Any]: 检查结果
        """
        is_correct = False
        feedback = ""
        
        if question["类型"] == "选择题":
            is_correct = user_answer == question["正确答案"]
        elif question["类型"] == "判断题":
            is_correct = user_answer == question["正确答案"]
        elif question["类型"] == "填空题":
            is_correct = user_answer.strip() == question["正确答案"]
        
        # 生成反馈
        if is_correct:
            feedback = "回答正确！"
        else:
            feedback = f"回答错误。正确答案：{question['正确答案']}"
        
        # 更新概念掌握情况
        self._update_concept_mastery(question, is_correct)
        
        # 生成结果
        result = {
            "题目": question,
            "用户答案": user_answer,
            "正确答案": question["正确答案"],
            "是否正确": is_correct,
            "反馈": feedback,
            "得分": question["分值"] if is_correct else 0,
            "测试时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return result
    
    def _update_concept_mastery(self, question: Dict[str, Any], is_correct: bool) -> None:
        """
        更新概念掌握情况
        
        Args:
            question: 题目
            is_correct: 是否正确
        """
        # 更新概念组测试次数
        question["概念组"]["测试次数"] += 1
        
        # 更新相关概念的掌握情况
        if "相关概念" in question:
            if isinstance(question["相关概念"], list):
                concepts = question["相关概念"]
            else:
                concepts = [question["相关概念"]]
            
            for concept in concepts:
                concept["测试次数"] += 1
                if is_correct:
                    concept["正确次数"] += 1
                else:
                    concept["错误次数"] += 1
                
                # 更新掌握程度
                mastery_rate = concept["正确次数"] / concept["测试次数"] if concept["测试次数"] > 0 else 0
                if mastery_rate >= 0.8:
                    concept["掌握程度"] = "已掌握"
                elif mastery_rate >= 0.4:
                    concept["掌握程度"] = "部分掌握"
                else:
                    concept["掌握程度"] = "未掌握"
                
                # 更新最近测试时间
                concept["最近测试时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def generate_memory_card(self, concept_group: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成记忆卡片
        
        Args:
            concept_group: 概念组
        
        Returns:
            Dict[str, Any]: 记忆卡片
        """
        card = {
            "组名": concept_group["组名"],
            "创建时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "概念卡片": [],
            "样式": self.config["memory_card_style"]
        }
        
        for concept in concept_group["概念列表"]:
            concept_card = {
                "概念名称": concept["概念名称"],
                "定义": concept["定义"],
                "核心特征": concept["核心特征"],
                "关键区别": concept["关键区别"],
                "记忆技巧": concept["记忆技巧"]
            }
            
            # 添加详细信息（如果样式为detailed）
            if self.config["memory_card_style"] == "detailed":
                concept_card["适用范围"] = concept["适用范围"]
                concept_card["典型例子"] = concept["典型例子"]
                concept_card["易混点"] = concept["易混点"]
            
            card["概念卡片"].append(concept_card)
        
        return card
    
    def get_weak_concepts(self) -> List[Dict[str, Any]]:
        """
        获取薄弱概念
        
        Returns:
            List[Dict[str, Any]]: 薄弱概念列表
        """
        weak_concepts = []
        
        for group in self.concept_groups:
            for concept in group["概念列表"]:
                if concept["掌握程度"] in ["未掌握", "部分掌握"] and concept["测试次数"] > 0:
                    # 计算错误率
                    error_rate = concept["错误次数"] / concept["测试次数"]
                    weak_concepts.append({
                        "概念": concept,
                        "概念组": group,
                        "错误率": error_rate,
                        "测试次数": concept["测试次数"]
                    })
        
        # 按错误率排序
        weak_concepts.sort(key=lambda x: x["错误率"], reverse=True)
        
        return weak_concepts
    
    def generate_analysis_report(self, test_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成分析报告
        
        Args:
            test_results: 测试结果列表
        
        Returns:
            Dict[str, Any]: 分析报告
        """
        if not test_results:
            return {"错误": "没有测试结果可以分析"}
        
        # 计算总分和得分
        total_points = sum(result["题目"]["分值"] for result in test_results)
        earned_points = sum(result["得分"] for result in test_results)
        score = int(earned_points / total_points * 100) if total_points > 0 else 0
        
        # 统计正确和错误数量
        correct_count = sum(1 for result in test_results if result["是否正确"])
        wrong_count = len(test_results) - correct_count
        
        # 按概念组统计错误
        error_by_group = Counter()
        for result in test_results:
            if not result["是否正确"]:
                group_name = result["题目"]["概念组"]["组名"]
                error_by_group[group_name] += 1
        
        # 生成报告
        report = {
            "测试时间": test_results[0]["测试时间"],
            "测试模式": test_results[0]["题目"]["类型"],
            "测试题数量": len(test_results),
            "总分": total_points,
            "得分": earned_points,
            "分数": score,
            "正确数量": correct_count,
            "错误数量": wrong_count,
            "正确率": round(correct_count / len(test_results) * 100, 1),
            "错误最多的概念组": error_by_group.most_common(),
            "薄弱概念": self.get_weak_concepts(),
            "改进建议": []
        }
        
        # 生成改进建议
        if score < 60:
            report["改进建议"].append("建议重点复习所有概念，尤其是错误率高的概念组")
        elif score < 80:
            report["改进建议"].append("建议加强薄弱概念的复习，多进行针对性练习")
        else:
            report["改进建议"].append("继续保持，建议定期进行复习巩固")
        
        if error_by_group:
            report["改进建议"].append(f"重点复习以下概念组：{', '.join([group[0] for group in error_by_group.most_common(3)])}")
        
        return report
    
    def export_concept_groups(self, file_path: str) -> bool:
        """
        导出概念组
        
        Args:
            file_path: 文件路径
        
        Returns:
            bool: 导出是否成功
        """
        try:
            DataIO.export_data(self.concept_groups, file_path, title="易混概念组")
            return True
        except Exception as e:
            print(f"导出概念组失败: {e}")
            return False
    
    def import_concept_groups(self, file_path: str) -> bool:
        """
        导入概念组
        
        Args:
            file_path: 文件路径
        
        Returns:
            bool: 导入是否成功
        """
        try:
            data = DataIO.import_data(file_path)
            if isinstance(data, list):
                for group in data:
                    if self.add_concept_group(group):
                        self.concept_groups.append(group)
                return True
            return False
        except Exception as e:
            print(f"导入概念组失败: {e}")
            return False
    
    def toggle_favorite(self, group_id: int) -> bool:
        """
        切换概念组收藏状态
        
        Args:
            group_id: 概念组索引
        
        Returns:
            bool: 操作是否成功
        """
        if 0 <= group_id < len(self.concept_groups):
            group = self.concept_groups[group_id]
            if group in self.favorite_concepts:
                self.favorite_concepts.remove(group)
            else:
                self.favorite_concepts.append(group)
            return True
        return False


class ConceptComparisonGUI(GUIApp):
    """易混概念对比工具GUI界面"""
    
    def __init__(self):
        """初始化GUI界面"""
        super().__init__("易混概念对比记忆工具", width=1200, height=800)
        self.tool = ConceptComparison()
        self.current_test = []
        self.current_question_index = 0
        self.test_results = []
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导入概念组", "command": self.import_concept_groups},
            {"label": "导出概念组", "command": self.export_concept_groups},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("概念组", [
            {"label": "添加概念组", "command": self.add_concept_group},
            {"label": "编辑概念组", "command": self.edit_concept_group},
            {"label": "删除概念组", "command": self.delete_concept_group},
            {"separator": True},
            {"label": "生成记忆卡片", "command": self.generate_memory_cards}
        ])
        
        self.add_menu("测试", [
            {"label": "开始测试", "command": self.start_test},
            {"label": "查看测试历史", "command": self.show_test_history},
            {"label": "查看薄弱概念", "command": self.show_weak_concepts}
        ])
    
    def create_main_frame(self):
        """创建主界面"""
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 顶部标题
        title_label = tk.Label(self.main_frame, text="易混概念对比记忆工具", font=(".SF NS Text", 16, "bold"))
        title_label.pack(pady=10)
        
        # 主内容区域
        content_frame = BaseFrame(self.main_frame, padding="10")
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧概念组列表
        left_frame = BaseFrame(content_frame, padding="10", width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        left_frame.pack_propagate(False)
        
        # 概念组列表
        left_frame.create_label("概念组列表", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        
        self.concept_listbox = tk.Listbox(left_frame, width=40, height=25)
        self.concept_listbox.grid(row=1, column=0, sticky="nsew")
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.concept_listbox.yview)
        self.concept_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")
        
        # 概念组操作按钮
        button_frame = BaseFrame(left_frame, padding="10")
        button_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        
        button_frame.create_button("添加概念组", self.add_concept_group, 0, 0, width=12)
        button_frame.create_button("编辑", self.edit_concept_group, 0, 1, width=8, padx=5)
        button_frame.create_button("删除", self.delete_concept_group, 0, 2, width=8)
        button_frame.create_button("收藏", self.toggle_favorite, 1, 0, width=12)
        button_frame.create_button("查看详情", self.view_concept_details, 1, 1, width=18, padx=5)
        
        # 右侧测试区域
        right_frame = BaseFrame(content_frame, padding="10")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 测试配置
        config_frame = BaseFrame(right_frame, padding="10")
        config_frame.pack(side=tk.TOP, fill=tk.X)
        
        # 测试模式
        config_frame.create_label("测试模式：", 0, 0, sticky="w")
        self.test_mode_var = tk.StringVar(value=self.tool.config["test_mode"])
        mode_combo = config_frame.create_combobox(["选择题", "判断题", "填空题"], 0, 1, width=15)
        mode_combo.config(textvariable=self.test_mode_var)
        
        # 概念数量
        config_frame.create_label("概念数量：", 0, 2, sticky="w", padx=20)
        self.concept_count_var = tk.IntVar(value=self.tool.config["concept_count"])
        count_entry = config_frame.create_entry(self.concept_count_var, 0, 3, width=10)
        
        # 难度选择
        config_frame.create_label("难度：", 0, 4, sticky="w", padx=20)
        self.difficulty_var = tk.StringVar(value=self.tool.config["difficulty"])
        difficulty_combo = config_frame.create_combobox(["全部", "简单", "中等", "困难"], 0, 5, width=10)
        difficulty_combo.config(textvariable=self.difficulty_var)
        
        # 测试范围
        config_frame.create_label("测试范围：", 1, 0, sticky="w", pady=10)
        self.test_scope_var = tk.StringVar(value=self.tool.config["test_scope"])
        scope_combo = config_frame.create_combobox(["全部", "收藏", "未掌握"], 1, 1, width=15)
        scope_combo.config(textvariable=self.test_scope_var)
        
        # 测试按钮
        test_button = config_frame.create_button("开始测试", self.start_test, 1, 2, width=15, padx=20)
        
        # 测试内容显示区域
        self.test_content_frame = BaseFrame(right_frame, padding="20")
        self.test_content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 初始化显示欢迎信息
        welcome_label = tk.Label(self.test_content_frame, text="欢迎使用易混概念对比记忆工具！\n\n选择一个概念组或开始测试。", font=(".SF NS Text", 14))
        welcome_label.pack(expand=True)
        
        # 更新概念组列表
        self.update_concept_list()
    
    def update_concept_list(self):
        """
        更新概念组列表
        """
        self.concept_listbox.delete(0, tk.END)
        
        for i, group in enumerate(self.tool.concept_groups):
            favorite_mark = "★ " if group in self.tool.favorite_concepts else "   "
            self.concept_listbox.insert(tk.END, f"{favorite_mark}{group['组名']} ({len(group['概念列表'])}个概念)")
    
    def add_concept_group(self):
        """
        添加概念组
        """
        MessageBox.info("提示", "该功能正在开发中")
    
    def edit_concept_group(self):
        """
        编辑概念组
        """
        MessageBox.info("提示", "该功能正在开发中")
    
    def delete_concept_group(self):
        """
        删除概念组
        """
        MessageBox.info("提示", "该功能正在开发中")
    
    def toggle_favorite(self):
        """
        切换收藏状态
        """
        selection = self.concept_listbox.curselection()
        if selection:
            index = selection[0]
            self.tool.toggle_favorite(index)
            self.update_concept_list()
    
    def view_concept_details(self):
        """
        查看概念详情
        """
        selection = self.concept_listbox.curselection()
        if not selection:
            MessageBox.warning("提示", "请先选择一个概念组")
            return
        
        index = selection[0]
        group = self.tool.concept_groups[index]
        
        # 创建详情窗口
        detail_window = tk.Toplevel(self.root)
        detail_window.title(f"概念组详情 - {group['组名']}")
        detail_window.geometry("700x500")
        
        detail_frame = BaseFrame(detail_window, padding="10")
        detail_frame.pack(fill=tk.BOTH, expand=True)
        
        # 概念组基本信息
        info_frame = BaseFrame(detail_frame, padding="10")
        info_frame.pack(side=tk.TOP, fill=tk.X)
        
        info_frame.create_label(f"组名：{group['组名']}", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        info_frame.create_label(f"分类：{group['分类']}", 1, 0, sticky="w")
        info_frame.create_label(f"难度：{group['难度']}", 2, 0, sticky="w")
        info_frame.create_label(f"概念数量：{len(group['概念列表'])}", 3, 0, sticky="w")
        
        # 概念列表
        concept_frame = BaseFrame(detail_frame, padding="10")
        concept_frame.pack(fill=tk.BOTH, expand=True)
        
        concept_frame.create_label("概念列表", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        
        # 创建表格显示概念
        columns = ("概念名称", "定义", "核心特征", "掌握程度")
        tree = ttk.Treeview(concept_frame, columns=columns, show="headings")
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)
        
        for concept in group["概念列表"]:
            tree.insert("", tk.END, values=(
                concept["概念名称"],
                concept["定义"],
                concept["核心特征"],
                concept["掌握程度"]
            ))
        
        tree.pack(fill=tk.BOTH, expand=True)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(concept_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def start_test(self):
        """
        开始测试
        """
        # 更新配置
        self.tool.config["test_mode"] = self.test_mode_var.get()
        self.tool.config["concept_count"] = self.concept_count_var.get()
        self.tool.config["difficulty"] = self.difficulty_var.get()
        self.tool.config["test_scope"] = self.test_scope_var.get()
        
        # 生成测试题
        self.current_test = self.tool.generate_test()
        if not self.current_test:
            MessageBox.warning("提示", "没有可测试的概念组")
            return
        
        self.current_question_index = 0
        self.test_results = []
        
        # 显示第一题
        self.show_question()
    
    def show_question(self):
        """
        显示当前题目
        """
        if self.current_question_index >= len(self.current_test):
            self.show_test_result()
            return
        
        # 清空测试内容区域
        for widget in self.test_content_frame.winfo_children():
            widget.destroy()
        
        question = self.current_test[self.current_question_index]
        
        # 显示题目信息
        question_label = tk.Label(self.test_content_frame, text=f"第 {self.current_question_index+1}/{len(self.current_test)} 题", font=(".SF NS Text", 14, "bold"))
        question_label.pack(pady=10)
        
        # 显示题目
        question_text = tk.Label(self.test_content_frame, text=question["题目"], font=(".SF NS Text", 12), wraplength=600)
        question_text.pack(pady=20)
        
        # 选项区域
        options_frame = BaseFrame(self.test_content_frame, padding="10")
        options_frame.pack(pady=10)
        
        # 根据测试类型显示不同的选项
        if question["类型"] == "选择题":
            self.answer_var = tk.StringVar()
            
            for i, option in enumerate(question["选项"]):
                radio = ttk.Radiobutton(options_frame, text=option, variable=self.answer_var, value=option)
                radio.pack(anchor=tk.W, pady=5)
        elif question["类型"] == "判断题":
            self.answer_var = tk.StringVar()
            
            true_radio = ttk.Radiobutton(options_frame, text="正确", variable=self.answer_var, value="正确")
            true_radio.pack(anchor=tk.W, pady=5)
            
            false_radio = ttk.Radiobutton(options_frame, text="错误", variable=self.answer_var, value="错误")
            false_radio.pack(anchor=tk.W, pady=5)
        elif question["类型"] == "填空题":
            self.answer_var = tk.StringVar()
            
            answer_frame = BaseFrame(options_frame, padding="5")
            answer_frame.pack()
            
            answer_frame.create_label("答案：", 0, 0, sticky="w")
            answer_entry = answer_frame.create_entry(self.answer_var, 0, 1, width=40)
            answer_entry.focus_set()
        
        # 按钮区域
        button_frame = BaseFrame(self.test_content_frame, padding="10")
        button_frame.pack(pady=20)
        
        submit_button = button_frame.create_button("提交答案", self.submit_answer, 0, 0, width=15)
        next_button = button_frame.create_button("下一题", lambda: self.next_question(True), 0, 1, width=15, padx=20)
        next_button.config(state=tk.DISABLED)
        
        self.submit_button = submit_button
        self.next_button = next_button
    
    def submit_answer(self):
        """
        提交答案
        """
        user_answer = self.answer_var.get().strip()
        if not user_answer:
            MessageBox.warning("提示", "请输入答案")
            return
        
        question = self.current_test[self.current_question_index]
        result = self.tool.check_answer(question, user_answer)
        
        # 保存结果
        self.test_results.append(result)
        
        # 显示结果
        self.show_answer_result(result)
        
        # 启用下一题按钮
        self.next_button.config(state=tk.NORMAL)
        self.submit_button.config(state=tk.DISABLED)
    
    def show_answer_result(self, result: Dict[str, Any]):
        """
        显示答案结果
        
        Args:
            result: 测试结果
        """
        # 创建结果标签
        result_label = tk.Label(
            self.test_content_frame,
            text=result["反馈"],
            font=(".SF NS Text", 12),
            fg="green" if result["是否正确"] else "red"
        )
        result_label.pack(pady=10)
    
    def next_question(self, is_submitted: bool = False):
        """
        进入下一题
        
        Args:
            is_submitted: 是否已提交答案
        """
        if not is_submitted and self.current_question_index < len(self.current_test):
            # 如果未提交答案，直接进入下一题
            self.current_question_index += 1
            self.show_question()
        elif is_submitted:
            # 如果已提交答案，进入下一题
            self.current_question_index += 1
            self.show_question()
    
    def show_test_result(self):
        """
        显示测试结果
        """
        # 清空测试内容区域
        for widget in self.test_content_frame.winfo_children():
            widget.destroy()
        
        # 生成分析报告
        report = self.tool.generate_analysis_report(self.test_results)
        
        # 显示测试结果
        result_label = tk.Label(self.test_content_frame, text="测试完成！", font=(".SF NS Text", 16, "bold"))
        result_label.pack(pady=20)
        
        # 结果详情
        result_frame = BaseFrame(self.test_content_frame, padding="10")
        result_frame.pack(pady=10)
        
        result_frame.create_label(f"测试模式：{report['测试模式']}", 0, 0, sticky="w")
        result_frame.create_label(f"测试题数量：{report['测试题数量']}", 1, 0, sticky="w")
        result_frame.create_label(f"总分：{report['总分']}", 2, 0, sticky="w")
        result_frame.create_label(f"得分：{report['得分']}", 3, 0, sticky="w")
        result_frame.create_label(f"分数：{report['分数']}分", 4, 0, sticky="w")
        result_frame.create_label(f"正确率：{report['正确率']}%", 5, 0, sticky="w")
        result_frame.create_label(f"正确数量：{report['正确数量']}，错误数量：{report['错误数量']}", 6, 0, sticky="w")
        
        # 错误最多的概念组
        if report["错误最多的概念组"]:
            result_frame.create_label("错误最多的概念组：", 7, 0, sticky="w", pady=10, font=(".SF NS Text", 11, "bold"))
            for i, (group_name, count) in enumerate(report["错误最多的概念组"], 1):
                result_frame.create_label(f"{i}. {group_name}：{count}次错误", 7+i, 0, sticky="w", padx=20)
        
        # 改进建议
        result_frame.create_label("改进建议：", 15, 0, sticky="w", pady=10, font=(".SF NS Text", 11, "bold"))
        for i, suggestion in enumerate(report["改进建议"], 1):
            result_frame.create_label(f"{i}. {suggestion}", 15+i, 0, sticky="w", padx=20, wraplength=500)
        
        # 操作按钮
        button_frame = BaseFrame(self.test_content_frame, padding="10")
        button_frame.pack(pady=20)
        
        button_frame.create_button("返回首页", self.create_main_frame, 0, 0, width=15)
        button_frame.create_button("重新测试", self.start_test, 0, 1, width=15, padx=20)
        button_frame.create_button("查看薄弱概念", self.show_weak_concepts, 0, 2, width=15)
    
    def show_weak_concepts(self):
        """
        显示薄弱概念
        """
        weak_concepts = self.tool.get_weak_concepts()
        
        # 创建薄弱概念窗口
        weak_window = tk.Toplevel(self.root)
        weak_window.title("薄弱概念列表")
        weak_window.geometry("800x600")
        
        weak_frame = BaseFrame(weak_window, padding="10")
        weak_frame.pack(fill=tk.BOTH, expand=True)
        
        weak_frame.create_label("薄弱概念列表", 0, 0, sticky="w", font=(".SF NS Text", 14, "bold"))
        
        # 创建表格
        columns = ("概念组", "概念名称", "错误率", "测试次数", "掌握程度")
        tree = ttk.Treeview(weak_frame, columns=columns, show="headings")
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)
        
        for item in weak_concepts:
            tree.insert("", tk.END, values=(
                item["概念组"]["组名"],
                item["概念"]["概念名称"],
                f"{item['错误率']:.2%}",
                item["测试次数"],
                item["概念"]["掌握程度"]
            ))
        
        tree.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(weak_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def add_concept_group(self):
        """
        添加概念组
        """
        # 创建添加概念组窗口
        add_window = tk.Toplevel(self.root)
        add_window.title("添加概念组")
        add_window.geometry("600x500")
        
        add_frame = BaseFrame(add_window, padding="10")
        add_frame.pack(fill=tk.BOTH, expand=True)
        
        # 组名
        add_frame.create_label("组名：", 0, 0, sticky="w")
        group_name_var = tk.StringVar()
        add_frame.create_entry(group_name_var, 0, 1, width=40)
        
        # 分类
        add_frame.create_label("分类：", 1, 0, sticky="w", pady=5)
        category_var = tk.StringVar()
        add_frame.create_entry(category_var, 1, 1, width=40)
        
        # 难度
        add_frame.create_label("难度：", 2, 0, sticky="w")
        difficulty_var = tk.StringVar(value="中等")
        difficulty_combo = add_frame.create_combobox(["简单", "中等", "困难"], 2, 1, width=15)
        difficulty_combo.config(textvariable=difficulty_var)
        
        # 概念列表
        add_frame.create_label("概念列表", 3, 0, sticky="w", pady=10, font=(".SF NS Text", 12, "bold"))
        
        concept_text = add_frame.create_text(3, 1, width=60, height=15, sticky="nsew")
        concept_text.insert(tk.END, "请输入概念列表，格式：概念1:定义1:核心特征1\n概念2:定义2:核心特征2")
        
        # 按钮
        button_frame = BaseFrame(add_window, padding="10")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        def save_group():
            """保存概念组"""
            group_name = group_name_var.get().strip()
            if not group_name:
                MessageBox.error("错误", "组名不能为空")
                return
            
            # 解析概念列表
            concept_list_text = concept_text.get("1.0", tk.END)
            concept_list = []
            
            for line in concept_list_text.strip().split("\n"):
                if line and not line.startswith("请输入"):
                    parts = line.split(":")
                    if len(parts) >= 3:
                        concept_list.append({
                            "概念名称": parts[0].strip(),
                            "定义": parts[1].strip(),
                            "核心特征": parts[2].strip()
                        })
            
            if not concept_list:
                MessageBox.error("错误", "请至少添加一个概念")
                return
            
            # 创建概念组
            group = {
                "组名": group_name,
                "分类": category_var.get().strip(),
                "难度": difficulty_var.get(),
                "概念列表": concept_list
            }
            
            # 添加概念组
            if self.tool.add_concept_group(group):
                MessageBox.info("成功", "概念组添加成功")
                self.update_concept_list()
                add_window.destroy()
            else:
                MessageBox.error("错误", "概念组添加失败")
        
        button_frame.create_button("保存", save_group, 0, 0, width=12)
        button_frame.create_button("取消", add_window.destroy, 0, 1, width=12, padx=10)
    
    def generate_memory_cards(self):
        """
        生成记忆卡片
        """
        selection = self.concept_listbox.curselection()
        if not selection:
            MessageBox.warning("提示", "请先选择一个概念组")
            return
        
        index = selection[0]
        group = self.tool.concept_groups[index]
        
        # 生成记忆卡片
        card = self.tool.generate_memory_card(group)
        
        # 创建记忆卡片窗口
        card_window = tk.Toplevel(self.root)
        card_window.title(f"记忆卡片 - {group['组名']}")
        card_window.geometry("800x600")
        
        card_frame = BaseFrame(card_window, padding="10")
        card_frame.pack(fill=tk.BOTH, expand=True)
        
        # 记忆卡片显示
        self.card_canvas = tk.Canvas(card_frame, bg="white", bd=2, relief="raised")
        self.card_canvas.pack(fill=tk.BOTH, expand=True, pady=20, padx=20)
        
        # 显示第一张卡片
        self.current_card_index = 0
        self.show_memory_card(card, self.current_card_index)
        
        # 卡片导航按钮
        nav_frame = BaseFrame(card_window, padding="10")
        nav_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        nav_frame.create_button("上一张", lambda: self.show_memory_card(card, self.current_card_index-1), 0, 0, width=12)
        nav_frame.create_button("下一张", lambda: self.show_memory_card(card, self.current_card_index+1), 0, 1, width=12, padx=20)
        nav_frame.create_button("导出卡片", lambda: self.export_memory_cards(card), 0, 2, width=12)
    
    def show_memory_card(self, card: Dict[str, Any], index: int):
        """
        显示记忆卡片
        
        Args:
            card: 记忆卡片数据
            index: 卡片索引
        """
        if index < 0 or index >= len(card["概念卡片"]):
            return
        
        self.current_card_index = index
        concept_card = card["概念卡片"][index]
        
        # 清空画布
        self.card_canvas.delete("all")
        
        # 绘制卡片内容
        width = self.card_canvas.winfo_width()
        height = self.card_canvas.winfo_height()
        
        # 绘制卡片边框
        self.card_canvas.create_rectangle(20, 20, width-20, height-20, outline="#333", width=2)
        
        # 绘制卡片标题
        title = f"{card['组名']} - 记忆卡片 {index+1}/{len(card['概念卡片'])}"
        self.card_canvas.create_text(width//2, 50, text=title, font=(".SF NS Text", 14, "bold"))
        
        # 绘制概念名称
        self.card_canvas.create_text(width//2, 100, text=concept_card["概念名称"], font=(".SF NS Text", 16, "bold"), fill="#2c3e50")
        
        # 绘制概念内容
        y_pos = 150
        line_height = 30
        
        self.card_canvas.create_text(50, y_pos, text="定义：", font=(".SF NS Text", 12, "bold"), anchor=tk.W)
        self.card_canvas.create_text(120, y_pos, text=concept_card["定义"], font=(".SF NS Text", 12), anchor=tk.W, width=width-140)
        y_pos += line_height
        
        self.card_canvas.create_text(50, y_pos, text="核心特征：", font=(".SF NS Text", 12, "bold"), anchor=tk.W)
        self.card_canvas.create_text(120, y_pos, text=concept_card["核心特征"], font=(".SF NS Text", 12), anchor=tk.W, width=width-140)
        y_pos += line_height
        
        if "关键区别" in concept_card and concept_card["关键区别"]:
            self.card_canvas.create_text(50, y_pos, text="关键区别：", font=(".SF NS Text", 12, "bold"), anchor=tk.W)
            self.card_canvas.create_text(120, y_pos, text=concept_card["关键区别"], font=(".SF NS Text", 12), anchor=tk.W, width=width-140)
            y_pos += line_height
        
        if "记忆技巧" in concept_card and concept_card["记忆技巧"]:
            self.card_canvas.create_text(50, y_pos, text="记忆技巧：", font=(".SF NS Text", 12, "bold"), anchor=tk.W)
            self.card_canvas.create_text(120, y_pos, text=concept_card["记忆技巧"], font=(".SF NS Text", 12, "italic"), anchor=tk.W, width=width-140, fill="#e74c3c")
        
        # 绑定窗口大小变化事件
        self.card_canvas.bind("<Configure>", lambda e: self.show_memory_card(card, index))
    
    def export_memory_cards(self, card: Dict[str, Any]):
        """
        导出记忆卡片
        
        Args:
            card: 记忆卡片数据
        """
        file_path = FileDialog.save_file(
            title="导出记忆卡片",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            DataIO.export_data([card], file_path, title=f"记忆卡片 - {card['组名']}")
            MessageBox.info("成功", f"记忆卡片已导出到 {file_path}")
    
    def import_concept_groups(self):
        """
        导入概念组
        """
        file_path = FileDialog.open_file(
            title="导入概念组",
            filetypes=[("Excel文件", "*.xlsx;*.xls"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        
        if file_path:
            if self.tool.import_concept_groups(file_path):
                MessageBox.info("成功", "概念组导入成功")
                self.update_concept_list()
            else:
                MessageBox.error("失败", "概念组导入失败")
    
    def export_concept_groups(self):
        """
        导出概念组
        """
        file_path = FileDialog.save_file(
            title="导出概念组",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            if self.tool.export_concept_groups(file_path):
                MessageBox.info("成功", f"概念组已导出到 {file_path}")
            else:
                MessageBox.error("失败", "概念组导出失败")


if __name__ == "__main__":
    app = ConceptComparisonGUI()
    app.run()