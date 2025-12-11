#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI基础组件模块
基于Tkinter的GUI基础组件，提供统一的界面风格和交互逻辑
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from typing import List, Dict, Any, Callable, Optional


class GUIApp:
    """基础GUI应用类"""
    
    def __init__(self, title: str, width: int = 800, height: int = 600):
        """
        初始化GUI应用
        
        Args:
            title: 窗口标题
            width: 窗口宽度
            height: 窗口高度
        """
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{width}x{height}")
        self.root.resizable(True, True)
        
        # 设置主题
        self.style = ttk.Style()
        self.setup_style()
        
        # 创建主框架
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 菜单条
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)
    
    def setup_style(self):
        """设置界面风格"""
        self.style.configure(
            "TFrame",
            background="#f0f0f0"
        )
        
        self.style.configure(
            "TButton",
            font=(".SF NS Text", 10),
            padding=6,
            relief=tk.FLAT,
            background="#4a90e2",
            foreground="white"
        )
        
        self.style.map(
            "TButton",
            background=[("active", "#357abd")],
            foreground=[("active", "white")]
        )
        
        self.style.configure(
            "TLabel",
            font=(".SF NS Text", 10),
            background="#f0f0f0",
            foreground="#333333"
        )
        
        self.style.configure(
            "TEntry",
            font=(".SF NS Text", 10),
            padding=5
        )
        
        self.style.configure(
            "TText",
            font=(".SF NS Text", 10)
        )
    
    def add_menu(self, name: str, items: List[Dict[str, Any]]) -> None:
        """
        添加菜单
        
        Args:
            name: 菜单名称
            items: 菜单项列表，每项包含label和command
        """
        menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label=name, menu=menu)
        
        for item in items:
            if item.get("separator", False):
                menu.add_separator()
            else:
                menu.add_command(
                    label=item["label"],
                    command=item["command"]
                )
    
    def show_message(self, title: str, message: str, type: str = "info") -> None:
        """
        显示消息框
        
        Args:
            title: 标题
            message: 消息内容
            type: 消息类型（info, warning, error, question）
        """
        message_types = {
            "info": messagebox.showinfo,
            "warning": messagebox.showwarning,
            "error": messagebox.showerror,
            "question": messagebox.askquestion
        }
        
        if type in message_types:
            message_types[type](title, message)
    
    def ask_open_file(self, title: str = "打开文件", filetypes: List[tuple] = None) -> Optional[str]:
        """
        打开文件对话框
        
        Args:
            title: 对话框标题
            filetypes: 文件类型列表，如[("文本文件", "*.txt"), ("所有文件", "*.*")]
        
        Returns:
            Optional[str]: 选中的文件路径，取消则返回None
        """
        if filetypes is None:
            filetypes = [("所有文件", "*.*")]
        
        return filedialog.askopenfilename(title=title, filetypes=filetypes)
    
    def ask_save_file(self, title: str = "保存文件", defaultextension: str = "", filetypes: List[tuple] = None) -> Optional[str]:
        """
        保存文件对话框
        
        Args:
            title: 对话框标题
            defaultextension: 默认扩展名
            filetypes: 文件类型列表
        
        Returns:
            Optional[str]: 保存的文件路径，取消则返回None
        """
        if filetypes is None:
            filetypes = [("所有文件", "*.*")]
        
        return filedialog.asksaveasfilename(title=title, defaultextension=defaultextension, filetypes=filetypes)
    
    def ask_directory(self, title: str = "选择目录") -> Optional[str]:
        """
        选择目录对话框
        
        Args:
            title: 对话框标题
        
        Returns:
            Optional[str]: 选中的目录路径，取消则返回None
        """
        return filedialog.askdirectory(title=title)
    
    def ask_string(self, title: str, prompt: str, initialvalue: str = "") -> Optional[str]:
        """
        输入字符串对话框
        
        Args:
            title: 对话框标题
            prompt: 提示信息
            initialvalue: 初始值
        
        Returns:
            Optional[str]: 输入的字符串，取消则返回None
        """
        return simpledialog.askstring(title, prompt, initialvalue=initialvalue)
    
    def ask_integer(self, title: str, prompt: str, initialvalue: int = 0, minvalue: int = 0, maxvalue: int = 100) -> Optional[int]:
        """
        输入整数对话框
        
        Args:
            title: 对话框标题
            prompt: 提示信息
            initialvalue: 初始值
            minvalue: 最小值
            maxvalue: 最大值
        
        Returns:
            Optional[int]: 输入的整数，取消则返回None
        """
        return simpledialog.askinteger(title, prompt, initialvalue=initialvalue, minvalue=minvalue, maxvalue=maxvalue)
    
    def run(self) -> None:
        """
        运行应用
        """
        self.root.mainloop()
    
    def destroy(self) -> None:
        """
        销毁应用
        """
        self.root.destroy()


class BaseFrame(ttk.Frame):
    """基础框架类"""
    
    def __init__(self, parent, padding="10"):
        """
        初始化基础框架
        
        Args:
            parent: 父组件
            padding: 内边距
        """
        super().__init__(parent, padding=padding)
    
    def create_label(self, text: str, row: int, column: int, columnspan: int = 1, sticky: str = "w", pady: int = 5) -> ttk.Label:
        """
        创建标签
        
        Args:
            text: 标签文本
            row: 行号
            column: 列号
            columnspan: 列跨度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            ttk.Label: 创建的标签组件
        """
        label = ttk.Label(self, text=text)
        label.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        return label
    
    def create_entry(self, row: int, column: int, columnspan: int = 1, width: int = 30, sticky: str = "ew", pady: int = 5) -> ttk.Entry:
        """
        创建输入框
        
        Args:
            row: 行号
            column: 列号
            columnspan: 列跨度
            width: 宽度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            ttk.Entry: 创建的输入框组件
        """
        entry = ttk.Entry(self, width=width)
        entry.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        return entry
    
    def create_button(self, text: str, command: Callable, row: int, column: int, columnspan: int = 1, sticky: str = "ew", pady: int = 5) -> ttk.Button:
        """
        创建按钮
        
        Args:
            text: 按钮文本
            command: 点击事件回调
            row: 行号
            column: 列号
            columnspan: 列跨度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            ttk.Button: 创建的按钮组件
        """
        button = ttk.Button(self, text=text, command=command)
        button.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        return button
    
    def create_text(self, row: int, column: int, columnspan: int = 1, width: int = 50, height: int = 10, sticky: str = "nsew", pady: int = 5) -> tk.Text:
        """
        创建文本框
        
        Args:
            row: 行号
            column: 列号
            columnspan: 列跨度
            width: 宽度
            height: 高度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            tk.Text: 创建的文本框组件
        """
        text = tk.Text(self, width=width, height=height, wrap=tk.WORD)
        text.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=text.yview)
        scrollbar.grid(row=row, column=column+columnspan, sticky="ns", pady=pady)
        text.config(yscrollcommand=scrollbar.set)
        
        return text
    
    def create_combobox(self, values: List[str], row: int, column: int, columnspan: int = 1, width: int = 28, sticky: str = "ew", pady: int = 5) -> ttk.Combobox:
        """
        创建下拉选择框
        
        Args:
            values: 选项列表
            row: 行号
            column: 列号
            columnspan: 列跨度
            width: 宽度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            ttk.Combobox: 创建的下拉选择框组件
        """
        combobox = ttk.Combobox(self, values=values, width=width, state="readonly")
        combobox.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        return combobox
    
    def create_listbox(self, row: int, column: int, columnspan: int = 1, width: int = 50, height: int = 10, sticky: str = "nsew", pady: int = 5) -> tk.Listbox:
        """
        创建列表框
        
        Args:
            row: 行号
            column: 列号
            columnspan: 列跨度
            width: 宽度
            height: 高度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            tk.Listbox: 创建的列表框组件
        """
        listbox = tk.Listbox(self, width=width, height=height)
        listbox.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=listbox.yview)
        scrollbar.grid(row=row, column=column+columnspan, sticky="ns", pady=pady)
        listbox.config(yscrollcommand=scrollbar.set)
        
        return listbox
    
    def create_checkbutton(self, text: str, variable: tk.Variable, row: int, column: int, columnspan: int = 1, sticky: str = "w", pady: int = 5) -> ttk.Checkbutton:
        """
        创建复选框
        
        Args:
            text: 复选框文本
            variable: 关联变量
            row: 行号
            column: 列号
            columnspan: 列跨度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            ttk.Checkbutton: 创建的复选框组件
        """
        checkbutton = ttk.Checkbutton(self, text=text, variable=variable)
        checkbutton.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        return checkbutton
    
    def create_radiobutton(self, text: str, variable: tk.Variable, value: Any, row: int, column: int, columnspan: int = 1, sticky: str = "w", pady: int = 5) -> ttk.Radiobutton:
        """
        创建单选按钮
        
        Args:
            text: 单选按钮文本
            variable: 关联变量
            value: 选项值
            row: 行号
            column: 列号
            columnspan: 列跨度
            sticky: 对齐方式
            pady: 垂直间距
        
        Returns:
            ttk.Radiobutton: 创建的单选按钮组件
        """
        radiobutton = ttk.Radiobutton(self, text=text, variable=variable, value=value)
        radiobutton.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, pady=pady)
        return radiobutton
    
    def clear(self) -> None:
        """
        清空框架内所有组件
        """
        for widget in self.winfo_children():
            widget.destroy()


class TabbedFrame(ttk.Notebook):
    """选项卡框架类"""
    
    def __init__(self, parent):
        """
        初始化选项卡框架
        
        Args:
            parent: 父组件
        """
        super().__init__(parent)
    
    def add_tab(self, title: str, frame: BaseFrame) -> None:
        """
        添加选项卡
        
        Args:
            title: 选项卡标题
            frame: 选项卡内容框架
        """
        self.add(frame, text=title)
    
    def get_current_tab(self) -> int:
        """
        获取当前选中的选项卡索引
        
        Returns:
            int: 当前选中的选项卡索引
        """
        return self.index(self.select())
    
    def set_current_tab(self, index: int) -> None:
        """
        设置当前选中的选项卡
        
        Args:
            index: 选项卡索引
        """
        self.select(index)


class StatusBar(ttk.Frame):
    """状态栏类"""
    
    def __init__(self, parent):
        """
        初始化状态栏
        
        Args:
            parent: 父组件
        """
        super().__init__(parent)
        self.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_label = ttk.Label(self, text="就绪", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, padx=10, pady=5)
    
    def set_status(self, text: str) -> None:
        """
        设置状态栏文本
        
        Args:
            text: 状态栏文本
        """
        self.status_label.config(text=text)
        self.update()
    
    def clear_status(self) -> None:
        """
        清空状态栏文本
        """
        self.status_label.config(text="就绪")
        self.update()


class MessageBox:
    """消息框类"""
    
    @staticmethod
    def info(title: str, message: str) -> None:
        """
        显示信息消息框
        
        Args:
            title: 标题
            message: 消息内容
        """
        messagebox.showinfo(title, message)
    
    @staticmethod
    def warning(title: str, message: str) -> None:
        """
        显示警告消息框
        
        Args:
            title: 标题
            message: 消息内容
        """
        messagebox.showwarning(title, message)
    
    @staticmethod
    def error(title: str, message: str) -> None:
        """
        显示错误消息框
        
        Args:
            title: 标题
            message: 消息内容
        """
        messagebox.showerror(title, message)
    
    @staticmethod
    def question(title: str, message: str) -> bool:
        """
        显示问题消息框
        
        Args:
            title: 标题
            message: 消息内容
        
        Returns:
            bool: 用户选择（是/否）
        """
        return messagebox.askyesno(title, message)


class FileDialog:
    """文件对话框类"""
    
    @staticmethod
    def open_file(title: str = "打开文件", filetypes: List[tuple] = None) -> Optional[str]:
        """
        打开文件对话框
        
        Args:
            title: 对话框标题
            filetypes: 文件类型列表
        
        Returns:
            Optional[str]: 选中的文件路径，取消则返回None
        """
        if filetypes is None:
            filetypes = [("所有文件", "*.*")]
        
        return filedialog.askopenfilename(title=title, filetypes=filetypes)
    
    @staticmethod
    def save_file(title: str = "保存文件", defaultextension: str = "", filetypes: List[tuple] = None) -> Optional[str]:
        """
        保存文件对话框
        
        Args:
            title: 对话框标题
            defaultextension: 默认扩展名
            filetypes: 文件类型列表
        
        Returns:
            Optional[str]: 保存的文件路径，取消则返回None
        """
        if filetypes is None:
            filetypes = [("所有文件", "*.*")]
        
        return filedialog.asksaveasfilename(title=title, defaultextension=defaultextension, filetypes=filetypes)
    
    @staticmethod
    def select_directory(title: str = "选择目录") -> Optional[str]:
        """
        选择目录对话框
        
        Args:
            title: 对话框标题
        
        Returns:
            Optional[str]: 选中的目录路径，取消则返回None
        """
        return filedialog.askdirectory(title=title)
