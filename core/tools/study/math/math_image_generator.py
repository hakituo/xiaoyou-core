#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学图像生成器
支持生成立体几何、三角函数、圆锥曲线等高考数学图像
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from typing import List, Dict, Any, Optional

# 导入公共模块
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class MathImageGenerator:
    """数学图像生成器"""
    
    def __init__(self):
        """初始化数学图像生成器"""
        self.image_types = {
            "立体几何": {
                "长方体": self.generate_cuboid,
                "正方体": self.generate_cube,
                "圆柱体": self.generate_cylinder,
                "圆锥体": self.generate_cone,
                "球体": self.generate_sphere
            },
            "三角函数": {
                "正弦函数": self.generate_sin,
                "余弦函数": self.generate_cos,
                "正切函数": self.generate_tan,
                "余切函数": self.generate_cot,
                "复合函数": self.generate_compound_trig
            },
            "圆锥曲线": {
                "椭圆": self.generate_ellipse,
                "双曲线": self.generate_hyperbola,
                "抛物线": self.generate_parabola,
                "圆": self.generate_circle
            }
        }
        
        # 配置参数
        self.config = {
            "figure_size": (8, 6),
            "dpi": 100,
            "color": "blue",
            "line_width": 2,
            "grid": True,
            "title_fontsize": 14,
            "axis_fontsize": 12
        }
    
    def generate_cuboid(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成长方体图像
        
        Args:
            params: 参数字典，包含长、宽、高
        
        Returns:
            plt.Figure: 生成的图像
        """
        from mpl_toolkits.mplot3d import Axes3D
        
        length = params.get("length", 3)
        width = params.get("width", 2)
        height = params.get("height", 1)
        
        fig = plt.figure(figsize=self.config["figure_size"])
        ax = fig.add_subplot(111, projection='3d')
        
        # 绘制长方体
        # 定义长方体的8个顶点
        vertices = np.array([
            [0, 0, 0], [length, 0, 0], [length, width, 0], [0, width, 0],
            [0, 0, height], [length, 0, height], [length, width, height], [0, width, height]
        ])
        
        # 定义面
        faces = [
            [0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4],
            [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]
        ]
        
        # 绘制面
        ax.add_collection3d(plt.PolygonPatch(
            vertices[faces[0]], color='lightblue', alpha=0.5, zorder=1
        ))
        
        # 绘制棱
        for i in range(4):
            ax.plot3D(*zip(vertices[i], vertices[(i+1)%4]), color='blue', linewidth=self.config["line_width"])
            ax.plot3D(*zip(vertices[i+4], vertices[(i+1)%4 + 4]), color='blue', linewidth=self.config["line_width"])
            ax.plot3D(*zip(vertices[i], vertices[i+4]), color='blue', linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('X轴', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('Y轴', fontsize=self.config["axis_fontsize"])
        ax.set_zlabel('Z轴', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'长方体 (长={length}, 宽={width}, 高={height})', fontsize=self.config["title_fontsize"])
        
        # 设置视角
        ax.view_init(30, 45)
        
        return fig
    
    def generate_cube(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成正方体图像
        
        Args:
            params: 参数字典，包含边长
        
        Returns:
            plt.Figure: 生成的图像
        """
        # 复用长方体函数，设置长宽高相等
        params["length"] = params.get("side_length", 2)
        params["width"] = params["length"]
        params["height"] = params["length"]
        
        fig = self.generate_cuboid(params)
        fig.axes[0].set_title(f'正方体 (边长={params["length"]})', fontsize=self.config["title_fontsize"])
        
        return fig
    
    def generate_cylinder(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成圆柱体图像
        
        Args:
            params: 参数字典，包含半径和高
        
        Returns:
            plt.Figure: 生成的图像
        """
        from mpl_toolkits.mplot3d import Axes3D
        
        radius = params.get("radius", 1)
        height = params.get("height", 3)
        
        fig = plt.figure(figsize=self.config["figure_size"])
        ax = fig.add_subplot(111, projection='3d')
        
        # 生成圆柱体数据
        theta = np.linspace(0, 2*np.pi, 50)
        z = np.linspace(0, height, 20)
        theta, z = np.meshgrid(theta, z)
        
        x = radius * np.cos(theta)
        y = radius * np.sin(theta)
        
        # 绘制侧面
        ax.plot_surface(x, y, z, alpha=0.5, color='lightblue')
        
        # 绘制上下底面
        theta_circle = np.linspace(0, 2*np.pi, 50)
        x_circle = radius * np.cos(theta_circle)
        y_circle = radius * np.sin(theta_circle)
        
        ax.plot(x_circle, y_circle, np.zeros_like(x_circle), color='blue', linewidth=self.config["line_width"])
        ax.plot(x_circle, y_circle, np.full_like(x_circle, height), color='blue', linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('X轴', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('Y轴', fontsize=self.config["axis_fontsize"])
        ax.set_zlabel('Z轴', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'圆柱体 (半径={radius}, 高={height})', fontsize=self.config["title_fontsize"])
        
        ax.view_init(30, 45)
        
        return fig
    
    def generate_cone(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成圆锥体图像
        
        Args:
            params: 参数字典，包含半径和高
        
        Returns:
            plt.Figure: 生成的图像
        """
        from mpl_toolkits.mplot3d import Axes3D
        
        radius = params.get("radius", 1)
        height = params.get("height", 3)
        
        fig = plt.figure(figsize=self.config["figure_size"])
        ax = fig.add_subplot(111, projection='3d')
        
        # 生成圆锥体数据
        theta = np.linspace(0, 2*np.pi, 50)
        z = np.linspace(0, height, 20)
        theta, z = np.meshgrid(theta, z)
        
        r = radius * (1 - z/height)
        x = r * np.cos(theta)
        y = r * np.sin(theta)
        
        # 绘制侧面
        ax.plot_surface(x, y, z, alpha=0.5, color='lightblue')
        
        # 绘制底面
        theta_circle = np.linspace(0, 2*np.pi, 50)
        x_circle = radius * np.cos(theta_circle)
        y_circle = radius * np.sin(theta_circle)
        
        ax.plot(x_circle, y_circle, np.zeros_like(x_circle), color='blue', linewidth=self.config["line_width"])
        
        # 绘制母线
        ax.plot([0, 0], [0, 0], [0, height], color='blue', linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('X轴', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('Y轴', fontsize=self.config["axis_fontsize"])
        ax.set_zlabel('Z轴', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'圆锥体 (半径={radius}, 高={height})', fontsize=self.config["title_fontsize"])
        
        ax.view_init(30, 45)
        
        return fig
    
    def generate_sphere(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成球体图像
        
        Args:
            params: 参数字典，包含半径
        
        Returns:
            plt.Figure: 生成的图像
        """
        from mpl_toolkits.mplot3d import Axes3D
        
        radius = params.get("radius", 2)
        
        fig = plt.figure(figsize=self.config["figure_size"])
        ax = fig.add_subplot(111, projection='3d')
        
        # 生成球体数据
        u, v = np.mgrid[0:2*np.pi:50j, 0:np.pi:50j]
        x = radius * np.cos(u) * np.sin(v)
        y = radius * np.sin(u) * np.sin(v)
        z = radius * np.cos(v)
        
        # 绘制球体
        ax.plot_surface(x, y, z, alpha=0.5, color='lightblue')
        
        # 设置坐标轴
        ax.set_xlabel('X轴', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('Y轴', fontsize=self.config["axis_fontsize"])
        ax.set_zlabel('Z轴', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'球体 (半径={radius})', fontsize=self.config["title_fontsize"])
        
        ax.view_init(30, 45)
        
        return fig
    
    def generate_sin(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成正弦函数图像
        
        Args:
            params: 参数字典，包含振幅、周期、相位等
        
        Returns:
            plt.Figure: 生成的图像
        """
        amplitude = params.get("amplitude", 1)
        period = params.get("period", 2*np.pi)
        phase = params.get("phase", 0)
        vertical_shift = params.get("vertical_shift", 0)
        
        # 生成数据
        x = np.linspace(0, 2*np.pi, 500)
        y = amplitude * np.sin((2*np.pi/period)*x + phase) + vertical_shift
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制函数
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'y = {amplitude}sin({2*np.pi/period:.2f}x + {phase:.2f}) + {vertical_shift}', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_xlim(0, 2*np.pi)
        ax.set_ylim(-amplitude-1, amplitude+1)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_cos(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成余弦函数图像
        
        Args:
            params: 参数字典，包含振幅、周期、相位等
        
        Returns:
            plt.Figure: 生成的图像
        """
        amplitude = params.get("amplitude", 1)
        period = params.get("period", 2*np.pi)
        phase = params.get("phase", 0)
        vertical_shift = params.get("vertical_shift", 0)
        
        # 生成数据
        x = np.linspace(0, 2*np.pi, 500)
        y = amplitude * np.cos((2*np.pi/period)*x + phase) + vertical_shift
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制函数
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'y = {amplitude}cos({2*np.pi/period:.2f}x + {phase:.2f}) + {vertical_shift}', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_xlim(0, 2*np.pi)
        ax.set_ylim(-amplitude-1, amplitude+1)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_tan(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成正切函数图像
        
        Args:
            params: 参数字典
        
        Returns:
            plt.Figure: 生成的图像
        """
        # 生成数据
        x = np.linspace(-np.pi/2 + 0.1, np.pi/2 - 0.1, 200)
        y = np.tan(x)
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制函数
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 添加渐近线
        ax.axvline(x=-np.pi/2, color='red', linestyle='--', linewidth=1)
        ax.axvline(x=np.pi/2, color='red', linestyle='--', linewidth=1)
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title('y = tan(x)', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_xlim(-np.pi/2 + 0.1, np.pi/2 - 0.1)
        ax.set_ylim(-10, 10)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_cot(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成余切函数图像
        
        Args:
            params: 参数字典
        
        Returns:
            plt.Figure: 生成的图像
        """
        # 生成数据
        x = np.linspace(0.1, np.pi - 0.1, 200)
        y = np.tan(np.pi/2 - x)
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制函数
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 添加渐近线
        ax.axvline(x=0, color='red', linestyle='--', linewidth=1)
        ax.axvline(x=np.pi, color='red', linestyle='--', linewidth=1)
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title('y = cot(x)', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_xlim(0.1, np.pi - 0.1)
        ax.set_ylim(-10, 10)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_compound_trig(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成复合三角函数图像
        
        Args:
            params: 参数字典
        
        Returns:
            plt.Figure: 生成的图像
        """
        # 生成数据
        x = np.linspace(0, 4*np.pi, 500)
        
        # 复合函数：y = sin(x) + 0.5sin(2x) + 0.3sin(3x)
        y = np.sin(x) + 0.5*np.sin(2*x) + 0.3*np.sin(3*x)
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制函数
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title('y = sin(x) + 0.5sin(2x) + 0.3sin(3x)', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_xlim(0, 4*np.pi)
        ax.set_ylim(-2, 2)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_circle(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成圆的图像
        
        Args:
            params: 参数字典，包含圆心和半径
        
        Returns:
            plt.Figure: 生成的图像
        """
        center_x = params.get("center_x", 0)
        center_y = params.get("center_y", 0)
        radius = params.get("radius", 2)
        
        # 生成数据
        theta = np.linspace(0, 2*np.pi, 200)
        x = center_x + radius * np.cos(theta)
        y = center_y + radius * np.sin(theta)
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制圆
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'圆 (圆心=({center_x}, {center_y}), 半径={radius})', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_aspect('equal')
        ax.set_xlim(center_x - radius - 1, center_x + radius + 1)
        ax.set_ylim(center_y - radius - 1, center_y + radius + 1)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_ellipse(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成椭圆图像
        
        Args:
            params: 参数字典，包含长半轴、短半轴、圆心等
        
        Returns:
            plt.Figure: 生成的图像
        """
        center_x = params.get("center_x", 0)
        center_y = params.get("center_y", 0)
        a = params.get("semi_major_axis", 3)  # 长半轴
        b = params.get("semi_minor_axis", 2)  # 短半轴
        
        # 生成数据
        theta = np.linspace(0, 2*np.pi, 200)
        x = center_x + a * np.cos(theta)
        y = center_y + b * np.sin(theta)
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制椭圆
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'椭圆 (长半轴={a}, 短半轴={b})', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_aspect('equal')
        ax.set_xlim(center_x - a - 1, center_x + a + 1)
        ax.set_ylim(center_y - b - 1, center_y + b + 1)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_hyperbola(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成双曲线图像
        
        Args:
            params: 参数字典，包含实半轴、虚半轴等
        
        Returns:
            plt.Figure: 生成的图像
        """
        a = params.get("real_axis", 2)  # 实半轴
        b = params.get("imaginary_axis", 1)  # 虚半轴
        
        # 生成数据
        x = np.linspace(-5, 5, 500)
        # 双曲线方程：x²/a² - y²/b² = 1
        y1 = b * np.sqrt((x**2/a**2) - 1)  # 上半支
        y2 = -b * np.sqrt((x**2/a**2) - 1)  # 下半支
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制双曲线
        ax.plot(x[x >= a], y1[x >= a], color=self.config["color"], linewidth=self.config["line_width"])
        ax.plot(x[x >= a], y2[x >= a], color=self.config["color"], linewidth=self.config["line_width"])
        ax.plot(x[x <= -a], y1[x <= -a], color=self.config["color"], linewidth=self.config["line_width"])
        ax.plot(x[x <= -a], y2[x <= -a], color=self.config["color"], linewidth=self.config["line_width"])
        
        # 绘制渐近线
        asymptote1 = (b/a)*x
        asymptote2 = -(b/a)*x
        ax.plot(x, asymptote1, color='red', linestyle='--', linewidth=1)
        ax.plot(x, asymptote2, color='red', linestyle='--', linewidth=1)
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'双曲线 x²/{a}² - y²/{b}² = 1', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_xlim(-5, 5)
        ax.set_ylim(-5, 5)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_parabola(self, params: Dict[str, Any]) -> plt.Figure:
        """
        生成抛物线图像
        
        Args:
            params: 参数字典，包含开口方向、焦点等
        
        Returns:
            plt.Figure: 生成的图像
        """
        a = params.get("coefficient", 0.5)  # 二次项系数
        
        # 生成数据
        x = np.linspace(-5, 5, 200)
        y = a * x**2
        
        fig, ax = plt.subplots(figsize=self.config["figure_size"])
        
        # 绘制抛物线
        ax.plot(x, y, color=self.config["color"], linewidth=self.config["line_width"])
        
        # 设置坐标轴
        ax.set_xlabel('x', fontsize=self.config["axis_fontsize"])
        ax.set_ylabel('y', fontsize=self.config["axis_fontsize"])
        ax.set_title(f'抛物线 y = {a}x²', fontsize=self.config["title_fontsize"])
        
        # 设置网格和范围
        ax.grid(self.config["grid"])
        ax.set_xlim(-5, 5)
        ax.set_ylim(-1, 15)
        
        # 添加坐标轴
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axvline(x=0, color='black', linewidth=1)
        
        return fig
    
    def generate_image(self, category: str, image_type: str, params: Dict[str, Any]) -> plt.Figure:
        """
        生成指定类型的图像
        
        Args:
            category: 图像类别
            image_type: 图像类型
            params: 参数字典
        
        Returns:
            plt.Figure: 生成的图像
        """
        if category not in self.image_types:
            raise ValueError(f"不支持的图像类别: {category}")
        
        if image_type not in self.image_types[category]:
            raise ValueError(f"不支持的图像类型: {image_type}")
        
        return self.image_types[category][image_type](params)
    
    def save_image(self, figure: plt.Figure, file_path: str) -> bool:
        """
        保存图像到文件
        
        Args:
            figure: 要保存的图像
            file_path: 保存路径
        
        Returns:
            bool: 保存是否成功
        """
        try:
            figure.savefig(file_path, dpi=self.config["dpi"], bbox_inches='tight')
            plt.close(figure)
            return True
        except Exception as e:
            print(f"保存图像失败: {e}")
            plt.close(figure)
            return False
    
    def set_config(self, config: Dict[str, Any]) -> None:
        """
        设置图像生成配置
        
        Args:
            config: 配置字典
        """
        self.config.update(config)


class MathImageGeneratorGUI(GUIApp):
    """数学图像生成器GUI界面"""
    
    def __init__(self):
        """初始化GUI界面"""
        super().__init__("数学图像生成器", width=1200, height=800)
        self.generator = MathImageGenerator()
        self.current_figure = None
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "保存图像", "command": self.save_current_image},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("配置", [
            {"label": "设置颜色", "command": self.set_color},
            {"label": "设置线宽", "command": self.set_line_width},
            {"label": "设置图像大小", "command": self.set_figure_size}
        ])
    
    def create_main_frame(self):
        """创建主界面"""
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 顶部标题
        title_label = tk.Label(self.main_frame, text="数学图像生成器", font=(".SF NS Text", 16, "bold"))
        title_label.pack(pady=10)
        
        # 主内容区域
        content_frame = BaseFrame(self.main_frame, padding="10")
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧控制面板
        left_frame = BaseFrame(content_frame, padding="10")
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        left_frame.pack_propagate(False)
        
        # 图像类别选择
        label = left_frame.create_label("图像类别：", 0, 0, sticky="w")
        label.config(font=(".SF NS Text", 12, "bold"))
        
        self.category_var = tk.StringVar(value="立体几何")
        categories = list(self.generator.image_types.keys())
        category_combo = left_frame.create_combobox(categories, 0, 1, width=20)
        category_combo.config(textvariable=self.category_var)
        category_combo.bind("<<ComboboxSelected>>", self.on_category_change)
        
        # 图像类型选择
        label = left_frame.create_label("图像类型：", 1, 0, sticky="w", pady=10)
        label.config(font=(".SF NS Text", 12, "bold"))
        
        self.image_type_var = tk.StringVar(value="长方体")
        image_types = list(self.generator.image_types["立体几何"].keys())
        self.image_type_combo = left_frame.create_combobox(image_types, 1, 1, width=20)
        self.image_type_combo.config(textvariable=self.image_type_var)
        
        # 参数配置区域
        self.params_frame = BaseFrame(left_frame, padding="10")
        self.params_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=10)
        
        # 初始显示立体几何的参数配置
        self.create_params_widgets("立体几何", "长方体")
        
        # 生成按钮
        generate_button = left_frame.create_button("生成图像", self.generate_image, 3, 0, columnspan=2)
        
        # 右侧图像显示区域
        right_frame = BaseFrame(content_frame, padding="10")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 图像显示区域
        self.image_container = BaseFrame(right_frame, padding="10")
        self.image_container.pack(fill=tk.BOTH, expand=True)
        
        # 初始显示欢迎信息
        welcome_label = tk.Label(self.image_container, text="欢迎使用数学图像生成器！\n\n选择图像类别和类型，调整参数，点击'生成图像'按钮查看效果。", font=(".SF NS Text", 14))
        welcome_label.pack(expand=True)
        
        self.welcome_label = welcome_label
    
    def on_category_change(self, event):
        """
        图像类别变化事件处理
        """
        category = self.category_var.get()
        image_types = list(self.generator.image_types[category].keys())
        
        # 更新图像类型下拉框
        self.image_type_combo.config(values=image_types)
        self.image_type_var.set(image_types[0])
        
        # 更新参数配置区域
        self.create_params_widgets(category, image_types[0])
    
    def create_params_widgets(self, category: str, image_type: str):
        """
        创建参数配置控件
        
        Args:
            category: 图像类别
            image_type: 图像类型
        """
        # 清空参数配置区域
        for widget in self.params_frame.winfo_children():
            widget.destroy()
        
        # 根据图像类型创建不同的参数控件
        if category == "立体几何":
            self.create_geometry_params(image_type)
        elif category == "三角函数":
            self.create_trig_params(image_type)
        elif category == "圆锥曲线":
            self.create_conic_params(image_type)
    
    def create_geometry_params(self, image_type: str):
        """
        创建立体几何参数控件
        
        Args:
            image_type: 图像类型
        """
        row = 0
        
        if image_type in ["长方体"]:
            # 长
            self.params_frame.create_label("长：", row, 0, sticky="w")
            self.length_var = tk.DoubleVar(value=3.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.length_var)
            row += 1
            
            # 宽
            self.params_frame.create_label("宽：", row, 0, sticky="w")
            self.width_var = tk.DoubleVar(value=2.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.width_var)
            row += 1
            
            # 高
            self.params_frame.create_label("高：", row, 0, sticky="w")
            self.height_var = tk.DoubleVar(value=1.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.height_var)
            row += 1
        
        elif image_type in ["正方体"]:
            # 边长
            self.params_frame.create_label("边长：", row, 0, sticky="w")
            self.side_length_var = tk.DoubleVar(value=2.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.side_length_var)
            row += 1
        
        elif image_type in ["圆柱体", "圆锥体"]:
            # 半径
            self.params_frame.create_label("半径：", row, 0, sticky="w")
            self.radius_var = tk.DoubleVar(value=1.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.radius_var)
            row += 1
            
            # 高
            self.params_frame.create_label("高：", row, 0, sticky="w")
            self.height_var = tk.DoubleVar(value=3.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.height_var)
            row += 1
        
        elif image_type in ["球体"]:
            # 半径
            self.params_frame.create_label("半径：", row, 0, sticky="w")
            self.radius_var = tk.DoubleVar(value=2.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.radius_var)
            row += 1
    
    def create_trig_params(self, image_type: str):
        """
        创建三角函数参数控件
        
        Args:
            image_type: 图像类型
        """
        row = 0
        
        if image_type in ["正弦函数", "余弦函数"]:
            # 振幅
            self.params_frame.create_label("振幅：", row, 0, sticky="w")
            self.amplitude_var = tk.DoubleVar(value=1.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.amplitude_var)
            row += 1
            
            # 周期
            self.params_frame.create_label("周期：", row, 0, sticky="w")
            self.period_var = tk.DoubleVar(value=2*np.pi)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.period_var)
            row += 1
            
            # 相位
            self.params_frame.create_label("相位：", row, 0, sticky="w")
            self.phase_var = tk.DoubleVar(value=0.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.phase_var)
            row += 1
    
    def create_conic_params(self, image_type: str):
        """
        创建圆锥曲线参数控件
        
        Args:
            image_type: 图像类型
        """
        row = 0
        
        if image_type in ["圆"]:
            # 圆心X
            self.params_frame.create_label("圆心X：", row, 0, sticky="w")
            self.center_x_var = tk.DoubleVar(value=0.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.center_x_var)
            row += 1
            
            # 圆心Y
            self.params_frame.create_label("圆心Y：", row, 0, sticky="w")
            self.center_y_var = tk.DoubleVar(value=0.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.center_y_var)
            row += 1
            
            # 半径
            self.params_frame.create_label("半径：", row, 0, sticky="w")
            self.radius_var = tk.DoubleVar(value=2.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.radius_var)
            row += 1
        
        elif image_type in ["椭圆"]:
            # 长半轴
            self.params_frame.create_label("长半轴：", row, 0, sticky="w")
            self.semi_major_axis_var = tk.DoubleVar(value=3.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.semi_major_axis_var)
            row += 1
            
            # 短半轴
            self.params_frame.create_label("短半轴：", row, 0, sticky="w")
            self.semi_minor_axis_var = tk.DoubleVar(value=2.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.semi_minor_axis_var)
            row += 1
        
        elif image_type in ["双曲线"]:
            # 实半轴
            self.params_frame.create_label("实半轴：", row, 0, sticky="w")
            self.real_axis_var = tk.DoubleVar(value=2.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.real_axis_var)
            row += 1
            
            # 虚半轴
            self.params_frame.create_label("虚半轴：", row, 0, sticky="w")
            self.imaginary_axis_var = tk.DoubleVar(value=1.0)
            entry = self.params_frame.create_entry(row, 1, width=15)
            entry.config(textvariable=self.imaginary_axis_var)
            row += 1
    
    def generate_image(self):
        """
        生成图像
        """
        try:
            # 获取选择的图像类别和类型
            category = self.category_var.get()
            image_type = self.image_type_var.get()
            
            # 获取参数
            params = self.get_params(category, image_type)
            
            # 生成图像
            self.current_figure = self.generator.generate_image(category, image_type, params)
            
            # 显示图像
            self.display_image()
            
        except Exception as e:
            MessageBox.error("生成失败", f"生成图像失败: {e}")
    
    def get_params(self, category: str, image_type: str) -> Dict[str, Any]:
        """
        获取当前参数
        
        Args:
            category: 图像类别
            image_type: 图像类型
        
        Returns:
            Dict[str, Any]: 参数字典
        """
        params = {}
        
        if category == "立体几何":
            if image_type == "长方体":
                params["length"] = self.length_var.get()
                params["width"] = self.width_var.get()
                params["height"] = self.height_var.get()
            elif image_type == "正方体":
                params["side_length"] = self.side_length_var.get()
            elif image_type in ["圆柱体", "圆锥体"]:
                params["radius"] = self.radius_var.get()
                params["height"] = self.height_var.get()
            elif image_type == "球体":
                params["radius"] = self.radius_var.get()
        
        elif category == "三角函数":
            if image_type in ["正弦函数", "余弦函数"]:
                params["amplitude"] = self.amplitude_var.get()
                params["period"] = self.period_var.get()
                params["phase"] = self.phase_var.get()
        
        elif category == "圆锥曲线":
            if image_type == "圆":
                params["center_x"] = self.center_x_var.get()
                params["center_y"] = self.center_y_var.get()
                params["radius"] = self.radius_var.get()
            elif image_type == "椭圆":
                params["semi_major_axis"] = self.semi_major_axis_var.get()
                params["semi_minor_axis"] = self.semi_minor_axis_var.get()
            elif image_type == "双曲线":
                params["real_axis"] = self.real_axis_var.get()
                params["imaginary_axis"] = self.imaginary_axis_var.get()
        
        return params
    
    def display_image(self):
        """
        在GUI中显示图像
        """
        # 移除欢迎信息
        if hasattr(self, 'welcome_label'):
            self.welcome_label.destroy()
        
        # 移除之前的图像
        for widget in self.image_container.winfo_children():
            widget.destroy()
        
        # 创建画布
        canvas = FigureCanvasTkAgg(self.current_figure, master=self.image_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    
    def save_current_image(self):
        """
        保存当前图像
        """
        if not self.current_figure:
            MessageBox.warning("提示", "请先生成图像")
            return
        
        # 选择保存路径
        file_path = FileDialog.save_file(
            title="保存图像",
            defaultextension=".png",
            filetypes=[("PNG文件", "*.png"), ("JPEG文件", "*.jpg"), ("PDF文件", "*.pdf"), ("SVG文件", "*.svg")]
        )
        
        if file_path:
            if self.generator.save_image(self.current_figure, file_path):
                MessageBox.info("成功", f"图像已保存到 {file_path}")
            else:
                MessageBox.error("失败", "保存图像失败")
    
    def set_color(self):
        """
        设置图像颜色
        """
        color_window = tk.Toplevel(self.root)
        color_window.title("设置颜色")
        color_window.geometry("300x200")
        
        # 颜色选择
        color_frame = BaseFrame(color_window, padding="20")
        color_frame.pack(fill=tk.BOTH, expand=True)
        
        color_frame.create_label("选择颜色：", 0, 0, sticky="w")
        
        self.color_var = tk.StringVar(value=self.generator.config["color"])
        colors = ["blue", "red", "green", "black", "purple", "orange", "yellow"]
        color_combo = color_frame.create_combobox(colors, 0, 1, width=15)
        color_combo.config(textvariable=self.color_var)
        
        def save_color():
            self.generator.config["color"] = self.color_var.get()
            color_window.destroy()
            MessageBox.info("成功", f"颜色已设置为 {self.color_var.get()}")
        
        color_frame.create_button("保存", save_color, 1, 0, columnspan=2, pady=20)
    
    def set_line_width(self):
        """
        设置线宽
        """
        line_width = simpledialog.askfloat("设置线宽", "请输入线宽 (0.5-5):", initialvalue=self.generator.config["line_width"], minvalue=0.5, maxvalue=5)
        if line_width is not None:
            self.generator.config["line_width"] = line_width
            MessageBox.info("成功", f"线宽已设置为 {line_width}")
    
    def set_figure_size(self):
        """
        设置图像大小
        """
        size_window = tk.Toplevel(self.root)
        size_window.title("设置图像大小")
        size_window.geometry("300x200")
        
        size_frame = BaseFrame(size_window, padding="20")
        size_frame.pack(fill=tk.BOTH, expand=True)
        
        size_frame.create_label("宽度：", 0, 0, sticky="w")
        self.width_var = tk.DoubleVar(value=self.generator.config["figure_size"][0])
        size_frame.create_entry(self.width_var, 0, 1, width=10)
        
        size_frame.create_label("高度：", 1, 0, sticky="w", pady=10)
        self.height_var = tk.DoubleVar(value=self.generator.config["figure_size"][1])
        size_frame.create_entry(self.height_var, 1, 1, width=10)
        
        def save_size():
            width = self.width_var.get()
            height = self.height_var.get()
            self.generator.config["figure_size"] = (width, height)
            size_window.destroy()
            MessageBox.info("成功", f"图像大小已设置为 ({width}, {height})")
        
        size_frame.create_button("保存", save_size, 2, 0, columnspan=2, pady=20)


# 导入simpledialog
from tkinter import simpledialog


if __name__ == "__main__":
    app = MathImageGeneratorGUI()
    app.run()