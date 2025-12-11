#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
等值线图分析模拟器
支持生成等高线/等压线/等温线/等降水量线图，交互式分析，判读技巧演示等功能
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Optional
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import cm
from matplotlib.contour import ContourSet
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class ContourSimulator:
    """等值线图模拟器"""
    
    def __init__(self):
        """初始化等值线模拟器"""
        self.config = {
            "contour_type": "等高线",  # 等值线类型：等高线/等压线/等温线/等降水量线
            "grid_size": 50,  # 网格大小
            "min_value": 0,  # 最小值
            "max_value": 100,  # 最大值
            "contour_interval": 10,  # 等值线间隔
            "show_labels": True,  # 是否显示等值线标签
            "show_colorbar": True,  # 是否显示颜色条
            "show_grid": True,  # 是否显示网格
            "terrain_type": "山地",  # 地形类型：山地/平原/海洋/丘陵/高原
            "contour_style": "solid",  # 等值线样式：solid/dashed/dotted
            "line_width": 1.0,  # 线条宽度
            "color_map": "viridis",  # 颜色映射
            "interpolation": "cubic",  # 插值方法
            "show_terrain_features": True,  # 是否显示地形特征标记
            "feature_size": 10  # 特征标记大小
        }
        
        # 预设地形模板
        self.terrain_templates = {
            "山地": {
                "function": lambda x, y: 50 + 30 * np.sin(0.1 * x) * np.cos(0.1 * y) + 20 * np.exp(-0.001 * (x**2 + y**2)),
                "min": 0,
                "max": 100,
                "interval": 10
            },
            "平原": {
                "function": lambda x, y: 20 + 5 * np.random.rand(*x.shape),
                "min": 10,
                "max": 30,
                "interval": 2
            },
            "海洋": {
                "function": lambda x, y: 100 - 0.01 * (x**2 + y**2) + 5 * np.random.rand(*x.shape),
                "min": 0,
                "max": 100,
                "interval": 10
            },
            "丘陵": {
                "function": lambda x, y: 30 + 15 * np.sin(0.2 * x) * np.sin(0.2 * y) + 10 * np.random.rand(*x.shape),
                "min": 10,
                "max": 60,
                "interval": 5
            },
            "高原": {
                "function": lambda x, y: 70 + 10 * np.sin(0.05 * x) * np.cos(0.05 * y),
                "min": 50,
                "max": 90,
                "interval": 5
            }
        }
        
        # 等值线类型配置
        self.contour_type_configs = {
            "等高线": {
                "title": "等高线图",
                "unit": "米",
                "color_map": "terrain",
                "features": ["山峰", "山谷", "山脊", "鞍部", "陡崖"]
            },
            "等压线": {
                "title": "等压线图",
                "unit": "百帕",
                "color_map": "RdBu_r",
                "features": ["高压中心", "低压中心", "高压脊", "低压槽", "鞍部"]
            },
            "等温线": {
                "title": "等温线图",
                "unit": "°C",
                "color_map": "coolwarm",
                "features": ["高温中心", "低温中心", "等温线密集区", "等温线稀疏区"]
            },
            "等降水量线": {
                "title": "等降水量线图",
                "unit": "毫米",
                "color_map": "Blues",
                "features": ["多雨中心", "少雨中心", "降水梯度大的区域"]
            }
        }
        
        self.current_data = None  # 当前数据
        self.current_contour = None  # 当前等值线对象
        self.interactive_points = []  # 交互点列表
    
    def generate_contour_data(self) -> np.ndarray:
        """
        生成等值线数据
        
        Returns:
            np.ndarray: 生成的数据数组
        """
        # 创建网格
        x = np.linspace(-100, 100, self.config["grid_size"])
        y = np.linspace(-100, 100, self.config["grid_size"])
        X, Y = np.meshgrid(x, y)
        
        # 根据地形类型生成数据
        template = self.terrain_templates[self.config["terrain_type"]]
        Z = template["function"](X, Y)
        
        # 归一化到指定范围
        Z = self._normalize_data(Z, self.config["min_value"], self.config["max_value"])
        
        self.current_data = Z
        return Z
    
    def _normalize_data(self, data: np.ndarray, min_val: float, max_val: float) -> np.ndarray:
        """
        归一化数据到指定范围
        
        Args:
            data: 原始数据
            min_val: 目标最小值
            max_val: 目标最大值
        
        Returns:
            np.ndarray: 归一化后的数据
        """
        data_min = np.min(data)
        data_max = np.max(data)
        
        if data_max == data_min:
            return np.full(data.shape, min_val)
        
        normalized = min_val + (max_val - min_val) * (data - data_min) / (data_max - data_min)
        return normalized
    
    def create_contour_plot(self, data: np.ndarray = None) -> plt.Figure:
        """
        创建等值线图
        
        Args:
            data: 要绘制的数据，默认使用当前数据
        
        Returns:
            plt.Figure: 等值线图表
        """
        if data is None:
            data = self.generate_contour_data()
        
        # 创建图表
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # 设置标题和单位
        contour_config = self.contour_type_configs[self.config["contour_type"]]
        ax.set_title(f"{contour_config['title']}", fontsize=14, fontweight="bold", pad=20)
        ax.set_xlabel("X 坐标", fontsize=12)
        ax.set_ylabel("Y 坐标", fontsize=12)
        
        # 绘制填充等值线
        cmap = plt.get_cmap(self.config["color_map"])
        contourf = ax.contourf(
            data,
            levels=np.arange(
                self.config["min_value"],
                self.config["max_value"] + self.config["contour_interval"] / 2,
                self.config["contour_interval"]
            ),
            cmap=cmap,
            alpha=0.7
        )
        
        # 绘制等值线
        contour = ax.contour(
            data,
            levels=np.arange(
                self.config["min_value"],
                self.config["max_value"] + self.config["contour_interval"] / 2,
                self.config["contour_interval"]
            ),
            colors="k",
            linewidths=self.config["line_width"],
            linestyles=self.config["contour_style"]
        )
        
        # 显示等值线标签
        if self.config["show_labels"]:
            ax.clabel(
                contour,
                inline=True,
                fontsize=8,
                fmt=f"%.0f{contour_config['unit']}"
            )
        
        # 显示颜色条
        if self.config["show_colorbar"]:
            cbar = fig.colorbar(contourf, ax=ax)
            cbar.set_label(f"数值 ({contour_config['unit']})")
        
        # 显示网格
        if self.config["show_grid"]:
            ax.grid(True, alpha=0.3, linestyle="--")
        
        # 标记地形特征
        if self.config["show_terrain_features"]:
            self._mark_terrain_features(ax, data)
        
        # 保存当前等值线对象
        self.current_contour = contour
        
        return fig
    
    def _mark_terrain_features(self, ax, data: np.ndarray):
        """
        标记地形特征
        
        Args:
            ax: 坐标轴对象
            data: 数据数组
        """
        contour_type = self.config["contour_type"]
        
        if contour_type == "等高线":
            # 标记山峰（局部最大值）
            peaks = self._find_local_maxima(data)
            for peak in peaks[:5]:  # 最多标记5个山峰
                ax.scatter(peak[1], peak[0], s=self.config["feature_size"]*2, c="r", marker="^", label="山峰")
                ax.text(peak[1]+1, peak[0]+1, f"山峰 ({data[peak[0], peak[1]]:.0f}m)", fontsize=8, ha="left")
            
            # 标记山谷（局部最小值）
            valleys = self._find_local_minima(data)
            for valley in valleys[:5]:  # 最多标记5个山谷
                ax.scatter(valley[1], valley[0], s=self.config["feature_size"]*2, c="b", marker="v", label="山谷")
                ax.text(valley[1]+1, valley[0]+1, f"山谷 ({data[valley[0], valley[1]]:.0f}m)", fontsize=8, ha="left")
        
        elif contour_type == "等压线":
            # 标记高压和低压中心
            peaks = self._find_local_maxima(data)
            for peak in peaks[:3]:
                ax.scatter(peak[1], peak[0], s=self.config["feature_size"]*2, c="r", marker="H", label="高压中心")
                ax.text(peak[1]+1, peak[0]+1, f"高压 ({data[peak[0], peak[1]]:.0f}hPa)", fontsize=8, ha="left")
            
            valleys = self._find_local_minima(data)
            for valley in valleys[:3]:
                ax.scatter(valley[1], valley[0], s=self.config["feature_size"]*2, c="b", marker="L", label="低压中心")
                ax.text(valley[1]+1, valley[0]+1, f"低压 ({data[valley[0], valley[1]]:.0f}hPa)", fontsize=8, ha="left")
        
        elif contour_type == "等温线":
            # 标记高温和低温中心
            peaks = self._find_local_maxima(data)
            for peak in peaks[:3]:
                ax.scatter(peak[1], peak[0], s=self.config["feature_size"]*2, c="r", marker="o", label="高温中心")
                ax.text(peak[1]+1, peak[0]+1, f"高温 ({data[peak[0], peak[1]]:.1f}°C)", fontsize=8, ha="left")
            
            valleys = self._find_local_minima(data)
            for valley in valleys[:3]:
                ax.scatter(valley[1], valley[0], s=self.config["feature_size"]*2, c="b", marker="o", label="低温中心")
                ax.text(valley[1]+1, valley[0]+1, f"低温 ({data[valley[0], valley[1]]:.1f}°C)", fontsize=8, ha="left")
    
    def _find_local_maxima(self, data: np.ndarray, neighborhood=3) -> List[tuple]:
        """
        查找局部最大值
        
        Args:
            data: 数据数组
            neighborhood: 邻域大小
        
        Returns:
            List[tuple]: 局部最大值坐标列表
        """
        maxima = []
        height, width = data.shape
        
        for i in range(neighborhood, height - neighborhood):
            for j in range(neighborhood, width - neighborhood):
                # 检查是否为局部最大值
                neighborhood_data = data[i-neighborhood:i+neighborhood+1, j-neighborhood:j+neighborhood+1]
                if data[i, j] == np.max(neighborhood_data):
                    maxima.append((i, j))
        
        # 按值排序
        maxima.sort(key=lambda x: data[x[0], x[1]], reverse=True)
        return maxima
    
    def _find_local_minima(self, data: np.ndarray, neighborhood=3) -> List[tuple]:
        """
        查找局部最小值
        
        Args:
            data: 数据数组
            neighborhood: 邻域大小
        
        Returns:
            List[tuple]: 局部最小值坐标列表
        """
        minima = []
        height, width = data.shape
        
        for i in range(neighborhood, height - neighborhood):
            for j in range(neighborhood, width - neighborhood):
                # 检查是否为局部最小值
                neighborhood_data = data[i-neighborhood:i+neighborhood+1, j-neighborhood:j+neighborhood+1]
                if data[i, j] == np.min(neighborhood_data):
                    minima.append((i, j))
        
        # 按值排序
        minima.sort(key=lambda x: data[x[0], x[1]])
        return minima
    
    def analyze_contour(self, point: tuple) -> Dict[str, Any]:
        """
        分析等值线上的点
        
        Args:
            point: 要分析的点坐标
        
        Returns:
            Dict[str, Any]: 分析结果
        """
        if self.current_data is None:
            return {"错误": "没有生成等值线数据"}
        
        # 确保坐标在有效范围内
        i, j = point
        height, width = self.current_data.shape
        if i < 0 or i >= height or j < 0 or j >= width:
            return {"错误": "坐标超出范围"}
        
        value = self.current_data[i, j]
        
        # 计算梯度
        gradient = np.gradient(self.current_data)
        gradient_magnitude = np.sqrt(gradient[0][i, j]**2 + gradient[1][i, j]**2)
        gradient_direction = np.arctan2(gradient[1][i, j], gradient[0][i, j]) * 180 / np.pi
        
        # 判断地形特征
        feature = self._classify_terrain_feature(i, j)
        
        # 生成分析报告
        analysis = {
            "坐标": point,
            "数值": round(value, 2),
            "梯度大小": round(gradient_magnitude, 4),
            "梯度方向": round(gradient_direction, 1),
            "地形特征": feature,
            "等值线类型": self.config["contour_type"],
            "判读技巧": self._get_interpretation_tips(feature),
            "高考考点": self._get_exam_points(feature)
        }
        
        return analysis
    
    def _classify_terrain_feature(self, i: int, j: int) -> str:
        """
        分类地形特征
        
        Args:
            i: 行索引
            j: 列索引
        
        Returns:
            str: 地形特征名称
        """
        # 简单实现，根据梯度和局部特征判断
        gradient = np.gradient(self.current_data)
        grad_mag = np.sqrt(gradient[0][i, j]**2 + gradient[1][i, j]**2)
        
        if grad_mag < 0.1:
            # 平坦区域
            return "平坦区域"
        elif grad_mag > 1.0:
            # 陡峭区域
            return "陡峭区域"
        else:
            # 中等坡度
            return "缓坡区域"
    
    def _get_interpretation_tips(self, feature: str) -> str:
        """
        获取判读技巧
        
        Args:
            feature: 地形特征
        
        Returns:
            str: 判读技巧
        """
        tips = {
            "山峰": "山峰是等高线闭合且数值从中心向四周递减的区域。判读时注意等高线的闭合情况和数值变化趋势。",
            "山谷": "山谷是等高线向数值高处凸出的区域。可以通过'凸高为低'的原则判断。",
            "山脊": "山脊是等高线向数值低处凸出的区域。可以通过'凸低为高'的原则判断。",
            "鞍部": "鞍部是两个山峰之间的低洼地带，等高线呈'8'字形。",
            "陡崖": "陡崖是多条等高线重合的区域，通常用锯齿状符号标记。",
            "高压中心": "高压中心是等压线闭合且数值从中心向四周递减的区域，天气通常晴朗。",
            "低压中心": "低压中心是等压线闭合且数值从中心向四周递增的区域，天气通常阴雨。",
            "高温中心": "高温中心是等温线闭合且数值从中心向四周递减的区域，通常表示热岛效应或高温天气。",
            "低温中心": "低温中心是等温线闭合且数值从中心向四周递增的区域，通常表示冷空气或高海拔地区。",
            "平坦区域": "平坦区域等值线稀疏，数值变化小，适合农业和城市建设。",
            "陡峭区域": "陡峭区域等值线密集，数值变化大，容易发生水土流失和滑坡。",
            "缓坡区域": "缓坡区域等值线较稀疏，数值变化适中，适合修建梯田和种植经济作物。"
        }
        
        return tips.get(feature, "该区域无特殊地形特征")
    
    def _get_exam_points(self, feature: str) -> str:
        """
        获取高考考点
        
        Args:
            feature: 地形特征
        
        Returns:
            str: 高考考点
        """
        exam_points = {
            "山峰": "高考考点：等高线的判读方法、地形对气候和河流的影响、山区开发利用原则。",
            "山谷": "高考考点：山谷的形成原因、山谷对河流流向的影响、山谷风环流。",
            "山脊": "高考考点：山脊的形成原因、分水岭的判断、山脊对气候的影响。",
            "鞍部": "高考考点：鞍部的地形特征、交通线路选址、军事战略意义。",
            "陡崖": "高考考点：陡崖的高度计算、陡崖的形成原因、瀑布的形成条件。",
            "高压中心": "高考考点：高压系统的天气特征、高压对气温和降水的影响、高压系统的移动规律。",
            "低压中心": "高考考点：低压系统的天气特征、气旋的形成和发展、台风的结构和影响。",
            "高温中心": "高考考点：高温天气的成因、热岛效应的影响、高温对农业生产的影响。",
            "低温中心": "高考考点：低温天气的成因、冷空气的移动路径、低温对农业的影响。",
            "平坦区域": "高考考点：平原的农业发展条件、城市区位选择、交通线路建设成本。",
            "陡峭区域": "高考考点：陡坡的生态问题、水土流失的防治措施、滑坡泥石流的形成条件。",
            "缓坡区域": "高考考点：缓坡的农业利用方式、梯田的修建条件、坡向对农业的影响。"
        }
        
        return exam_points.get(feature, "该地形特征的高考考点较少")
    
    def export_contour(self, file_path: str, fig: plt.Figure = None) -> bool:
        """
        导出等值线图
        
        Args:
            file_path: 导出文件路径
            fig: 要导出的图表，默认使用当前图表
        
        Returns:
            bool: 导出是否成功
        """
        try:
            if fig is None:
                fig = self.create_contour_plot()
            
            fig.savefig(file_path, dpi=300, bbox_inches="tight")
            plt.close(fig)
            return True
        except Exception as e:
            print(f"导出等值线图失败: {e}")
            return False
    
    def set_config(self, config: Dict[str, Any]) -> None:
        """
        设置配置
        
        Args:
            config: 配置字典
        """
        self.config.update(config)
        
        # 如果地形类型改变，更新相关参数
        if "terrain_type" in config:
            template = self.terrain_templates[config["terrain_type"]]
            self.config["min_value"] = template["min"]
            self.config["max_value"] = template["max"]
            self.config["contour_interval"] = template["interval"]
    
    def get_config(self) -> Dict[str, Any]:
        """
        获取当前配置
        
        Returns:
            Dict[str, Any]: 当前配置
        """
        return self.config.copy()


class ContourSimulatorGUI(GUIApp):
    """等值线图模拟器GUI界面"""
    
    def __init__(self):
        """初始化GUI界面"""
        super().__init__("等值线图分析模拟器", width=1400, height=900)
        self.simulator = ContourSimulator()
        self.current_fig = None
        self.current_canvas = None
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导出等值线图", "command": self.export_contour},
            {"label": "保存配置", "command": self.save_config},
            {"label": "加载配置", "command": self.load_config},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("生成", [
            {"label": "生成等值线图", "command": self.generate_contour},
            {"label": "切换等值线类型", "command": self.switch_contour_type},
            {"label": "切换地形类型", "command": self.switch_terrain_type}
        ])
    
    def create_main_frame(self):
        """创建主界面"""
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 左侧控制面板
        control_frame = BaseFrame(self.main_frame, padding="10", width=350)
        control_frame.pack(side=tk.LEFT, fill=tk.Y)
        control_frame.pack_propagate(False)
        
        # 等值线类型选择
        control_frame.create_label("等值线类型", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        self.contour_type_var = tk.StringVar(value=self.simulator.config["contour_type"])
        contour_types = list(self.simulator.contour_type_configs.keys())
        control_frame.create_combobox(contour_types, 0, 1, width=15)
        
        # 地形类型选择
        control_frame.create_label("地形类型", 1, 0, sticky="w", font=(".SF NS Text", 12, "bold"), pady=10)
        self.terrain_var = tk.StringVar(value=self.simulator.config["terrain_type"])
        terrain_types = list(self.simulator.terrain_templates.keys())
        control_frame.create_combobox(terrain_types, 1, 1, width=15)
        
        # 数值范围设置
        control_frame.create_label("数值范围", 2, 0, sticky="w", font=(".SF NS Text", 12, "bold"), pady=10)
        
        range_frame = BaseFrame(control_frame, padding="5")
        range_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        
        range_frame.create_label("最小值：", 0, 0, sticky="w")
        self.min_value_var = tk.DoubleVar(value=self.simulator.config["min_value"])
        range_frame.create_entry(self.min_value_var, 0, 1, width=10)
        
        range_frame.create_label("最大值：", 1, 0, sticky="w")
        self.max_value_var = tk.DoubleVar(value=self.simulator.config["max_value"])
        range_frame.create_entry(self.max_value_var, 1, 1, width=10)
        
        range_frame.create_label("间隔：", 2, 0, sticky="w")
        self.interval_var = tk.DoubleVar(value=self.simulator.config["contour_interval"])
        range_frame.create_entry(self.interval_var, 2, 1, width=10)
        
        # 显示选项
        control_frame.create_label("显示选项", 4, 0, sticky="w", font=(".SF NS Text", 12, "bold"), pady=10)
        
        self.show_labels_var = tk.BooleanVar(value=self.simulator.config["show_labels"])
        control_frame.create_checkbutton("显示等值线标签", self.show_labels_var, 5, 0, sticky="w")
        
        self.show_colorbar_var = tk.BooleanVar(value=self.simulator.config["show_colorbar"])
        control_frame.create_checkbutton("显示颜色条", self.show_colorbar_var, 6, 0, sticky="w")
        
        self.show_grid_var = tk.BooleanVar(value=self.simulator.config["show_grid"])
        control_frame.create_checkbutton("显示网格", self.show_grid_var, 7, 0, sticky="w")
        
        self.show_features_var = tk.BooleanVar(value=self.simulator.config["show_terrain_features"])
        control_frame.create_checkbutton("显示地形特征", self.show_features_var, 8, 0, sticky="w")
        
        # 操作按钮
        button_frame = BaseFrame(control_frame, padding="10")
        button_frame.grid(row=9, column=0, columnspan=2, sticky="ew", pady=20)
        
        button_frame.create_button("生成等值线图", self.generate_contour, 0, 0, width=12)
        button_frame.create_button("应用配置", self.apply_config, 0, 1, width=12, padx=10)
        button_frame.create_button("重置配置", self.reset_config, 1, 0, width=12)
        
        # 右侧等值线显示和分析区域
        right_frame = BaseFrame(self.main_frame, padding="10")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 等值线显示区域
        self.contour_frame = BaseFrame(right_frame, padding="10")
        self.contour_frame.pack(fill=tk.BOTH, expand=True)
        
        # 分析结果区域
        analysis_frame = BaseFrame(right_frame, padding="10")
        analysis_frame.pack(side=tk.BOTTOM, fill=tk.X, height=200)
        analysis_frame.pack_propagate(False)
        
        analysis_frame.create_label("分析结果", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        self.analysis_text = analysis_frame.create_text(1, 0, width=90, height=8, sticky="nsew")
        
        # 初始化生成等值线图
        self.generate_contour()
    
    def generate_contour(self):
        """
        生成等值线图
        """
        # 应用当前配置
        self.apply_config()
        
        # 生成等值线图
        fig = self.simulator.create_contour_plot()
        
        # 清空之前的图表
        if self.current_canvas:
            self.current_canvas.get_tk_widget().destroy()
        
        # 显示图表
        self.current_canvas = FigureCanvasTkAgg(fig, master=self.contour_frame)
        self.current_canvas.draw()
        self.current_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # 绑定鼠标事件
        self.current_canvas.mpl_connect("button_press_event", self.on_canvas_click)
        
        self.current_fig = fig
    
    def on_canvas_click(self, event):
        """
        画布点击事件
        
        Args:
            event: 鼠标事件
        """
        if event.inaxes is None:
            return
        
        # 转换为数据坐标
        x = int(event.xdata)
        y = int(event.ydata)
        
        # 分析点击位置
        analysis = self.simulator.analyze_contour((y, x))
        
        # 显示分析结果
        self.display_analysis(analysis)
    
    def display_analysis(self, analysis: Dict[str, Any]):
        """
        显示分析结果
        
        Args:
            analysis: 分析结果
        """
        self.analysis_text.delete("1.0", tk.END)
        
        content = "等值线分析结果：\n"
        content += "=" * 60 + "\n"
        
        for key, value in analysis.items():
            content += f"{key}：{value}\n\n"
        
        self.analysis_text.insert(tk.END, content)
    
    def apply_config(self):
        """
        应用配置
        """
        # 更新配置
        config = {
            "contour_type": self.contour_type_var.get(),
            "terrain_type": self.terrain_var.get(),
            "min_value": self.min_value_var.get(),
            "max_value": self.max_value_var.get(),
            "contour_interval": self.interval_var.get(),
            "show_labels": self.show_labels_var.get(),
            "show_colorbar": self.show_colorbar_var.get(),
            "show_grid": self.show_grid_var.get(),
            "show_terrain_features": self.show_features_var.get()
        }
        
        self.simulator.set_config(config)
        
        # 更新界面上的数值范围
        self.min_value_var.set(self.simulator.config["min_value"])
        self.max_value_var.set(self.simulator.config["max_value"])
        self.interval_var.set(self.simulator.config["contour_interval"])
    
    def reset_config(self):
        """
        重置配置
        """
        # 重置为默认配置
        default_config = {
            "contour_type": "等高线",
            "terrain_type": "山地",
            "show_labels": True,
            "show_colorbar": True,
            "show_grid": True,
            "show_terrain_features": True
        }
        
        self.simulator.set_config(default_config)
        
        # 更新界面
        self.contour_type_var.set(default_config["contour_type"])
        self.terrain_var.set(default_config["terrain_type"])
        self.show_labels_var.set(default_config["show_labels"])
        self.show_colorbar_var.set(default_config["show_colorbar"])
        self.show_grid_var.set(default_config["show_grid"])
        self.show_features_var.set(default_config["show_terrain_features"])
        
        # 更新数值范围
        self.min_value_var.set(self.simulator.config["min_value"])
        self.max_value_var.set(self.simulator.config["max_value"])
        self.interval_var.set(self.simulator.config["contour_interval"])
    
    def export_contour(self):
        """
        导出等值线图
        """
        file_path = FileDialog.save_file(
            title="导出等值线图",
            defaultextension=".png",
            filetypes=[("PNG图片", "*.png"), ("PDF文件", "*.pdf"), ("SVG文件", "*.svg")]
        )
        
        if file_path:
            if self.current_fig:
                if self.simulator.export_contour(file_path, self.current_fig):
                    MessageBox.info("成功", f"等值线图已导出到 {file_path}")
                else:
                    MessageBox.error("失败", "导出等值线图失败")
            else:
                MessageBox.warning("提示", "没有可导出的等值线图")
    
    def save_config(self):
        """
        保存配置
        """
        file_path = FileDialog.save_file(
            title="保存配置",
            defaultextension=".json",
            filetypes=[("JSON文件", "*.json"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            try:
                import json
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.simulator.get_config(), f, ensure_ascii=False, indent=2)
                MessageBox.info("成功", f"配置已保存到 {file_path}")
            except Exception as e:
                MessageBox.error("失败", f"保存配置失败: {e}")
    
    def load_config(self):
        """
        加载配置
        """
        file_path = FileDialog.open_file(
            title="加载配置",
            filetypes=[("JSON文件", "*.json"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            try:
                import json
                with open(file_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 应用加载的配置
                self.simulator.set_config(config)
                
                # 更新界面
                self.contour_type_var.set(config.get("contour_type", "等高线"))
                self.terrain_var.set(config.get("terrain_type", "山地"))
                self.min_value_var.set(config.get("min_value", 0))
                self.max_value_var.set(config.get("max_value", 100))
                self.interval_var.set(config.get("contour_interval", 10))
                self.show_labels_var.set(config.get("show_labels", True))
                self.show_colorbar_var.set(config.get("show_colorbar", True))
                self.show_grid_var.set(config.get("show_grid", True))
                self.show_features_var.set(config.get("show_terrain_features", True))
                
                MessageBox.info("成功", "配置加载成功")
            except Exception as e:
                MessageBox.error("失败", f"加载配置失败: {e}")
    
    def switch_contour_type(self):
        """
        切换等值线类型
        """
        # 简单实现，弹出选择对话框
        contour_types = list(self.simulator.contour_type_configs.keys())
        selected = tk.StringVar(value=self.simulator.config["contour_type"])
        
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("选择等值线类型")
        dialog.geometry("300x200")
        
        frame = BaseFrame(dialog, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        for i, contour_type in enumerate(contour_types):
            frame.create_radiobutton(contour_type, selected, contour_type, i, 0, sticky="w")
        
        def on_ok():
            self.contour_type_var.set(selected.get())
            dialog.destroy()
            self.generate_contour()
        
        button_frame = BaseFrame(dialog, padding="10")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)
        button_frame.create_button("确定", on_ok, 0, 0, width=10)
        button_frame.create_button("取消", dialog.destroy, 0, 1, width=10, padx=10)
    
    def switch_terrain_type(self):
        """
        切换地形类型
        """
        # 简单实现，弹出选择对话框
        terrain_types = list(self.simulator.terrain_templates.keys())
        selected = tk.StringVar(value=self.simulator.config["terrain_type"])
        
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("选择地形类型")
        dialog.geometry("300x250")
        
        frame = BaseFrame(dialog, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        for i, terrain_type in enumerate(terrain_types):
            frame.create_radiobutton(terrain_type, selected, terrain_type, i, 0, sticky="w")
        
        def on_ok():
            self.terrain_var.set(selected.get())
            dialog.destroy()
            self.generate_contour()
        
        button_frame = BaseFrame(dialog, padding="10")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)
        button_frame.create_button("确定", on_ok, 0, 0, width=10)
        button_frame.create_button("取消", dialog.destroy, 0, 1, width=10, padx=10)


if __name__ == "__main__":
    app = ContourSimulatorGUI()
    app.run()