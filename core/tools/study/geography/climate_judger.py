#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
气候类型自动判断工具
支持数据输入、双维度判断、详细结果输出等功能
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Optional
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class ClimateJudger:
    """气候类型判断工具"""
    
    def __init__(self):
        """初始化气候判断工具"""
        self.climate_data = []  # 气候数据列表
        self.judge_history = []  # 判断历史记录
        
        # 气候类型判断规则
        self.climate_rules = [
            # 热带气候
            {
                "气候类型": "热带雨林气候",
                "判断条件": [
                    {"条件": "最冷月均温 > 15°C"},
                    {"条件": "年降水量 > 2000mm"},
                    {"条件": "各月降水量较均匀"}
                ],
                "核心特征": "全年高温多雨",
                "分布区域": "赤道附近（南北纬10°之间）",
                "典型植被": "热带雨林",
                "农业影响": "适合种植热带经济作物，如橡胶、咖啡等",
                "高考高频考点": "气候成因（赤道低压带控制）、分布规律、植被类型"
            },
            {
                "气候类型": "热带草原气候",
                "判断条件": [
                    {"条件": "最冷月均温 > 15°C"},
                    {"条件": "年降水量 750-1500mm"},
                    {"条件": "有明显干湿季"}
                ],
                "核心特征": "全年高温，分干湿两季",
                "分布区域": "热带雨林气候南北两侧（南北纬10°-20°）",
                "典型植被": "热带草原",
                "农业影响": "适合发展畜牧业，雨季可种植粮食作物",
                "高考高频考点": "气候成因（赤道低压带与信风带交替控制）、干湿季变化"
            },
            {
                "气候类型": "热带季风气候",
                "判断条件": [
                    {"条件": "最冷月均温 > 15°C"},
                    {"条件": "年降水量 1500-2000mm"},
                    {"条件": "有明显旱雨季"}
                ],
                "核心特征": "全年高温，分旱雨两季",
                "分布区域": "亚洲南部和东南部（北纬10°-25°大陆东岸）",
                "典型植被": "热带季雨林",
                "农业影响": "雨热同期，适合种植水稻等粮食作物",
                "高考高频考点": "气候成因（海陆热力性质差异和气压带风带季节移动）"
            },
            {
                "气候类型": "热带沙漠气候",
                "判断条件": [
                    {"条件": "最冷月均温 > 15°C"},
                    {"条件": "年降水量 < 250mm"},
                    {"条件": "全年干旱少雨"}
                ],
                "核心特征": "全年高温少雨",
                "分布区域": "南北回归线附近大陆西岸和内部（南北纬20°-30°）",
                "典型植被": "热带荒漠",
                "农业影响": "水资源短缺，需发展节水农业",
                "高考高频考点": "气候成因（副热带高压带或信风带控制）、分布规律"
            },
            # 亚热带气候
            {
                "气候类型": "亚热带季风气候",
                "判断条件": [
                    {"条件": "最冷月均温 0-15°C"},
                    {"条件": "年降水量 800-1500mm"},
                    {"条件": "夏季高温多雨，冬季温和少雨"}
                ],
                "核心特征": "夏季高温多雨，冬季温和少雨",
                "分布区域": "南北纬25°-35°大陆东岸",
                "典型植被": "亚热带常绿阔叶林",
                "农业影响": "雨热同期，适合种植亚热带作物",
                "高考高频考点": "气候成因（海陆热力性质差异）、分布规律、农业生产"
            },
            {
                "气候类型": "地中海气候",
                "判断条件": [
                    {"条件": "最冷月均温 0-15°C"},
                    {"条件": "年降水量 300-1000mm"},
                    {"条件": "夏季炎热干燥，冬季温和多雨"}
                ],
                "核心特征": "夏季炎热干燥，冬季温和多雨",
                "分布区域": "南北纬30°-40°大陆西岸",
                "典型植被": "亚热带常绿硬叶林",
                "农业影响": "适合种植葡萄、橄榄等耐旱作物",
                "高考高频考点": "气候成因（副热带高压带与西风带交替控制）、雨热不同期"
            },
            # 温带气候
            {
                "气候类型": "温带季风气候",
                "判断条件": [
                    {"条件": "最冷月均温 < 0°C"},
                    {"条件": "年降水量 500-800mm"},
                    {"条件": "夏季高温多雨，冬季寒冷干燥"}
                ],
                "核心特征": "夏季高温多雨，冬季寒冷干燥",
                "分布区域": "北纬35°-55°大陆东岸",
                "典型植被": "温带落叶阔叶林",
                "农业影响": "雨热同期，适合种植小麦、玉米等粮食作物",
                "高考高频考点": "气候成因（海陆热力性质差异）、分布区域（仅亚洲东部）"
            },
            {
                "气候类型": "温带海洋性气候",
                "判断条件": [
                    {"条件": "最冷月均温 > 0°C"},
                    {"条件": "年降水量 700-1000mm"},
                    {"条件": "全年温和湿润，降水均匀"}
                ],
                "核心特征": "全年温和湿润，降水均匀",
                "分布区域": "南北纬40°-60°大陆西岸",
                "典型植被": "温带落叶阔叶林",
                "农业影响": "适合多汁牧草生长，有利于发展畜牧业",
                "高考高频考点": "气候成因（西风带控制，受暖流影响）、分布规律"
            },
            {
                "气候类型": "温带大陆性气候",
                "判断条件": [
                    {"条件": "最冷月均温 < 0°C"},
                    {"条件": "年降水量 < 500mm"},
                    {"条件": "冬冷夏热，年温差大"}
                ],
                "核心特征": "冬冷夏热，年温差大，降水少",
                "分布区域": "温带大陆内部",
                "典型植被": "温带草原、温带荒漠",
                "农业影响": "降水少，需发展灌溉农业或畜牧业",
                "高考高频考点": "气候成因（深居内陆，远离海洋）、分布规律"
            },
            # 寒带气候
            {
                "气候类型": "寒带气候",
                "判断条件": [
                    {"条件": "最热月均温 < 10°C"},
                    {"条件": "年降水量 < 250mm"},
                    {"条件": "全年寒冷少雨"}
                ],
                "核心特征": "全年寒冷少雨",
                "分布区域": "极地地区",
                "典型植被": "苔原、冰原",
                "农业影响": "气候恶劣，几乎无农业生产",
                "高考高频考点": "气候成因（纬度高，太阳辐射弱）、分布区域"
            }
        ]
        
        self.config = {
            "use_humidity_index": True,  # 是否使用湿度指数辅助判断
            "show_detailed_rules": True,  # 是否显示详细判断规则
            "temperature_precision": 1,  # 温度精度（小数点后位数）
            "precipitation_precision": 0,  # 降水量精度（小数点后位数）
            "default_month_count": 12,  # 默认月份数量
            "validation_threshold": 10  # 数据验证阈值（异常值判断）
        }
    
    def judge_climate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        判断气候类型
        
        Args:
            data: 气候数据，包含气温和降水量信息
        
        Returns:
            Dict[str, Any]: 判断结果
        """
        # 数据验证
        validation = self._validate_data(data)
        if not validation["valid"]:
            return {
                "错误": validation["message"],
                "数据": data
            }
        
        # 计算气候指标
        climate_index = self._calculate_climate_index(data)
        
        # 根据规则判断气候类型
        matched_climates = []
        for rule in self.climate_rules:
            if self._match_climate_rule(rule, climate_index):
                matched_climates.append(rule)
        
        # 生成判断结果
        result = {
            "气候数据": data,
            "气候指标": climate_index,
            "匹配的气候类型": matched_climates,
            "最终判断气候": matched_climates[0] if matched_climates else {"气候类型": "无法判断"},
            "判断依据": [],
            "建议": "",
            "判断时间": ""
        }
        
        # 生成判断依据
        if matched_climates:
            for climate in matched_climates:
                for i, condition in enumerate(climate["判断条件"]):
                    result["判断依据"].append({
                        "气候类型": climate["气候类型"],
                        "条件": condition["条件"],
                        "符合情况": "符合"
                    })
        
        # 记录判断历史
        self.judge_history.append(result)
        
        return result
    
    def _validate_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证气候数据
        
        Args:
            data: 气候数据
        
        Returns:
            Dict[str, Any]: 验证结果
        """
        required_fields = ["气温数据", "降水量数据"]
        for field in required_fields:
            if field not in data:
                return {"valid": False, "message": f"缺少必要字段：{field}"}
        
        # 检查数据长度
        temp_data = data["气温数据"]
        precip_data = data["降水量数据"]
        
        if len(temp_data) != len(precip_data):
            return {"valid": False, "message": "气温数据和降水量数据长度不一致"}
        
        if len(temp_data) < 3:
            return {"valid": False, "message": "数据不足，至少需要3个月的气候数据"}
        
        # 检查数据合理性
        for i, (temp, precip) in enumerate(zip(temp_data, precip_data)):
            try:
                temp_val = float(temp)
                precip_val = float(precip)
                
                # 检查温度异常值
                if temp_val < -50 or temp_val > 50:
                    return {"valid": False, "message": f"第{i+1}个月温度异常：{temp_val}°C"}
                
                # 检查降水量异常值
                if precip_val < 0 or precip_val > 5000:
                    return {"valid": False, "message": f"第{i+1}个月降水量异常：{precip_val}mm"}
            except ValueError:
                return {"valid": False, "message": f"第{i+1}个月数据格式错误"}
        
        return {"valid": True, "message": "数据验证通过"}
    
    def _calculate_climate_index(self, data: Dict[str, Any]) -> Dict[str, float]:
        """
        计算气候指标
        
        Args:
            data: 气候数据
        
        Returns:
            Dict[str, float]: 气候指标
        """
        temp_data = [float(temp) for temp in data["气温数据"]]
        precip_data = [float(precip) for precip in data["降水量数据"]]
        
        # 计算基本指标
        avg_temp = sum(temp_data) / len(temp_data)
        min_temp = min(temp_data)
        max_temp = max(temp_data)
        annual_precip = sum(precip_data)
        avg_precip = annual_precip / len(temp_data)
        
        # 计算最冷月和最热月
        coldest_month = temp_data.index(min_temp) + 1
        hottest_month = temp_data.index(max_temp) + 1
        
        # 计算降水季节变化
        if len(temp_data) >= 12:
            # 计算夏季（6-8月）和冬季（12-2月）降水量
            summer_precip = sum(precip_data[5:8])  # 6-8月
            winter_precip = sum(precip_data[11:12] + precip_data[0:2])  # 12-2月
            seasonal_ratio = summer_precip / winter_precip if winter_precip != 0 else float('inf')
        else:
            seasonal_ratio = 1.0
        
        # 计算湿度指数
        humidity_index = annual_precip / (avg_temp + 10) if (avg_temp + 10) != 0 else 0
        
        climate_index = {
            "年平均气温": round(avg_temp, self.config["temperature_precision"]),
            "最冷月均温": round(min_temp, self.config["temperature_precision"]),
            "最热月均温": round(max_temp, self.config["temperature_precision"]),
            "年降水量": round(annual_precip, self.config["precipitation_precision"]),
            "月平均降水量": round(avg_precip, self.config["precipitation_precision"]),
            "最冷月": coldest_month,
            "最热月": hottest_month,
            "降水季节变化比": round(seasonal_ratio, 2),
            "湿度指数": round(humidity_index, 2)
        }
        
        return climate_index
    
    def _match_climate_rule(self, rule: Dict[str, Any], climate_index: Dict[str, float]) -> bool:
        """
        匹配气候规则
        
        Args:
            rule: 气候规则
            climate_index: 气候指标
        
        Returns:
            bool: 是否匹配
        """
        for condition in rule["判断条件"]:
            if not self._evaluate_condition(condition["条件"], climate_index):
                return False
        
        return True
    
    def _evaluate_condition(self, condition: str, climate_index: Dict[str, float]) -> bool:
        """
        评估条件是否满足
        
        Args:
            condition: 条件字符串
            climate_index: 气候指标
        
        Returns:
            bool: 条件是否满足
        """
        # 最冷月均温判断
        if "最冷月均温" in condition:
            temp = climate_index["最冷月均温"]
            if ">" in condition:
                threshold = float(condition.split(">"[1]))
                return temp > threshold
            elif "<" in condition:
                threshold = float(condition.split("<"[1]))
                return temp < threshold
            elif "-" in condition:
                low, high = map(float, condition.split("最冷月均温")[1].strip().split("-"))
                return low <= temp <= high
        
        # 最热月均温判断
        if "最热月均温" in condition:
            temp = climate_index["最热月均温"]
            if ">" in condition:
                threshold = float(condition.split(">"[1]))
                return temp > threshold
            elif "<" in condition:
                threshold = float(condition.split("<"[1]))
                return temp < threshold
        
        # 年降水量判断
        if "年降水量" in condition:
            precip = climate_index["年降水量"]
            if ">" in condition:
                threshold = float(condition.split(">"[1]))
                return precip > threshold
            elif "<" in condition:
                threshold = float(condition.split("<"[1]))
                return precip < threshold
            elif "-" in condition:
                low, high = map(float, condition.split("年降水量")[1].strip().split("-"))
                return low <= precip <= high
        
        # 简化的季节特征判断
        if "全年高温" in condition:
            return climate_index["最冷月均温"] > 15
        if "夏季高温" in condition:
            return climate_index["最热月均温"] > 20
        if "冬季寒冷" in condition:
            return climate_index["最冷月均温"] < 0
        if "冬季温和" in condition:
            return 0 <= climate_index["最冷月均温"] <= 15
        if "全年温和" in condition:
            return climate_index["最热月均温"] < 20 and climate_index["最冷月均温"] > 0
        
        return True  # 默认返回True
    
    def visualize_climate(self, data: Dict[str, Any]) -> plt.Figure:
        """
        可视化气候数据
        
        Args:
            data: 气候数据
        
        Returns:
            plt.Figure: 气候图表
        """
        # 创建图表
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        
        # 准备数据
        months = list(range(1, len(data["气温数据"]) + 1))
        temps = [float(t) for t in data["气温数据"]]
        precips = [float(p) for p in data["降水量数据"]]
        
        # 绘制气温曲线
        ax1.plot(months, temps, 'r-', linewidth=2, marker='o', markersize=5, label='气温 (°C)')
        ax1.set_ylabel('气温 (°C)', fontsize=12, color='red')
        ax1.tick_params(axis='y', labelcolor='red')
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.set_title('气候数据可视化', fontsize=14, fontweight='bold', pad=20)
        
        # 绘制降水量柱状图
        ax2.bar(months, precips, color='blue', alpha=0.6, label='降水量 (mm)')
        ax2.set_ylabel('降水量 (mm)', fontsize=12, color='blue')
        ax2.tick_params(axis='y', labelcolor='blue')
        ax2.grid(True, alpha=0.3, linestyle='--')
        ax2.set_xlabel('月份', fontsize=12)
        
        # 设置X轴刻度
        ax2.set_xticks(months)
        ax2.set_xticklabels([f'{m}月' for m in months], rotation=45)
        
        # 调整布局
        plt.tight_layout()
        
        return fig
    
    def export_result(self, result: Dict[str, Any], file_path: str) -> bool:
        """
        导出判断结果
        
        Args:
            result: 判断结果
            file_path: 导出文件路径
        
        Returns:
            bool: 导出是否成功
        """
        try:
            # 准备导出数据
            export_data = {
                "气候数据": result["气候数据"],
                "气候指标": result["气候指标"],
                "判断结果": result["最终判断气候"],
                "判断依据": result["判断依据"],
                "建议": result["建议"]
            }
            
            DataIO.export_data([export_data], file_path, title="气候类型判断结果")
            return True
        except Exception as e:
            print(f"导出结果失败: {e}")
            return False
    
    def import_data(self, file_path: str) -> Dict[str, Any]:
        """
        从文件导入气候数据
        
        Args:
            file_path: 文件路径
        
        Returns:
            Dict[str, Any]: 导入的数据
        """
        try:
            data = DataIO.import_data(file_path)
            if isinstance(data, list):
                # 假设第一行是气温，第二行是降水量
                if len(data) >= 2:
                    return {
                        "气温数据": data[0],
                        "降水量数据": data[1]
                    }
            elif isinstance(data, dict):
                return data
            return {}
        except Exception as e:
            print(f"导入数据失败: {e}")
            return {}


class ClimateJudgerGUI(GUIApp):
    """气候类型判断工具GUI界面"""
    
    def __init__(self):
        """初始化GUI界面"""
        super().__init__("气候类型自动判断工具", width=1200, height=800)
        self.judger = ClimateJudger()
        self.current_data = {
            "气温数据": [0.0] * 12,
            "降水量数据": [0.0] * 12
        }
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导入气候数据", "command": self.import_data},
            {"label": "导出判断结果", "command": self.export_result},
            {"label": "导出错题本", "command": self.export_error_book},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("操作", [
            {"label": "开始判断", "command": self.judge_climate},
            {"label": "重置数据", "command": self.reset_data},
            {"label": "保存判断历史", "command": self.save_history}
        ])
    
    def create_main_frame(self):
        """创建主界面"""
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 顶部标题
        title_label = tk.Label(self.main_frame, text="气候类型自动判断工具", font=(".SF NS Text", 16, "bold"))
        title_label.pack(pady=10)
        
        # 主内容区域
        content_frame = BaseFrame(self.main_frame, padding="10")
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧数据输入区域
        input_frame = BaseFrame(content_frame, padding="10", width=400)
        input_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        input_frame.pack_propagate(False)
        
        # 数据输入选项卡
        notebook = ttk.Notebook(input_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 手动输入选项卡
        manual_frame = BaseFrame(notebook, padding="10")
        notebook.add(manual_frame, text="手动输入")
        
        # 气温数据输入
        manual_frame.create_label("气温数据 (°C)", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        temp_frame = BaseFrame(manual_frame, padding="5")
        temp_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        
        self.temp_entries = []
        for i in range(12):
            temp_frame.create_label(f"{i+1}月：", i, 0, sticky="e")
            entry = temp_frame.create_entry(0.0, i, 1, width=10)
            self.temp_entries.append(entry)
        
        # 降水量数据输入
        manual_frame.create_label("降水量数据 (mm)", 2, 0, sticky="w", font=(".SF NS Text", 12, "bold"), pady=10)
        precip_frame = BaseFrame(manual_frame, padding="5")
        precip_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        
        self.precip_entries = []
        for i in range(12):
            precip_frame.create_label(f"{i+1}月：", i, 0, sticky="e")
            entry = precip_frame.create_entry(0.0, i, 1, width=10)
            self.precip_entries.append(entry)
        
        # 导入数据选项卡
        import_frame = BaseFrame(notebook, padding="10")
        notebook.add(import_frame, text="导入数据")
        
        import_frame.create_label("支持Excel、CSV、TXT格式导入\n每行数据对应一个月份，第一列为气温，第二列为降水量", 0, 0, sticky="w", font=(".SF NS Text", 10, "italic"))
        import_button = import_frame.create_button("选择文件导入", self.import_data, 1, 0, width=20, pady=10)
        
        # 右侧结果显示区域
        result_frame = BaseFrame(content_frame, padding="10")
        result_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 结果选项卡
        result_notebook = ttk.Notebook(result_frame)
        result_notebook.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 判断结果选项卡
        result_tab = BaseFrame(result_notebook, padding="10")
        result_notebook.add(result_tab, text="判断结果")
        
        # 气候指标显示
        metrics_frame = BaseFrame(result_tab, padding="10")
        metrics_frame.pack(side=tk.TOP, fill=tk.X)
        
        metrics_frame.create_label("气候指标", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        self.metrics_text = metrics_frame.create_text(1, 0, width=60, height=10, sticky="nsew")
        
        # 气候类型显示
        climate_frame = BaseFrame(result_tab, padding="10")
        climate_frame.pack(side=tk.TOP, fill=tk.X)
        
        climate_frame.create_label("气候类型判断结果", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        self.climate_text = climate_frame.create_text(1, 0, width=60, height=15, sticky="nsew")
        
        # 图表显示选项卡
        chart_tab = BaseFrame(result_notebook, padding="10")
        result_notebook.add(chart_tab, text="气候图表")
        
        self.chart_canvas = None
        chart_button = chart_tab.create_button("生成气候图表", self.generate_chart, 0, 0, width=15, pady=10)
        
        # 历史记录选项卡
        history_tab = BaseFrame(result_notebook, padding="10")
        result_notebook.add(history_tab, text="判断历史")
        
        history_tab.create_label("判断历史记录", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        self.history_listbox = tk.Listbox(history_tab, width=80, height=20)
        self.history_listbox.grid(row=1, column=0, sticky="nsew")
        
        # 操作按钮
        button_frame = BaseFrame(input_frame, padding="10")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        button_frame.create_button("开始判断", self.judge_climate, 0, 0, width=12)
        button_frame.create_button("重置数据", self.reset_data, 0, 1, width=12, padx=10)
        button_frame.create_button("导出错题", self.export_error_book, 0, 2, width=12)
    
    def judge_climate(self):
        """
        执行气候判断
        """
        # 收集输入数据
        temp_data = []
        precip_data = []
        
        for i in range(12):
            try:
                temp = float(self.temp_entries[i].get())
                precip = float(self.precip_entries[i].get())
                temp_data.append(temp)
                precip_data.append(precip)
            except ValueError:
                MessageBox.error("错误", f"第{i+1}个月数据格式错误，请输入数字")
                return
        
        # 准备气候数据
        climate_data = {
            "气温数据": temp_data,
            "降水量数据": precip_data
        }
        
        # 执行判断
        result = self.judger.judge_climate(climate_data)
        
        # 显示结果
        self.display_result(result)
    
    def display_result(self, result: Dict[str, Any]):
        """
        显示判断结果
        
        Args:
            result: 判断结果
        """
        # 显示气候指标
        self.metrics_text.delete("1.0", tk.END)
        metrics_content = "气候指标：\n"
        metrics_content += "=" * 40 + "\n"
        
        for key, value in result["气候指标"].items():
            metrics_content += f"{key}：{value}\n"
        
        self.metrics_text.insert(tk.END, metrics_content)
        
        # 显示气候类型判断结果
        self.climate_text.delete("1.0", tk.END)
        
        if "错误" in result:
            self.climate_text.insert(tk.END, f"判断错误：{result['错误']}\n", "error")
            return
        
        # 显示最终判断结果
        final_climate = result["最终判断气候"]
        self.climate_text.insert(tk.END, f"最终判断气候类型：{final_climate['气候类型']}\n", "climate_type")
        self.climate_text.insert(tk.END, "\n核心特征：\n")
        self.climate_text.insert(tk.END, f"{final_climate['核心特征']}\n\n")
        
        self.climate_text.insert(tk.END, "分布区域：\n")
        self.climate_text.insert(tk.END, f"{final_climate['分布区域']}\n\n")
        
        self.climate_text.insert(tk.END, "典型植被：\n")
        self.climate_text.insert(tk.END, f"{final_climate['典型植被']}\n\n")
        
        self.climate_text.insert(tk.END, "农业影响：\n")
        self.climate_text.insert(tk.END, f"{final_climate['农业影响']}\n\n")
        
        self.climate_text.insert(tk.END, "高考高频考点：\n")
        self.climate_text.insert(tk.END, f"{final_climate['高考高频考点']}\n\n")
        
        # 显示判断依据
        self.climate_text.insert(tk.END, "判断依据：\n")
        self.climate_text.insert(tk.END, "-" * 40 + "\n")
        
        for i, basis in enumerate(result["判断依据"], 1):
            self.climate_text.insert(tk.END, f"{i}. {basis['气候类型']} - {basis['条件']} - {basis['符合情况']}\n")
        
        # 配置文本样式
        self.climate_text.tag_config("error", foreground="red", font=(".SF NS Text", 12, "bold"))
        self.climate_text.tag_config("climate_type", foreground="blue", font=(".SF NS Text", 14, "bold"))
    
    def generate_chart(self):
        """
        生成气候图表
        """
        # 收集输入数据
        temp_data = []
        precip_data = []
        
        for i in range(12):
            try:
                temp = float(self.temp_entries[i].get())
                precip = float(self.precip_entries[i].get())
                temp_data.append(temp)
                precip_data.append(precip)
            except ValueError:
                MessageBox.error("错误", "请先输入有效的气候数据")
                return
        
        # 准备气候数据
        climate_data = {
            "气温数据": temp_data,
            "降水量数据": precip_data
        }
        
        # 生成图表
        fig = self.judger.visualize_climate(climate_data)
        
        # 清空之前的图表
        if hasattr(self, 'chart_canvas') and self.chart_canvas:
            self.chart_canvas.get_tk_widget().destroy()
        
        # 显示图表
        self.chart_canvas = FigureCanvasTkAgg(fig, master=self.result_notebook.winfo_children()[1])
        self.chart_canvas.draw()
        self.chart_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=10)
    
    def import_data(self):
        """
        导入气候数据
        """
        file_path = FileDialog.open_file(
            title="导入气候数据",
            filetypes=[("Excel文件", "*.xlsx;*.xls"), ("CSV文件", "*.csv"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        
        if file_path:
            data = self.judger.import_data(file_path)
            if data and "气温数据" in data and "降水量数据" in data:
                # 更新输入框
                for i in range(min(12, len(data["气温数据"]))):
                    self.temp_entries[i].delete(0, tk.END)
                    self.temp_entries[i].insert(0, str(data["气温数据"][i]))
                    
                    self.precip_entries[i].delete(0, tk.END)
                    self.precip_entries[i].insert(0, str(data["降水量数据"][i]))
                
                MessageBox.info("成功", f"成功导入 {len(data['气温数据'])} 个月的气候数据")
            else:
                MessageBox.error("失败", "导入数据失败，请检查文件格式")
    
    def reset_data(self):
        """
        重置输入数据
        """
        for i in range(12):
            self.temp_entries[i].delete(0, tk.END)
            self.temp_entries[i].insert(0, "0.0")
            
            self.precip_entries[i].delete(0, tk.END)
            self.precip_entries[i].insert(0, "0.0")
        
        # 清空结果显示
        self.metrics_text.delete("1.0", tk.END)
        self.climate_text.delete("1.0", tk.END)
        
        MessageBox.info("提示", "数据已重置")
    
    def export_error_book(self):
        """
        导出错题本
        """
        file_path = FileDialog.save_file(
            title="导出错题本",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            # 简单实现，将判断历史导出
            if self.judger.judge_history:
                DataIO.export_data(self.judger.judge_history, file_path, title="气候类型判断错题本")
                MessageBox.info("成功", f"错题本已导出到 {file_path}")
            else:
                MessageBox.warning("提示", "没有判断历史记录可以导出")
    
    def save_history(self):
        """
        保存判断历史
        """
        file_path = FileDialog.save_file(
            title="保存判断历史",
            defaultextension=".json",
            filetypes=[("JSON文件", "*.json"), ("Excel文件", "*.xlsx")]
        )
        
        if file_path:
            if self.judger.judge_history:
                DataIO.export_data(self.judger.judge_history, file_path, title="气候类型判断历史")
                MessageBox.info("成功", f"判断历史已保存到 {file_path}")
            else:
                MessageBox.warning("提示", "没有判断历史记录可以保存")
    
    def export_result(self):
        """
        导出当前判断结果
        """
        # 实现简化，使用最后一次判断结果
        if self.judger.judge_history:
            last_result = self.judger.judge_history[-1]
            file_path = FileDialog.save_file(
                title="导出判断结果",
                defaultextension=".xlsx",
                filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
            )
            
            if file_path:
                if self.judger.export_result(last_result, file_path):
                    MessageBox.info("成功", f"判断结果已导出到 {file_path}")
                else:
                    MessageBox.error("失败", "导出结果失败")
        else:
            MessageBox.warning("提示", "没有判断结果可以导出")


if __name__ == "__main__":
    app = ClimateJudgerGUI()
    app.run()