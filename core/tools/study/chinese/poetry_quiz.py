#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古诗文默写随机抽查器
支持TXT/Excel格式导入高考必背篇目，提供挖空测试、答案对比、易错字统计等功能
"""

import os
import random
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Tuple
from ..common.utils import compare_strings, highlight_errors, random_sample
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class PoetryQuiz:
    """古诗文默写抽查器类"""
    
    def __init__(self):
        """初始化古诗文默写抽查器"""
        self.poetry_list = []  # 古诗文列表
        self.current_quiz = []  # 当前测验题目
        self.user_answers = []  # 用户答案
        self.error_stats = {}  # 易错字统计
        self.wrong_questions = []  # 错题记录
        
        # 配置
        self.config = {
            "question_count": 20,
            "blank_mode": "keyword",  # keyword或sentence
            "keyword_ratio": 0.3  # 关键字挖空比例
        }
    
    def load_poetry(self, file_path: str) -> bool:
        """
        加载古诗文数据
        
        Args:
            file_path: 文件路径
        
        Returns:
            bool: 加载是否成功
        """
        try:
            data = DataIO.import_data(file_path)
            self.poetry_list = []
            
            for item in data:
                if isinstance(item, dict) and "content" in item:
                    # 解析诗句格式：诗句|作者|篇目
                    content = item["content"]
                    parts = content.split("|")
                    if len(parts) >= 3:
                        self.poetry_list.append({
                            "sentence": parts[0].strip(),
                            "author": parts[1].strip(),
                            "title": parts[2].strip()
                        })
                    elif len(parts) == 1:
                        # 仅诗句，无作者和篇目
                        self.poetry_list.append({
                            "sentence": parts[0].strip(),
                            "author": "",
                            "title": ""
                        })
            
            return len(self.poetry_list) > 0
        except Exception as e:
            print(f"加载失败: {e}")
            return False
    
    def generate_quiz(self) -> List[Dict[str, Any]]:
        """
        生成测验题目
        
        Returns:
            List[Dict[str, Any]]: 测验题目列表
        """
        if len(self.poetry_list) == 0:
            return []
        
        # 随机选择题目
        selected = random_sample(self.poetry_list, self.config["question_count"])
        self.current_quiz = []
        
        for poetry in selected:
            question = self._generate_question(poetry)
            self.current_quiz.append(question)
        
        return self.current_quiz
    
    def _generate_question(self, poetry: Dict[str, str]) -> Dict[str, Any]:
        """
        生成单个题目
        
        Args:
            poetry: 古诗文数据
        
        Returns:
            Dict[str, Any]: 题目数据
        """
        sentence = poetry["sentence"]
        
        if self.config["blank_mode"] == "keyword":
            # 关键字挖空
            blanked_sentence, blanks = self._generate_keyword_blanks(sentence)
        else:
            # 整句挖空
            blanked_sentence, blanks = self._generate_sentence_blanks(sentence)
        
        return {
            "original": sentence,
            "blanked": blanked_sentence,
            "blanks": blanks,
            "author": poetry["author"],
            "title": poetry["title"]
        }
    
    def _generate_keyword_blanks(self, sentence: str) -> Tuple[str, List[str]]:
        """
        生成关键字挖空
        
        Args:
            sentence: 原句
        
        Returns:
            Tuple[str, List[str]]: (挖空后的句子, 挖空的关键字列表)
        """
        # 简单关键字提取：跳过首尾字，选择中间字
        chars = list(sentence)
        if len(chars) <= 4:
            # 短句不挖空或只挖中间字
            mid = len(chars) // 2
            blanks = [chars[mid]]
            chars[mid] = "____"
            return "".join(chars), blanks
        
        # 计算需要挖空的字数
        blank_count = max(1, int(len(chars) * self.config["keyword_ratio"]))
        
        # 选择挖空位置（跳过首尾）
        positions = random.sample(range(1, len(chars)-1), blank_count)
        positions.sort()
        
        blanks = []
        blanked = []
        last_pos = 0
        
        for pos in positions:
            blanked.append("".join(chars[last_pos:pos]))
            blanked.append("____")
            blanks.append(chars[pos])
            last_pos = pos + 1
        
        blanked.append("".join(chars[last_pos:]))
        
        return "".join(blanked), blanks
    
    def _generate_sentence_blanks(self, sentence: str) -> Tuple[str, List[str]]:
        """
        生成整句挖空
        
        Args:
            sentence: 原句
        
        Returns:
            Tuple[str, List[str]]: (挖空后的句子, 原句)
        """
        return "____", [sentence]
    
    def check_answer(self, question: Dict[str, Any], user_answer: str) -> Dict[str, Any]:
        """
        检查答案
        
        Args:
            question: 题目数据
            user_answer: 用户答案
        
        Returns:
            Dict[str, Any]: 检查结果
        """
        original = question["original"]
        error_count, errors = compare_strings(original, user_answer)
        
        # 统计易错字
        for pos, correct_char, user_char in errors:
            if correct_char:
                self.error_stats[correct_char] = self.error_stats.get(correct_char, 0) + 1
        
        # 生成结果
        result = {
            "question": question,
            "user_answer": user_answer,
            "correct_answer": original,
            "error_count": error_count,
            "errors": errors,
            "highlighted": highlight_errors(original, user_answer),
            "is_correct": error_count == 0
        }
        
        # 记录错题
        if error_count > 0:
            self.wrong_questions.append(result)
        
        return result
    
    def get_error_stats(self) -> List[Tuple[str, int]]:
        """
        获取易错字统计
        
        Returns:
            List[Tuple[str, int]]: 易错字列表，按错误次数排序
        """
        return sorted(self.error_stats.items(), key=lambda x: x[1], reverse=True)
    
    def export_wrong_questions(self, file_path: str) -> bool:
        """
        导出错题本
        
        Args:
            file_path: 文件路径
        
        Returns:
            bool: 导出是否成功
        """
        try:
            # 准备导出数据
            export_data = []
            for i, wrong_q in enumerate(self.wrong_questions, 1):
                export_data.append({
                    "序号": i,
                    "题目": wrong_q["question"]["blanked"],
                    "用户答案": wrong_q["user_answer"],
                    "正确答案": wrong_q["correct_answer"],
                    "作者": wrong_q["question"]["author"],
                    "篇目": wrong_q["question"]["title"],
                    "错误数量": wrong_q["error_count"],
                    "错误详情": ", ".join([f"{pos+1}位：{correct}→{user}" for pos, correct, user in wrong_q["errors"]])
                })
            
            DataIO.export_data(export_data, file_path, title="古诗文默写错题本")
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False
    
    def clear_stats(self) -> None:
        """
        清空统计数据
        """
        self.error_stats = {}
        self.wrong_questions = []
    
    def set_config(self, config: Dict[str, Any]) -> None:
        """
        设置配置
        
        Args:
            config: 配置字典
        """
        self.config.update(config)
        
        # 确保题目数量在合理范围
        if "question_count" in config:
            self.config["question_count"] = max(10, min(50, self.config["question_count"]))
    
    def get_config(self) -> Dict[str, Any]:
        """
        获取配置
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return self.config.copy()


class PoetryQuizGUI(GUIApp):
    """古诗文默写抽查器GUI界面"""
    
    def __init__(self):
        """初始化GUI界面"""
        super().__init__("古诗文默写随机抽查器", width=900, height=600)
        self.quiz = PoetryQuiz()
        self.current_question_index = 0
        self.quiz_results = []
        
        # 创建主界面
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导入古诗文", "command": self.import_poetry},
            {"label": "导出错题本", "command": self.export_wrong_questions},
            {"separator": True},
            {"label": "清空统计", "command": self.clear_stats}
        ])
    
    def create_main_frame(self):
        """创建主界面"""
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 配置区域
        config_frame = BaseFrame(self.main_frame)
        config_frame.pack(fill=tk.X, pady=10)
        
        # 题目数量
        config_frame.create_label("题目数量：", 0, 0, sticky="w")
        self.question_count_var = tk.StringVar(value=str(self.quiz.get_config()["question_count"]))
        question_count_entry = config_frame.create_entry(0, 1, width=10)
        question_count_entry.config(textvariable=self.question_count_var)
        
        # 挖空模式
        config_frame.create_label("挖空模式：", 0, 2, sticky="w", padx=20)
        self.blank_mode_var = tk.StringVar(value=self.quiz.get_config()["blank_mode"])
        keyword_radio = config_frame.create_radiobutton("关键字挖空", self.blank_mode_var, "keyword", 0, 3, sticky="w")
        sentence_radio = config_frame.create_radiobutton("整句挖空", self.blank_mode_var, "sentence", 0, 4, sticky="w")
        
        # 操作按钮
        self.start_button = config_frame.create_button("开始抽查", self.start_quiz, 0, 5, sticky="e", padx=20)
        self.import_button = config_frame.create_button("导入篇目", self.import_poetry, 0, 6, sticky="e")
        
        # 状态显示
        status_frame = BaseFrame(self.main_frame)
        status_frame.pack(fill=tk.X, pady=5)
        
        self.status_label = status_frame.create_label(
            f"已加载 {len(self.quiz.poetry_list)} 条古诗文", 
            0, 0, 
            sticky="w"
        )
        
        # 测验区域
        quiz_frame = BaseFrame(self.main_frame)
        quiz_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 题目显示
        self.question_label = quiz_frame.create_label("", 0, 0, columnspan=2, sticky="nsew")
        self.question_label.config(font=(".SF NS Text", 16), wraplength=800, justify=tk.CENTER)
        
        # 作者和篇目
        self.info_label = quiz_frame.create_label("", 1, 0, columnspan=2, sticky="nsew")
        self.info_label.config(font=(".SF NS Text", 12), wraplength=800, justify=tk.CENTER, foreground="#666666")
        
        # 答案输入
        quiz_frame.create_label("请输入答案：", 2, 0, sticky="w", pady=10)
        self.answer_entry = quiz_frame.create_text(3, 0, columnspan=2, width=80, height=5, sticky="nsew")
        
        # 按钮区域
        button_frame = BaseFrame(self.main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        self.prev_button = button_frame.create_button("上一题", self.prev_question, 0, 0, sticky="ew")
        self.prev_button.config(state=tk.DISABLED)
        
        self.submit_button = button_frame.create_button("提交答案", self.submit_answer, 0, 1, sticky="ew", padx=10)
        
        self.next_button = button_frame.create_button("下一题", self.next_question, 0, 2, sticky="ew")
        self.next_button.config(state=tk.DISABLED)
        
        self.analysis_button = button_frame.create_button("查看解析", self.show_analysis, 0, 3, sticky="ew", padx=10)
        self.analysis_button.config(state=tk.DISABLED)
        
        # 结果显示区域
        result_frame = BaseFrame(self.main_frame)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.result_text = result_frame.create_text(0, 0, columnspan=2, width=80, height=10, sticky="nsew")
        
        # 滚动条配置
        quiz_frame.columnconfigure(0, weight=1)
        quiz_frame.rowconfigure(3, weight=1)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
    
    def import_poetry(self):
        """
        导入古诗文文件
        """
        file_path = FileDialog.open_file(
            title="导入古诗文篇目",
            filetypes=[("文本文件", "*.txt"), ("Excel文件", "*.xlsx;*.xls"), ("所有文件", "*.*")]
        )
        
        if file_path:
            if self.quiz.load_poetry(file_path):
                MessageBox.info("成功", f"成功导入 {len(self.quiz.poetry_list)} 条古诗文")
                self.status_label.config(text=f"已加载 {len(self.quiz.poetry_list)} 条古诗文")
            else:
                MessageBox.error("失败", "导入失败，请检查文件格式")
    
    def start_quiz(self):
        """
        开始抽查
        """
        if len(self.quiz.poetry_list) == 0:
            MessageBox.warning("提示", "请先导入古诗文篇目")
            return
        
        # 更新配置
        self.quiz.set_config({
            "question_count": int(self.question_count_var.get()),
            "blank_mode": self.blank_mode_var.get()
        })
        
        # 生成测验
        self.quiz.generate_quiz()
        self.current_question_index = 0
        self.quiz_results = []
        
        # 显示第一题
        self.show_current_question()
        
        # 更新按钮状态
        self.start_button.config(state=tk.DISABLED)
        self.submit_button.config(state=tk.NORMAL)
        self.next_button.config(state=tk.NORMAL if len(self.quiz.current_quiz) > 1 else tk.DISABLED)
        self.analysis_button.config(state=tk.DISABLED)
        
        MessageBox.info("开始", f"共 {len(self.quiz.current_quiz)} 道题，开始抽查！")
    
    def show_current_question(self):
        """
        显示当前题目
        """
        if self.current_question_index < 0 or self.current_question_index >= len(self.quiz.current_quiz):
            return
        
        question = self.quiz.current_quiz[self.current_question_index]
        
        # 显示题目
        self.question_label.config(
            text=f"第 {self.current_question_index+1}/{len(self.quiz.current_quiz)} 题：\n{question['blanked']}"
        )
        
        # 显示作者和篇目
        info = []
        if question["author"]:
            info.append(f"作者：{question['author']}")
        if question["title"]:
            info.append(f"篇目：{question['title']}")
        self.info_label.config(text=" | ".join(info))
        
        # 清空答案输入
        self.answer_entry.delete("1.0", tk.END)
        
        # 清空结果显示
        self.result_text.delete("1.0", tk.END)
    
    def submit_answer(self):
        """
        提交答案
        """
        user_answer = self.answer_entry.get("1.0", tk.END).strip()
        if not user_answer:
            MessageBox.warning("提示", "请输入答案")
            return
        
        question = self.quiz.current_quiz[self.current_question_index]
        result = self.quiz.check_answer(question, user_answer)
        
        # 保存结果
        self.quiz_results.append(result)
        
        # 显示结果
        self.show_result(result)
        
        # 更新按钮状态
        self.submit_button.config(state=tk.DISABLED)
        self.analysis_button.config(state=tk.NORMAL)
        
        # 如果是最后一题，显示完成信息
        if self.current_question_index == len(self.quiz.current_quiz) - 1:
            self.show_quiz_complete()
    
    def show_result(self, result: Dict[str, Any]):
        """
        显示答案检查结果
        
        Args:
            result: 检查结果
        """
        self.result_text.delete("1.0", tk.END)
        
        if result["is_correct"]:
            self.result_text.insert(tk.END, "✓ 回答正确！\n\n", "correct")
        else:
            self.result_text.insert(tk.END, f"✗ 回答错误，共 {result['error_count']} 处错误\n\n", "error")
        
        self.result_text.insert(tk.END, f"正确答案：{result['correct_answer']}\n\n")
        self.result_text.insert(tk.END, f"你的答案：{result['highlighted']}\n\n")
        
        # 配置文本样式
        self.result_text.tag_config("correct", foreground="green", font=(".SF NS Text", 12, "bold"))
        self.result_text.tag_config("error", foreground="red", font=(".SF NS Text", 12, "bold"))
    
    def show_analysis(self):
        """
        查看详细解析
        """
        if self.current_question_index < 0 or self.current_question_index >= len(self.quiz_results):
            return
        
        result = self.quiz_results[self.current_question_index]
        
        # 显示解析
        analysis = f"详细解析：\n\n"
        analysis += f"题目：{result['question']['blanked']}\n"
        analysis += f"正确答案：{result['correct_answer']}\n"
        analysis += f"你的答案：{result['user_answer']}\n\n"
        
        if result['errors']:
            analysis += "错误详情：\n"
            for pos, correct, user in result['errors']:
                analysis += f"第 {pos+1} 位：应该是 '{correct}'，你写了 '{user}'\n"
        
        MessageBox.info("解析", analysis)
    
    def prev_question(self):
        """
        上一题
        """
        if self.current_question_index > 0:
            self.current_question_index -= 1
            self.show_current_question()
            
            # 更新按钮状态
            self.prev_button.config(state=tk.DISABLED if self.current_question_index == 0 else tk.NORMAL)
            self.next_button.config(state=tk.NORMAL)
            
            # 恢复按钮状态
            if self.current_question_index < len(self.quiz_results):
                self.submit_button.config(state=tk.DISABLED)
                self.analysis_button.config(state=tk.NORMAL)
            else:
                self.submit_button.config(state=tk.NORMAL)
                self.analysis_button.config(state=tk.DISABLED)
    
    def next_question(self):
        """
        下一题
        """
        if self.current_question_index < len(self.quiz.current_quiz) - 1:
            self.current_question_index += 1
            self.show_current_question()
            
            # 更新按钮状态
            self.prev_button.config(state=tk.NORMAL)
            self.next_button.config(state=tk.DISABLED if self.current_question_index == len(self.quiz.current_quiz) - 1 else tk.NORMAL)
            
            # 恢复按钮状态
            if self.current_question_index < len(self.quiz_results):
                self.submit_button.config(state=tk.DISABLED)
                self.analysis_button.config(state=tk.NORMAL)
            else:
                self.submit_button.config(state=tk.NORMAL)
                self.analysis_button.config(state=tk.DISABLED)
    
    def show_quiz_complete(self):
        """
        显示测验完成信息
        """
        # 计算得分
        correct_count = sum(1 for result in self.quiz_results if result["is_correct"])
        total_count = len(self.quiz_results)
        score = int(correct_count / total_count * 100)
        
        # 显示统计信息
        stats = f"测验完成！\n\n"
        stats += f"共 {total_count} 题，答对 {correct_count} 题，得分 {score} 分\n\n"
        
        # 显示易错字
        error_chars = self.quiz.get_error_stats()
        if error_chars:
            stats += "易错字统计（按错误次数排序）：\n"
            for char, count in error_chars[:10]:
                stats += f"{char}：{count} 次\n"
        
        MessageBox.info("完成", stats)
        
        # 恢复按钮状态
        self.start_button.config(state=tk.NORMAL)
    
    def export_wrong_questions(self):
        """
        导出错题本
        """
        if len(self.quiz.wrong_questions) == 0:
            MessageBox.warning("提示", "没有错题记录")
            return
        
        # 选择保存路径
        file_path = FileDialog.save_file(
            title="导出错题本",
            defaultextension=".docx",
            filetypes=[("Word文件", "*.docx"), ("PDF文件", "*.pdf"), ("Excel文件", "*.xlsx"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            if self.quiz.export_wrong_questions(file_path):
                MessageBox.info("成功", f"成功导出 {len(self.quiz.wrong_questions)} 道错题")
            else:
                MessageBox.error("失败", "导出失败")
    
    def clear_stats(self):
        """
        清空统计数据
        """
        if MessageBox.question("确认", "确定要清空所有统计数据吗？"):
            self.quiz.clear_stats()
            MessageBox.info("成功", "统计数据已清空")


if __name__ == "__main__":
    # 测试代码
    app = PoetryQuizGUI()
    app.run()
