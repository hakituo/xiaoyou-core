#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英语高频词汇随机测试器 (GUI Frontend)
Unified with VocabularyManager backend.
"""

import os
import random
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta

# Try relative imports (package mode) or absolute imports (script mode)
try:
    from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog
    from .vocabulary_manager import VocabularyManager
except ImportError:
    # Fallback for direct execution if needed, but usually run from root
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from core.tools.study.common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog
    from core.tools.study.english.vocabulary_manager import VocabularyManager

class VocabTesterAdapter:
    """
    Adapter to make VocabularyManager compatible with the GUI's expectations.
    """
    def __init__(self):
        self.vm = VocabularyManager()
        self.config = {
            "test_mode": "看词选义",
            "test_range": "全词表", # Mapped to source="all"
            "word_count": 20,
            "unit": "", # Not supported in new backend yet, ignored
            "allow_spelling_error": True, # Handled by backend check_answer logic mostly
            "spelling_error_tolerance": 1
        }
        
    @property
    def vocab_list(self):
        return self.vm.dictionary

    def load_vocab(self, file_path: str) -> bool:
        count = self.vm.import_from_file(file_path)
        return count > 0 or len(self.vm.dictionary) > 0

    def generate_test(self) -> List[Dict[str, Any]]:
        source = "all"
        if self.config["test_range"] == "薄弱词":
            source = "weak"
        
        # Map GUI mode to backend mode
        mode_map = {
            "看词选义": "multiple_choice",
            "看义写词": "dictation", 
            "听写填空": "dictation" # Fallback
        }
        backend_mode = mode_map.get(self.config["test_mode"], "multiple_choice")
        
        questions = self.vm.generate_quiz(
            mode=backend_mode,
            count=int(self.config["word_count"]),
            source=source
        )
        
        # Adapt to GUI format
        gui_questions = []
        for q in questions:
            gui_q = {
                "类型": self.config["test_mode"],
                "单词": q["word_data"]["word"],
                "音标": "", # Backend might not have it loaded from simple files
                "正确答案": q["answer"],
                "词汇数据": {
                    "单词": q["word_data"]["word"],
                    "中文释义": q["answer"],
                    "单元": "",
                    "掌握程度": q["word_data"].get("status", "new")
                }
            }
            
            if backend_mode == "multiple_choice":
                gui_q["选项"] = q["options"]
                
            gui_questions.append(gui_q)
            
        return gui_questions

    def check_answer(self, question: Dict[str, Any], user_answer: str) -> Dict[str, Any]:
        # Reconstruct backend question format
        backend_q = {
            "type": "multiple_choice" if "选项" in question else "dictation",
            "answer": question["正确答案"],
            "word_data": {"word": question["单词"]}
        }
        
        result = self.vm.check_quiz_answer(backend_q, user_answer)
        
        return {
            "题目": question,
            "用户答案": user_answer,
            "正确答案": result["correct_answer"],
            "是否正确": result["is_correct"],
            "错误信息": "" if result["is_correct"] else f"正确答案: {result['correct_answer']}",
            "测试时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def get_weak_words(self) -> List[Dict[str, Any]]:
        # Adapt backend weak words to GUI format
        weak = self.vm.get_weak_words(limit=100)
        return [
            {
                "单词": w["word"],
                "中文释义": "; ".join([t["translation"] for t in w.get("translations", [])]),
                "错误次数": w.get("stats", {}).get("reps", 0), # Not exactly error count, but proxy
                "掌握程度": "薄弱"
            }
            for w in weak
        ]

    def generate_memory_curve(self) -> Dict[str, Any]:
        data = self.vm.get_memory_curve_data()
        return {
            "总词汇数": data["stats"]["total_words"],
            "已掌握词汇": data["stats"]["mastered_words"],
            "薄弱词汇": data["stats"]["due_words"], # Using due as weak proxy for summary
            "平均错误率": 0, # Not tracked
            "复习建议": [
                {
                    "单词": item["word"],
                    "下次复习时间": item["next_review"],
                    "错误次数": 0
                }
                for item in data["review_advice"]
            ]
        }
        
    def reset_weak_words(self) -> bool:
        # Not supported in SM-2 directly without resetting everything
        # Maybe just reset due times?
        return True

    def get_units(self) -> List[str]:
        return []

    def set_config(self, config: Dict[str, Any]) -> None:
        self.config.update(config)

    def get_config(self) -> Dict[str, Any]:
        return self.config.copy()


class VocabTesterGUI(GUIApp):
    """高频词汇测试器GUI界面"""
    
    def __init__(self):
        super().__init__("英语高频词汇随机测试器 (Unified)", width=900, height=600)
        self.tester = VocabTesterAdapter()
        self.current_test = []
        self.current_question_index = 0
        self.test_results = []
        
        self.test_modes = ["看词选义", "看义写词"] # Reduced modes
        
        self.create_main_frame()
        
        self.add_menu("文件", [
            {"label": "导入词汇表", "command": self.import_vocab},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("测试", [
            {"label": "开始测试", "command": self.start_test},
            {"label": "查看记忆曲线", "command": self.show_memory_curve}
        ])

    def create_main_frame(self):
        # Clear frame
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # Config Frame
        config_frame = BaseFrame(self.main_frame, padding="10")
        config_frame.pack(side=tk.TOP, fill=tk.X)
        
        # Mode
        config_frame.create_label("测试模式：", 0, 0, sticky="w", pady=5)
        self.mode_var = tk.StringVar(value=self.tester.config["test_mode"])
        mode_combo = config_frame.create_combobox(self.test_modes, 0, 1, width=20)
        mode_combo.config(textvariable=self.mode_var)
        
        # Range
        config_frame.create_label("测试范围：", 0, 2, sticky="w", padx=20)
        self.range_var = tk.StringVar(value=self.tester.config["test_range"])
        range_combo = config_frame.create_combobox(["全词表", "薄弱词"], 0, 3, width=15)
        range_combo.config(textvariable=self.range_var)
        
        # Count
        config_frame.create_label("题量：", 0, 4, sticky="w", padx=20)
        self.count_var = tk.StringVar(value=str(self.tester.config["word_count"]))
        count_entry = config_frame.create_entry(0, 5, width=10)
        count_entry.config(textvariable=self.count_var)
        
        # Buttons
        self.import_button = config_frame.create_button("导入新词", self.import_vocab, 1, 0, sticky="w", padx=10)
        self.start_button = config_frame.create_button("开始测试", self.start_test, 1, 1, sticky="w", padx=10)
        self.memory_curve_button = config_frame.create_button("记忆曲线", self.show_memory_curve, 1, 2, sticky="w", padx=10)
        
        # Status
        self.status_var = tk.StringVar(value=f"词库总量: {len(self.tester.vocab_list)}")
        status_label = config_frame.create_label(self.status_var.get(), 1, 3, columnspan=3, sticky="w", padx=20)
        status_label.config(textvariable=self.status_var)
        
        # Test Area
        self.test_frame = BaseFrame(self.main_frame, padding="10")
        self.test_frame.pack(fill=tk.BOTH, expand=True)
        
        self.question_label = self.test_frame.create_label("请点击开始测试", 0, 0, sticky="nsew", font=("Arial", 14))
        self.question_label.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=20)
        
        self.options_frame = BaseFrame(self.test_frame, padding="5")
        self.options_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        
        self.answer_frame = BaseFrame(self.test_frame, padding="5")
        self.answer_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=20)
        
        self.answer_label = self.answer_frame.create_label("答案：", 0, 0, sticky="w")
        self.answer_var = tk.StringVar(value="")
        self.answer_entry = self.answer_frame.create_entry(0, 1, width=50)
        self.answer_entry.config(textvariable=self.answer_var)
        
        self.submit_button = self.answer_frame.create_button("提交答案", self.submit_answer, 0, 2, sticky="w", padx=10)
        self.submit_button.config(state=tk.DISABLED)
        
        self.result_text = self.test_frame.create_text(3, 0, columnspan=2, width=80, height=15, sticky="nsew")

    def import_vocab(self):
        file_path = FileDialog.open_file(title="导入词汇表", filetypes=[("Excel/Text", "*.xlsx;*.xls;*.txt"), ("All", "*.*")])
        if file_path:
            if self.tester.load_vocab(file_path):
                MessageBox.info("成功", "导入成功并已合并到主词库")
                self.status_var.set(f"词库总量: {len(self.tester.vocab_list)}")
            else:
                MessageBox.error("失败", "导入失败")

    def start_test(self):
        if not self.tester.vocab_list:
            MessageBox.warning("提示", "词库为空，请先导入")
            return
            
        self.tester.set_config({
            "test_mode": self.mode_var.get(),
            "test_range": self.range_var.get(),
            "word_count": int(self.count_var.get())
        })
        
        self.current_test = self.tester.generate_test()
        if not self.current_test:
            MessageBox.info("提示", "没有符合条件的单词")
            return
            
        self.current_question_index = 0
        self.test_results = []
        self.result_text.delete("1.0", tk.END)
        self.show_question()

    def show_question(self):
        if self.current_question_index >= len(self.current_test):
            self.show_summary()
            return
            
        question = self.current_test[self.current_question_index]
        
        # Display question
        q_text = f"第 {self.current_question_index + 1}/{len(self.current_test)} 题\n\n"
        if question["类型"] == "看词选义":
            q_text += f"单词：{question['单词']}"
        else:
            q_text += f"释义：{question['正确答案']}" # Actually for '看义写词' answer is word, question is meaning
            if question["类型"] == "看义写词":
                 q_text = f"第 {self.current_question_index + 1}/{len(self.current_test)} 题\n\n释义：{question['词汇数据']['中文释义']}"
            
        self.question_label.config(text=q_text)
        
        # Clear options
        for widget in self.options_frame.winfo_children():
            widget.destroy()
            
        self.answer_var.set("")
        self.submit_button.config(state=tk.NORMAL)
        
        if question.get("选项"):
            # Multiple choice buttons
            for i, opt in enumerate(question["选项"]):
                btn = ttk.Button(self.options_frame, text=f"{chr(65+i)}. {opt}", 
                               command=lambda o=opt: self.select_option(o))
                btn.pack(fill=tk.X, pady=2)
            self.answer_frame.grid_remove() # Hide text entry for MC
            self.options_frame.grid()
        else:
            self.options_frame.grid_remove()
            self.answer_frame.grid()
            self.answer_entry.focus_set()

    def select_option(self, option):
        self.submit_answer(option)

    def submit_answer(self, answer=None):
        if answer is None:
            answer = self.answer_var.get()
            
        question = self.current_test[self.current_question_index]
        result = self.tester.check_answer(question, answer)
        self.test_results.append(result)
        
        # Show immediate feedback
        if not result["是否正确"]:
            MessageBox.warning("错误", f"回答错误！\n正确答案：{result['正确答案']}")
        
        self.current_question_index += 1
        self.show_question()

    def show_summary(self):
        correct_count = sum(1 for r in self.test_results if r["是否正确"])
        score = int(correct_count / len(self.test_results) * 100)
        
        summary = f"测试结束！\n得分：{score}\n"
        summary += f"共 {len(self.test_results)} 题，对 {correct_count} 题，错 {len(self.test_results) - correct_count} 题\n\n"
        summary += "详细记录：\n"
        
        for i, res in enumerate(self.test_results):
            status = "✅" if res["是否正确"] else "❌"
            summary += f"{i+1}. {status} {res['题目']['单词']} -> {res['用户答案']}\n"
            if not res["是否正确"]:
                summary += f"   正确答案：{res['正确答案']}\n"
                
        self.result_text.insert(tk.END, summary)
        self.question_label.config(text=f"测试结束 - 得分 {score}")
        self.submit_button.config(state=tk.DISABLED)

    def show_memory_curve(self):
        data = self.tester.generate_memory_curve()
        info = f"总词汇：{data['总词汇数']}\n已掌握：{data['已掌握词汇']}\n待复习：{data['薄弱词汇']}\n\n复习建议：\n"
        for item in data['复习建议'][:10]:
            info += f"{item['单词']}: {item['下次复习时间']}\n"
        MessageBox.info("记忆状态", info)

if __name__ == "__main__":
    app = VocabTesterGUI()
    app.mainloop()
