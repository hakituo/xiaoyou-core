#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
遗传概率自动计算器
支持单基因/双基因/三基因遗传交叉计算
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
from datetime import datetime
import random

# 导入公共模块
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class GeneticsCalculator:
    """遗传概率自动计算器"""
    
    def __init__(self):
        """初始化遗传计算器"""
        self.config = {
            "gene_count": 1,  # 基因数量：1-3
            "dominant_symbol": "A",  # 显性基因符号
            "recessive_symbol": "a",  # 隐性基因符号
            "show_chessboard": True,  # 是否显示棋盘图
            "show_calculation_steps": True,  # 是否显示计算步骤
            "show_ratio": True,  # 是否显示比例
            "export_format": "xlsx",  # 导出格式
            "font_size": 12,  # 字体大小
        }
        
        # 计算历史记录
        self.calculation_history = []
    
    def validate_genotype(self, genotype: str, gene_count: int) -> bool:
        """
        验证基因型格式是否正确
        
        Args:
            genotype: 基因型字符串
            gene_count: 基因数量
        
        Returns:
            bool: 基因型是否有效
        """
        try:
            # 移除空格
            genotype = genotype.strip().replace(" ", "")
            
            # 检查基因型长度
            if len(genotype) != gene_count * 2:
                return False
            
            # 检查每对基因是否由相同字母组成（大小写不同）
            for i in range(0, len(genotype), 2):
                gene_pair = genotype[i:i+2]
                if gene_pair[0].lower() != gene_pair[1].lower():
                    return False
            
            # 检查是否包含相同基因的不同字母
            genes = set()
            for i in range(0, len(genotype), 2):
                gene = genotype[i].lower()
                if gene in genes:
                    return False
                genes.add(gene)
            
            return True
        except Exception:
            return False
    
    def get_gametes(self, genotype: str, gene_count: int) -> List[str]:
        """
        生成配子组合
        
        Args:
            genotype: 亲本基因型
            gene_count: 基因数量
        
        Returns:
            List[str]: 配子组合列表
        """
        genotype = genotype.strip().replace(" ", "")
        
        # 分离每对基因
        gene_pairs = [genotype[i:i+2] for i in range(0, len(genotype), 2)]
        
        # 生成所有可能的配子
        gametes = [""]
        for gene_pair in gene_pairs:
            new_gametes = []
            for gamete in gametes:
                for gene in gene_pair:
                    new_gametes.append(gamete + gene)
            gametes = new_gametes
        
        # 去除重复的配子
        unique_gametes = list(set(gametes))
        
        return unique_gametes
    
    def calculate_offspring(self, parent1: str, parent2: str, gene_count: int) -> Dict[str, Any]:
        """
        计算子代基因型和表现型
        
        Args:
            parent1: 父本基因型
            parent2: 母本基因型
            gene_count: 基因数量
        
        Returns:
            Dict[str, Any]: 计算结果
        """
        # 验证基因型
        if not self.validate_genotype(parent1, gene_count):
            raise ValueError(f"父本基因型格式错误: {parent1}")
        if not self.validate_genotype(parent2, gene_count):
            raise ValueError(f"母本基因型格式错误: {parent2}")
        
        # 生成配子
        gametes1 = self.get_gametes(parent1, gene_count)
        gametes2 = self.get_gametes(parent2, gene_count)
        
        # 生成棋盘图
        chessboard = []
        offspring_genotypes = []
        
        for gamete1 in gametes1:
            row = []
            for gamete2 in gametes2:
                # 组合配子生成子代基因型
                offspring = "".join(["" + a + b for a, b in zip(gamete1, gamete2)])
                row.append(offspring)
                offspring_genotypes.append(offspring)
            chessboard.append(row)
        
        # 计算基因型比例
        genotype_counts = Counter(offspring_genotypes)
        total = len(offspring_genotypes)
        genotype_ratios = {gt: count/total for gt, count in genotype_counts.items()}
        
        # 计算表现型
        phenotypes = []
        for genotype in offspring_genotypes:
            # 表现型由显性基因决定
            phenotype = ""
            for i in range(0, len(genotype), 2):
                gene_pair = genotype[i:i+2]
                # 如果有大写字母，表现为显性
                if any(gene.isupper() for gene in gene_pair):
                    phenotype += gene_pair[0].upper()
                else:
                    phenotype += gene_pair[0].lower()
            phenotypes.append(phenotype)
        
        # 计算表现型比例
        phenotype_counts = Counter(phenotypes)
        phenotype_ratios = {pt: count/total for pt, count in phenotype_counts.items()}
        
        # 计算纯合子和杂合子比例
        homozygous = 0
        heterozygous = 0
        
        for genotype in offspring_genotypes:
            is_homozygous = True
            for i in range(0, len(genotype), 2):
                gene_pair = genotype[i:i+2]
                if gene_pair[0] != gene_pair[1]:
                    is_homozygous = False
                    break
            
            if is_homozygous:
                homozygous += 1
            else:
                heterozygous += 1
        
        homozygous_ratio = homozygous / total
        heterozygous_ratio = heterozygous / total
        
        # 生成计算步骤
        calculation_steps = [
            f"1. 确定亲本基因型：父本 {parent1}，母本 {parent2}",
            f"2. 生成配子：",
            f"   - 父本配子：{', '.join(gametes1)}",
            f"   - 母本配子：{', '.join(gametes2)}",
            f"3. 构建棋盘图：",
            f"   - 配子组合数：{len(gametes1)} × {len(gametes2)} = {total}",
            f"4. 计算基因型比例：",
            f"   - 基因型总数：{total}",
        ]
        
        for gt, ratio in genotype_ratios.items():
            calculation_steps.append(f"   - {gt}: {int(ratio*100)}% ({genotype_counts[gt]}/{total})")
        
        calculation_steps.append(f"5. 计算表现型比例：")
        for pt, ratio in phenotype_ratios.items():
            calculation_steps.append(f"   - {pt}: {int(ratio*100)}% ({phenotype_counts[pt]}/{total})")
        
        calculation_steps.append(f"6. 计算纯合子/杂合子比例：")
        calculation_steps.append(f"   - 纯合子：{int(homozygous_ratio*100)}% ({homozygous}/{total})")
        calculation_steps.append(f"   - 杂合子：{int(heterozygous_ratio*100)}% ({heterozygous}/{total})")
        
        # 生成结果
        result = {
            "计算时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "基因数量": gene_count,
            "父本基因型": parent1,
            "母本基因型": parent2,
            "父本配子": gametes1,
            "母本配子": gametes2,
            "棋盘图": chessboard,
            "子代基因型": offspring_genotypes,
            "基因型比例": genotype_ratios,
            "表现型": phenotypes,
            "表现型比例": phenotype_ratios,
            "纯合子比例": homozygous_ratio,
            "杂合子比例": heterozygous_ratio,
            "计算步骤": calculation_steps,
        }
        
        # 保存到历史记录
        self.calculation_history.append(result)
        
        return result
    
    def calculate_genotype_from_phenotype(self, phenotype_ratio: str, gene_count: int) -> List[str]:
        """
        从表现型比例逆推亲本基因型
        
        Args:
            phenotype_ratio: 表现型比例字符串，如 "3:1"
            gene_count: 基因数量
        
        Returns:
            List[str]: 可能的亲本基因型组合
        """
        try:
            # 解析比例
            ratio_parts = phenotype_ratio.split(":")
            if len(ratio_parts) != 2:
                raise ValueError("表现型比例格式错误，应为 '显性:隐性'")
            
            dominant = int(ratio_parts[0])
            recessive = int(ratio_parts[1])
            total = dominant + recessive
            
            # 根据基因数量和比例推断亲本基因型
            possible_genotypes = []
            
            if gene_count == 1:
                if dominant == 3 and recessive == 1:
                    # 3:1 比例，亲本为杂合子
                    possible_genotypes = ["Aa × Aa"]
                elif dominant == 1 and recessive == 1:
                    # 1:1 比例，亲本为杂合子和隐性纯合子
                    possible_genotypes = ["Aa × aa"]
                elif dominant == 4 and recessive == 0:
                    # 全显性，亲本至少有一个显性纯合子
                    possible_genotypes = ["AA × AA", "AA × Aa", "AA × aa"]
                elif dominant == 0 and recessive == 4:
                    # 全隐性，亲本均为隐性纯合子
                    possible_genotypes = ["aa × aa"]
            
            elif gene_count == 2:
                if dominant == 9 and recessive == 7:
                    # 9:7 互补作用
                    possible_genotypes = ["AaBb × AaBb"]
                elif dominant == 15 and recessive == 1:
                    # 15:1 重叠作用
                    possible_genotypes = ["AaBb × AaBb"]
                elif dominant == 13 and recessive == 3:
                    # 13:3 抑制作用
                    possible_genotypes = ["AaBb × AaBb"]
            
            return possible_genotypes
        except Exception as e:
            raise ValueError(f"逆推失败: {str(e)}")
    
    def export_result(self, result: Dict[str, Any], file_path: str) -> bool:
        """
        导出计算结果
        
        Args:
            result: 计算结果
            file_path: 导出文件路径
        
        Returns:
            bool: 导出是否成功
        """
        try:
            # 准备导出数据
            export_data = []
            
            # 基本信息
            export_data.append({
                "类型": "基本信息",
                "内容": f"计算时间: {result['计算时间']}"
            })
            export_data.append({
                "类型": "基本信息",
                "内容": f"基因数量: {result['基因数量']}"
            })
            export_data.append({
                "类型": "基本信息",
                "内容": f"父本基因型: {result['父本基因型']}"
            })
            export_data.append({
                "类型": "基本信息",
                "内容": f"母本基因型: {result['母本基因型']}"
            })
            
            # 配子信息
            export_data.append({
                "类型": "配子信息",
                "内容": f"父本配子: {', '.join(result['父本配子'])}"
            })
            export_data.append({
                "类型": "配子信息",
                "内容": f"母本配子: {', '.join(result['母本配子'])}"
            })
            
            # 基因型比例
            export_data.append({"类型": "分隔符", "内容": "="*50})
            export_data.append({"类型": "基因型比例", "内容": "基因型比例:"})
            for gt, ratio in result['基因型比例'].items():
                export_data.append({
                    "类型": "基因型比例",
                    "内容": f"{gt}: {int(ratio*100)}%"
                })
            
            # 表现型比例
            export_data.append({"类型": "表现型比例", "内容": "表现型比例:"})
            for pt, ratio in result['表现型比例'].items():
                export_data.append({
                    "类型": "表现型比例",
                    "内容": f"{pt}: {int(ratio*100)}%"
                })
            
            # 纯合子/杂合子比例
            export_data.append({"类型": "纯合子/杂合子比例", "内容": "纯合子/杂合子比例:"})
            export_data.append({
                "类型": "纯合子/杂合子比例",
                "内容": f"纯合子: {int(result['纯合子比例']*100)}%"
            })
            export_data.append({
                "类型": "纯合子/杂合子比例",
                "内容": f"杂合子: {int(result['杂合子比例']*100)}%"
            })
            
            # 计算步骤
            export_data.append({"类型": "分隔符", "内容": "="*50})
            export_data.append({"类型": "计算步骤", "内容": "计算步骤:"})
            for step in result['计算步骤']:
                export_data.append({"类型": "计算步骤", "内容": step})
            
            # 棋盘图
            if self.config["show_chessboard"]:
                export_data.append({"类型": "分隔符", "内容": "="*50})
                export_data.append({"类型": "棋盘图", "内容": "棋盘图:"})
                for i, row in enumerate(result['棋盘图']):
                    export_data.append({
                        "类型": "棋盘图",
                        "内容": f"配子 {result['父本配子'][i]}: {', '.join(row)}"
                    })
            
            # 导出数据
            DataIO.export_data(export_data, file_path, title="遗传概率计算结果")
            
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False


class GeneticsCalculatorGUI(GUIApp):
    """遗传概率计算器GUI界面"""
    
    def __init__(self):
        """初始化GUI界面"""
        super().__init__("遗传概率自动计算器", width=1200, height=800)
        self.calculator = GeneticsCalculator()
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导出计算结果", "command": self.export_result},
            {"label": "查看历史记录", "command": self.show_history},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("设置", [
            {"label": "基因数量设置", "command": self.set_gene_count},
            {"label": "显示选项", "command": self.set_display_options}
        ])
    
    def create_main_frame(self):
        """创建主界面"""
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 顶部标题
        title_label = tk.Label(self.main_frame, text="遗传概率自动计算器", font=(".SF NS Text", 16, "bold"))
        title_label.pack(pady=10)
        
        # 主内容区域
        content_frame = BaseFrame(self.main_frame, padding="10")
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧输入区域
        left_frame = BaseFrame(content_frame, padding="10")
        left_frame.config(width=400)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        left_frame.pack_propagate(False)
        
        # 基因数量选择
        gene_count_frame = BaseFrame(left_frame, padding="10")
        gene_count_frame.pack(fill=tk.X)
        
        label = gene_count_frame.create_label("基因数量：", 0, 0, sticky="w")
        label.config(font=(".SF NS Text", 12))
        
        self.gene_count_var = tk.IntVar(value=1)
        gene_count_frame.create_radiobutton("单基因", self.gene_count_var, 1, 0, 1, sticky="w")
        gene_count_frame.create_radiobutton("双基因", self.gene_count_var, 2, 0, 2, sticky="w")
        gene_count_frame.create_radiobutton("三基因", self.gene_count_var, 3, 0, 3, sticky="w")
        
        # 基因型输入
        genotype_frame = BaseFrame(left_frame, padding="10")
        genotype_frame.pack(fill=tk.X, pady=10)
        
        label = genotype_frame.create_label("亲本基因型输入", 0, 0, sticky="w")
        label.config(font=(".SF NS Text", 12, "bold"))
        
        genotype_frame.create_label("父本基因型：", 1, 0, sticky="w", pady=5)
        self.parent1_var = tk.StringVar()
        parent1_entry = genotype_frame.create_entry(1, 1, width=30)
        parent1_entry.config(textvariable=self.parent1_var)
        
        genotype_frame.create_label("母本基因型：", 2, 0, sticky="w", pady=5)
        self.parent2_var = tk.StringVar()
        parent2_entry = genotype_frame.create_entry(2, 1, width=30)
        parent2_entry.config(textvariable=self.parent2_var)
        
        # 示例基因型
        example_frame = BaseFrame(left_frame, padding="10")
        example_frame.pack(fill=tk.X, pady=10)
        
        label = example_frame.create_label("示例基因型：", 0, 0, sticky="w")
        label.config(font=(".SF NS Text", 10, "bold"))
        example_frame.create_label("单基因：Aa × Aa", 1, 0, sticky="w")
        example_frame.create_label("双基因：AaBb × AaBb", 2, 0, sticky="w")
        example_frame.create_label("三基因：AaBbCc × AaBbCc", 3, 0, sticky="w")
        
        # 计算按钮
        button_frame = BaseFrame(left_frame, padding="10")
        button_frame.pack(fill=tk.X, pady=10)
        
        button_frame.create_button("开始计算", self.start_calculation, 0, 0)
        button_frame.create_button("清空输入", self.clear_input, 0, 1)
        
        # 逆推功能
        reverse_frame = BaseFrame(left_frame, padding="10")
        reverse_frame.pack(fill=tk.X, pady=10)
        
        label = reverse_frame.create_label("基因型逆推", 0, 0, sticky="w")
        label.config(font=(".SF NS Text", 12, "bold"))
        
        reverse_frame.create_label("表现型比例：", 1, 0, sticky="w", pady=5)
        self.phenotype_ratio_var = tk.StringVar()
        ratio_entry = reverse_frame.create_entry(1, 1, width=20)
        ratio_entry.config(textvariable=self.phenotype_ratio_var)
        
        reverse_frame.create_button("逆推基因型", self.reverse_calculate, 2, 0)
        
        # 右侧结果显示区域
        right_frame = BaseFrame(content_frame, padding="10")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 结果标签
        result_label = tk.Label(right_frame, text="计算结果", font=(".SF NS Text", 12, "bold"))
        result_label.pack(pady=10)
        
        # 结果显示区域
        self.result_text = tk.Text(right_frame, width=80, height=30, font=(".SF NS Text", 10), wrap=tk.WORD)
        self.result_text.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.config(yscrollcommand=scrollbar.set)
        
        # 初始显示帮助信息
        self.show_help_info()
    
    def show_help_info(self):
        """显示帮助信息"""
        help_text = """
        遗传概率自动计算器使用说明：
        
        1. 选择基因数量（单基因/双基因/三基因）
        2. 输入亲本基因型，格式示例：
           - 单基因：Aa × Aa
           - 双基因：AaBb × AaBb
           - 三基因：AaBbCc × AaBbCc
        3. 点击"开始计算"按钮
        4. 查看计算结果，包括：
           - 配子组合
           - 棋盘图
           - 基因型比例
           - 表现型比例
           - 纯合子/杂合子比例
           - 详细计算步骤
        5. 可以使用"逆推基因型"功能，从表现型比例推测亲本基因型
        
        注意事项：
        - 基因型中的每对基因必须使用相同字母（大小写不同）
        - 不同基因对必须使用不同字母
        - 输入时可省略空格
        
        示例：
        - 单基因杂交：Aa × Aa → 3:1 显性:隐性
        - 双基因杂交：AaBb × AaBb → 9:3:3:1 表现型比例
        """
        
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert(tk.END, help_text)
    
    def start_calculation(self):
        """开始计算"""
        try:
            # 获取输入
            gene_count = self.gene_count_var.get()
            parent1 = self.parent1_var.get().strip()
            parent2 = self.parent2_var.get().strip()
            
            # 验证输入
            if not parent1 or not parent2:
                MessageBox.warning("提示", "请输入亲本基因型")
                return
            
            # 验证基因型格式
            if not self.calculator.validate_genotype(parent1, gene_count):
                MessageBox.error("错误", f"父本基因型 {parent1} 格式错误")
                return
            
            if not self.calculator.validate_genotype(parent2, gene_count):
                MessageBox.error("错误", f"母本基因型 {parent2} 格式错误")
                return
            
            # 执行计算
            result = self.calculator.calculate_offspring(parent1, parent2, gene_count)
            
            # 显示结果
            self.show_calculation_result(result)
            
        except Exception as e:
            MessageBox.error("计算错误", str(e))
    
    def show_calculation_result(self, result: Dict[str, Any]):
        """显示计算结果"""
        # 清空结果区域
        self.result_text.delete("1.0", tk.END)
        
        # 设置字体
        self.result_text.tag_configure("title", font=(".SF NS Text", 12, "bold"))
        self.result_text.tag_configure("heading", font=(".SF NS Text", 11, "bold"))
        self.result_text.tag_configure("normal", font=(".SF NS Text", 10))
        self.result_text.tag_configure("ratio", font=(".SF NS Text", 10, "bold"), foreground="#2c3e50")
        
        # 显示基本信息
        self.result_text.insert(tk.END, "=== 遗传概率计算结果 ===\n\n", "title")
        self.result_text.insert(tk.END, f"计算时间：{result['计算时间']}\n", "normal")
        self.result_text.insert(tk.END, f"基因数量：{result['基因数量']} 对\n", "normal")
        self.result_text.insert(tk.END, f"父本基因型：{result['父本基因型']}\n", "normal")
        self.result_text.insert(tk.END, f"母本基因型：{result['母本基因型']}\n\n", "normal")
        
        # 显示配子
        self.result_text.insert(tk.END, "=== 配子组合 ===\n", "heading")
        self.result_text.insert(tk.END, f"父本配子：{', '.join(result['父本配子'])}\n", "normal")
        self.result_text.insert(tk.END, f"母本配子：{', '.join(result['母本配子'])}\n\n", "normal")
        
        # 显示棋盘图
        if self.calculator.config["show_chessboard"]:
            self.result_text.insert(tk.END, "=== 棋盘图 ===\n", "heading")
            # 显示母本配子
            self.result_text.insert(tk.END, f"       {'   '.join(result['母本配子'])}\n", "normal")
            # 显示棋盘内容
            for i, row in enumerate(result['棋盘图']):
                self.result_text.insert(tk.END, f"{result['父本配子'][i]}  : {'   '.join(row)}\n", "normal")
            self.result_text.insert(tk.END, "\n", "normal")
        
        # 显示基因型比例
        self.result_text.insert(tk.END, "=== 基因型比例 ===\n", "heading")
        for gt, ratio in result['基因型比例'].items():
            self.result_text.insert(tk.END, f"{gt} : {int(ratio*100)}% ({len([g for g in result['子代基因型'] if g == gt])}/{len(result['子代基因型'])})\n", "normal")
        self.result_text.insert(tk.END, "\n", "normal")
        
        # 显示表现型比例
        self.result_text.insert(tk.END, "=== 表现型比例 ===\n", "heading")
        for pt, ratio in result['表现型比例'].items():
            self.result_text.insert(tk.END, f"{pt} : {int(ratio*100)}% ({len([p for p in result['表现型'] if p == pt])}/{len(result['表现型'])})\n", "normal")
        self.result_text.insert(tk.END, "\n", "normal")
        
        # 显示纯合子/杂合子比例
        self.result_text.insert(tk.END, "=== 纯合子/杂合子比例 ===\n", "heading")
        self.result_text.insert(tk.END, f"纯合子：{int(result['纯合子比例']*100)}%\n", "ratio")
        self.result_text.insert(tk.END, f"杂合子：{int(result['杂合子比例']*100)}%\n\n", "ratio")
        
        # 显示计算步骤
        if self.calculator.config["show_calculation_steps"]:
            self.result_text.insert(tk.END, "=== 计算步骤 ===\n", "heading")
            for step in result['计算步骤']:
                self.result_text.insert(tk.END, f"{step}\n", "normal")
    
    def reverse_calculate(self):
        """逆推基因型"""
        try:
            # 获取输入
            gene_count = self.gene_count_var.get()
            phenotype_ratio = self.phenotype_ratio_var.get().strip()
            
            # 验证输入
            if not phenotype_ratio:
                MessageBox.warning("提示", "请输入表现型比例")
                return
            
            # 执行逆推计算
            possible_genotypes = self.calculator.calculate_genotype_from_phenotype(phenotype_ratio, gene_count)
            
            # 显示结果
            self.result_text.delete("1.0", tk.END)
            
            if possible_genotypes:
                self.result_text.insert(tk.END, f"=== 基因型逆推结果 ===\n\n", "title")
                self.result_text.insert(tk.END, f"表现型比例：{phenotype_ratio}\n", "normal")
                self.result_text.insert(tk.END, f"基因数量：{gene_count} 对\n\n", "normal")
                self.result_text.insert(tk.END, "可能的亲本基因型组合：\n", "heading")
                for i, genotype in enumerate(possible_genotypes, 1):
                    self.result_text.insert(tk.END, f"{i}. {genotype}\n", "normal")
            else:
                self.result_text.insert(tk.END, f"=== 基因型逆推结果 ===\n\n", "title")
                self.result_text.insert(tk.END, f"表现型比例：{phenotype_ratio}\n", "normal")
                self.result_text.insert(tk.END, f"基因数量：{gene_count} 对\n\n", "normal")
                self.result_text.insert(tk.END, "未找到匹配的基因型组合\n", "normal")
                self.result_text.insert(tk.END, "请检查输入的表现型比例是否正确\n", "normal")
                
        except Exception as e:
            MessageBox.error("逆推错误", str(e))
    
    def clear_input(self):
        """清空输入"""
        self.parent1_var.set("")
        self.parent2_var.set("")
        self.phenotype_ratio_var.set("")
        self.result_text.delete("1.0", tk.END)
        self.show_help_info()
    
    def export_result(self):
        """导出计算结果"""
        if not self.calculator.calculation_history:
            MessageBox.warning("提示", "没有可导出的计算结果")
            return
        
        # 获取最新的计算结果
        latest_result = self.calculator.calculation_history[-1]
        
        # 选择导出文件路径
        file_path = FileDialog.save_file(
            title="导出计算结果",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("Word文件", "*.docx"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            if self.calculator.export_result(latest_result, file_path):
                MessageBox.info("成功", f"计算结果已导出到 {file_path}")
            else:
                MessageBox.error("失败", "导出失败，请检查文件路径和格式")
    
    def show_history(self):
        """显示计算历史"""
        if not self.calculator.calculation_history:
            MessageBox.info("提示", "没有计算历史记录")
            return
        
        # 创建历史记录窗口
        history_window = tk.Toplevel(self.root)
        history_window.title("计算历史记录")
        history_window.geometry("800x600")
        
        # 创建历史记录列表
        history_listbox = tk.Listbox(history_window, width=100, height=20)
        history_listbox.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(history_window, orient=tk.VERTICAL, command=history_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        history_listbox.config(yscrollcommand=scrollbar.set)
        
        # 填充历史记录
        for i, result in enumerate(self.calculator.calculation_history):
            history_listbox.insert(tk.END, f"{i+1}. {result['计算时间']} - {result['父本基因型']} × {result['母本基因型']}")
        
        # 查看按钮
        def view_history_item():
            selected = history_listbox.curselection()
            if selected:
                index = selected[0]
                result = self.calculator.calculation_history[index]
                self.show_calculation_result(result)
                history_window.destroy()
        
        view_button = ttk.Button(history_window, text="查看选中记录", command=view_history_item)
        view_button.pack(pady=10)
    
    def set_gene_count(self):
        """设置基因数量"""
        gene_count = self.calculator.config["gene_count"]
        new_count = simpledialog.askinteger("基因数量设置", "请输入基因数量 (1-3):", initialvalue=gene_count, minvalue=1, maxvalue=3)
        if new_count:
            self.calculator.config["gene_count"] = new_count
            MessageBox.info("成功", f"基因数量已设置为 {new_count}")
    
    def set_display_options(self):
        """设置显示选项"""
        # 创建设置窗口
        settings_window = tk.Toplevel(self.root)
        settings_window.title("显示选项设置")
        settings_window.geometry("400x300")
        
        # 显示棋盘图选项
        show_chessboard_var = tk.BooleanVar(value=self.calculator.config["show_chessboard"])
        chessboard_check = ttk.Checkbutton(settings_window, text="显示棋盘图", variable=show_chessboard_var)
        chessboard_check.pack(pady=10, padx=20, anchor=tk.W)
        
        # 显示计算步骤选项
        show_steps_var = tk.BooleanVar(value=self.calculator.config["show_calculation_steps"])
        steps_check = ttk.Checkbutton(settings_window, text="显示计算步骤", variable=show_steps_var)
        steps_check.pack(pady=10, padx=20, anchor=tk.W)
        
        # 显示比例选项
        show_ratio_var = tk.BooleanVar(value=self.calculator.config["show_ratio"])
        ratio_check = ttk.Checkbutton(settings_window, text="显示比例", variable=show_ratio_var)
        ratio_check.pack(pady=10, padx=20, anchor=tk.W)
        
        # 保存按钮
        def save_settings():
            self.calculator.config["show_chessboard"] = show_chessboard_var.get()
            self.calculator.config["show_calculation_steps"] = show_steps_var.get()
            self.calculator.config["show_ratio"] = show_ratio_var.get()
            MessageBox.info("成功", "显示选项已保存")
            settings_window.destroy()
        
        save_button = ttk.Button(settings_window, text="保存设置", command=save_settings)
        save_button.pack(pady=20)


if __name__ == "__main__":
    app = GeneticsCalculatorGUI()
    app.run()
