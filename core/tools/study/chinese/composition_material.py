#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作文素材分类管理器
支持3级分类架构，多关键词检索，素材应用段落生成等功能
"""

import os
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
from ..common.utils import filter_list_by_keywords, normalize_string
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class CompositionMaterial:
    """作文素材管理类"""
    
    def __init__(self):
        """初始化作文素材管理器"""
        self.materials = []  # 素材列表
        self.categories = {
            "大类": {},
            "子主题": {},
            "素材类型": {}
        }  # 3级分类架构
        
        # 初始化默认分类
        self._init_default_categories()
        
        # 素材使用频率统计
        self.usage_stats = {}
    
    def _init_default_categories(self):
        """初始化默认分类架构"""
        # 主题大类
        self.categories["大类"] = {
            "坚持": [],
            "创新": [],
            "家国情怀": [],
            "责任担当": [],
            "理想信念": [],
            "科学精神": [],
            "人文关怀": [],
            "生态文明": [],
            "文化传承": [],
            "时代精神": []
        }
        
        # 子主题示例
        self.categories["子主题"] = {
            "坚持": ["个人坚持", "团队坚持", "历史坚持"],
            "创新": ["科技创新", "文化创新", "制度创新"],
            "家国情怀": ["爱国主义", "家乡情怀", "民族精神"]
        }
        
        # 素材类型
        self.categories["素材类型"] = {
            "事例素材": [],
            "名言素材": [],
            "数据素材": [],
            "理论素材": [],
            "文学素材": []
        }
    
    def add_material(self, material: Dict[str, Any]) -> bool:
        """
        添加素材
        
        Args:
            material: 素材数据
        
        Returns:
            bool: 添加是否成功
        """
        try:
            # 验证必填字段
            required_fields = ["标题", "核心内容", "出处", "适用文体", "关键词标签"]
            if not all(field in material for field in required_fields):
                return False
            
            # 生成唯一ID
            material["id"] = f"mat_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000, 9999)}"
            
            # 添加默认字段
            material["创建时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            material["修改时间"] = material["创建时间"]
            material["使用频率"] = 0
            material["个人标注"] = ""
            material["修改记录"] = []
            
            # 规范化字段
            for field in material:
                if isinstance(material[field], str):
                    material[field] = normalize_string(material[field])
            
            # 更新分类
            self._update_category(material)
            
            self.materials.append(material)
            return True
        except Exception as e:
            print(f"添加素材失败: {e}")
            return False
    
    def _update_category(self, material: Dict[str, Any]):
        """
        更新分类架构
        
        Args:
            material: 素材数据
        """
        # 更新大类
        category = material.get("主题大类", "")
        if category and category not in self.categories["大类"]:
            self.categories["大类"][category] = []
        
        # 更新子主题
        sub_category = material.get("子主题", "")
        if sub_category:
            if category and sub_category not in self.categories["子主题"].get(category, []):
                if category not in self.categories["子主题"]:
                    self.categories["子主题"][category] = []
                self.categories["子主题"][category].append(sub_category)
        
        # 更新素材类型
        material_type = material.get("素材类型", "")
        if material_type and material_type not in self.categories["素材类型"]:
            self.categories["素材类型"][material_type] = []
    
    def search_materials(self, keywords: List[str], categories: Dict[str, str] = None, sort_by_usage: bool = False) -> List[Dict[str, Any]]:
        """
        搜索素材
        
        Args:
            keywords: 关键词列表
            categories: 分类筛选
            sort_by_usage: 是否按使用频率排序
        
        Returns:
            List[Dict[str, Any]]: 搜索结果
        """
        # 先按关键词过滤
        result = filter_list_by_keywords(
            self.materials,
            keywords,
            ["标题", "核心内容", "出处", "适用文体", "关键词标签", "个人标注"]
        )
        
        # 再按分类过滤
        if categories:
            filtered = []
            for material in result:
                match = True
                for cat_type, cat_value in categories.items():
                    if cat_value and material.get(cat_type, "") != cat_value:
                        match = False
                        break
                if match:
                    filtered.append(material)
            result = filtered
        
        # 按使用频率排序
        if sort_by_usage:
            result.sort(key=lambda x: x.get("使用频率", 0), reverse=True)
        
        return result
    
    def generate_application_paragraph(self, material_id: str, theme: str = "") -> str:
        """
        生成素材应用段落
        
        Args:
            material_id: 素材ID
            theme: 应用主题
        
        Returns:
            str: 生成的应用段落
        """
        # 查找素材
        material = next((m for m in self.materials if m["id"] == material_id), None)
        if not material:
            return ""
        
        # 增加使用频率
        material["使用频率"] += 1
        self.usage_stats[material_id] = self.usage_stats.get(material_id, 0) + 1
        
        # 生成应用段落
        title = material["标题"]
        content = material["核心内容"]
        applicable_style = material["适用文体"]
        
        if theme:
            paragraph = f"在{theme}主题下，{title}的事例极具说服力。{content}这一素材生动展现了{theme}的内涵，"
            paragraph += f"适合用于{applicable_style}中，能够有效增强文章的论证力度，引发读者共鸣。"
        else:
            paragraph = f"{title}是一则典型的作文素材。{content}这一内容展现了深刻的思想内涵，"
            paragraph += f"适合用于{applicable_style}等文体中，能够为文章增添丰富的内容支撑和思想深度。"
        
        # 调整段落长度在100-200字
        if len(paragraph) > 200:
            paragraph = paragraph[:197] + "..."
        elif len(paragraph) < 100:
            paragraph += " 这一素材不仅具有鲜明的时代特色，还蕴含着深刻的人生哲理，值得我们深入思考和借鉴。"
            if len(paragraph) < 100:
                paragraph += " 在写作中巧妙运用这一素材，能够使文章更加生动有力，富有感染力。"
        
        return paragraph
    
    def import_materials(self, data: List[Dict[str, Any]]) -> int:
        """
        批量导入素材
        
        Args:
            data: 素材数据列表
        
        Returns:
            int: 成功导入的数量
        """
        success_count = 0
        
        for item in data:
            if self.add_material(item):
                success_count += 1
        
        return success_count
    
    def export_materials(self, materials: List[Dict[str, Any]], file_path: str) -> bool:
        """
        导出素材
        
        Args:
            materials: 要导出的素材列表
            file_path: 文件路径
        
        Returns:
            bool: 导出是否成功
        """
        try:
            DataIO.export_data(materials, file_path, title="作文素材导出")
            return True
        except Exception as e:
            print(f"导出素材失败: {e}")
            return False
    
    def update_material(self, material_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新素材
        
        Args:
            material_id: 素材ID
            updates: 更新的字段
        
        Returns:
            bool: 更新是否成功
        """
        # 查找素材
        for material in self.materials:
            if material["id"] == material_id:
                # 记录修改前的数据
                old_data = material.copy()
                
                # 更新字段
                for field, value in updates.items():
                    if field in material and field != "id" and field != "创建时间":
                        if isinstance(value, str):
                            value = normalize_string(value)
                        material[field] = value
                
                # 更新修改时间
                material["修改时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 添加修改记录
                material["修改记录"].append({
                    "修改时间": material["修改时间"],
                    "修改内容": {k: v for k, v in updates.items() if k in material}
                })
                
                # 更新分类
                self._update_category(material)
                
                return True
        
        return False
    
    def delete_material(self, material_id: str) -> bool:
        """
        删除素材
        
        Args:
            material_id: 素材ID
        
        Returns:
            bool: 删除是否成功
        """
        # 查找素材索引
        for i, material in enumerate(self.materials):
            if material["id"] == material_id:
                del self.materials[i]
                # 更新使用频率统计
                if material_id in self.usage_stats:
                    del self.usage_stats[material_id]
                return True
        
        return False
    
    def get_material_by_id(self, material_id: str) -> Optional[Dict[str, Any]]:
        """
        根据ID获取素材
        
        Args:
            material_id: 素材ID
        
        Returns:
            Optional[Dict[str, Any]]: 素材数据
        """
        return next((m for m in self.materials if m["id"] == material_id), None)
    
    def get_all_materials(self) -> List[Dict[str, Any]]:
        """
        获取所有素材
        
        Returns:
            List[Dict[str, Any]]: 素材列表
        """
        return self.materials.copy()
    
    def get_categories(self) -> Dict[str, Any]:
        """
        获取分类架构
        
        Returns:
            Dict[str, Any]: 分类架构
        """
        return self.categories.copy()
    
    def get_materials_by_category(self, category_type: str, category_value: str) -> List[Dict[str, Any]]:
        """
        根据分类获取素材
        
        Args:
            category_type: 分类类型
            category_value: 分类值
        
        Returns:
            List[Dict[str, Any]]: 素材列表
        """
        if category_type not in ["大类", "子主题", "素材类型"]:
            return []
        
        if category_type == "大类":
            return [m for m in self.materials if m.get("主题大类") == category_value]
        elif category_type == "子主题":
            return [m for m in self.materials if m.get("子主题") == category_value]
        else:
            return [m for m in self.materials if m.get("素材类型") == category_value]
    
    def batch_delete_materials(self, material_ids: List[str]) -> int:
        """
        批量删除素材
        
        Args:
            material_ids: 素材ID列表
        
        Returns:
            int: 成功删除的数量
        """
        delete_count = 0
        
        for material_id in material_ids:
            if self.delete_material(material_id):
                delete_count += 1
        
        return delete_count
    
    def load_materials_from_file(self, file_path: str) -> int:
        """
        从文件加载素材
        
        Args:
            file_path: 文件路径
        
        Returns:
            int: 成功加载的数量
        """
        try:
            data = DataIO.import_data(file_path)
            return self.import_materials(data)
        except Exception as e:
            print(f"从文件加载素材失败: {e}")
            return 0


class CompositionMaterialGUI(GUIApp):
    """作文素材管理器GUI界面"""
    
    def __init__(self):
        """
        初始化GUI界面
        """
        super().__init__("作文素材分类管理器", width=1000, height=700)
        self.material_manager = CompositionMaterial()
        self.current_material = None
        
        # 创建主界面
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导入素材", "command": self.import_materials},
            {"label": "导出素材", "command": self.export_materials},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
        
        self.add_menu("素材", [
            {"label": "添加素材", "command": self.add_material},
            {"label": "编辑素材", "command": self.edit_material},
            {"label": "删除素材", "command": self.delete_material},
            {"separator": True},
            {"label": "生成应用段落", "command": self.generate_application}
        ])
    
    def create_main_frame(self):
        """
        创建主界面
        """
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 左侧：分类和搜索区域
        left_frame = BaseFrame(self.main_frame, padding="5")
        left_frame.pack(side=tk.LEFT, fill=tk.Y, width=250)
        
        # 右侧：素材列表和详情区域
        right_frame = BaseFrame(self.main_frame, padding="5")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 分类显示
        left_frame.create_label("分类架构", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        
        # 大类选择
        left_frame.create_label("主题大类：", 1, 0, sticky="w", pady=5)
        self.category_var = tk.StringVar(value="")
        categories = list(self.material_manager.categories["大类"].keys())
        category_combo = left_frame.create_combobox(categories, 1, 1, width=20)
        category_combo.config(textvariable=self.category_var, postcommand=self.update_subcategories)
        category_combo.bind("<<ComboboxSelected>>", self.on_category_select)
        
        # 子主题选择
        left_frame.create_label("子主题：", 2, 0, sticky="w", pady=5)
        self.subcategory_var = tk.StringVar(value="")
        self.subcategory_combo = left_frame.create_combobox([], 2, 1, width=20)
        self.subcategory_combo.config(textvariable=self.subcategory_var)
        self.subcategory_combo.bind("<<ComboboxSelected>>", self.on_subcategory_select)
        
        # 素材类型选择
        left_frame.create_label("素材类型：", 3, 0, sticky="w", pady=5)
        self.type_var = tk.StringVar(value="")
        types = list(self.material_manager.categories["素材类型"].keys())
        type_combo = left_frame.create_combobox(types, 3, 1, width=20)
        type_combo.config(textvariable=self.type_var)
        type_combo.bind("<<ComboboxSelected>>", self.on_type_select)
        
        # 关键词搜索
        left_frame.create_label("关键词搜索：", 4, 0, sticky="w", pady=10)
        self.keyword_entry = left_frame.create_entry(4, 1, width=20)
        self.search_button = left_frame.create_button("搜索", self.search_materials, 5, 0, columnspan=2, pady=5)
        
        # 按使用频率排序
        self.sort_by_usage_var = tk.BooleanVar(value=False)
        left_frame.create_checkbutton("按使用频率排序", self.sort_by_usage_var, 6, 0, columnspan=2, sticky="w", pady=5)
        
        # 素材列表
        right_frame.create_label("素材列表", 0, 0, sticky="w", font=(".SF NS Text", 12, "bold"))
        
        # 列表框
        self.material_listbox = right_frame.create_listbox(1, 0, height=20, sticky="nsew")
        self.material_listbox.bind("<<ListboxSelect>>", self.on_material_select)
        
        # 素材详情
        right_frame.create_label("素材详情", 2, 0, sticky="w", font=(".SF NS Text", 12, "bold"), pady=10)
        
        # 详情显示区域
        self.detail_text = right_frame.create_text(3, 0, width=80, height=15, sticky="nsew")
        
        # 操作按钮
        button_frame = BaseFrame(right_frame, padding="5")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        
        self.add_button = button_frame.create_button("添加素材", self.add_material, 0, 0, sticky="w")
        self.edit_button = button_frame.create_button("编辑素材", self.edit_material, 0, 1, sticky="w", padx=10)
        self.delete_button = button_frame.create_button("删除素材", self.delete_material, 0, 2, sticky="w", padx=10)
        self.generate_button = button_frame.create_button("生成应用段落", self.generate_application, 0, 3, sticky="w", padx=10)
        
        # 批量操作按钮
        self.batch_import_button = button_frame.create_button("批量导入", self.import_materials, 0, 4, sticky="w", padx=10)
        self.batch_export_button = button_frame.create_button("批量导出", self.export_materials, 0, 5, sticky="w", padx=10)
        
        # 更新素材列表
        self.update_material_list()
    
    def update_subcategories(self):
        """
        更新子主题列表
        """
        category = self.category_var.get()
        if category in self.material_manager.categories["子主题"]:
            subcategories = self.material_manager.categories["子主题"][category]
        else:
            subcategories = []
        
        self.subcategory_combo.config(values=subcategories)
        self.subcategory_var.set("")
    
    def on_category_select(self, event=None):
        """
        主题大类选择事件
        """
        self.update_subcategories()
        self.search_materials()
    
    def on_subcategory_select(self, event=None):
        """
        子主题选择事件
        """
        self.search_materials()
    
    def on_type_select(self, event=None):
        """
        素材类型选择事件
        """
        self.search_materials()
    
    def update_material_list(self, materials: List[Dict[str, Any]] = None):
        """
        更新素材列表
        
        Args:
            materials: 要显示的素材列表，None表示显示所有
        """
        # 清空列表
        self.material_listbox.delete(0, tk.END)
        
        if materials is None:
            materials = self.material_manager.get_all_materials()
        
        # 添加到列表
        for material in materials:
            self.material_listbox.insert(tk.END, f"{material['标题']} - {material.get('主题大类', '')}")
        
        # 保存当前显示的素材
        self.current_displayed_materials = materials
    
    def on_material_select(self, event=None):
        """
        素材选择事件
        """
        selection = self.material_listbox.curselection()
        if selection:
            index = selection[0]
            if 0 <= index < len(self.current_displayed_materials):
                self.current_material = self.current_displayed_materials[index]
                self.show_material_detail(self.current_material)
    
    def show_material_detail(self, material: Dict[str, Any]):
        """
        显示素材详情
        
        Args:
            material: 素材数据
        """
        self.detail_text.delete("1.0", tk.END)
        
        detail = "素材详情：\n\n"
        for field, value in material.items():
            if isinstance(value, list) and value:
                detail += f"{field}：\n"
                for item in value:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            detail += f"  {k}：{v}\n"
                    else:
                        detail += f"  {item}\n"
            else:
                detail += f"{field}：{value}\n"
        
        self.detail_text.insert(tk.END, detail)
    
    def search_materials(self):
        """
        搜索素材
        """
        # 获取搜索条件
        keywords = self.keyword_entry.get().strip().split()
        category = self.category_var.get()
        subcategory = self.subcategory_var.get()
        material_type = self.type_var.get()
        sort_by_usage = self.sort_by_usage_var.get()
        
        # 构建分类筛选
        categories = {
            "主题大类": category,
            "子主题": subcategory,
            "素材类型": material_type
        }
        
        # 搜索素材
        results = self.material_manager.search_materials(keywords, categories, sort_by_usage)
        
        # 更新列表
        self.update_material_list(results)
    
    def add_material(self):
        """
        添加素材
        """
        # 创建添加素材窗口
        add_window = tk.Toplevel(self.root)
        add_window.title("添加素材")
        add_window.geometry("600x500")
        add_window.resizable(True, True)
        
        # 创建添加素材框架
        add_frame = BaseFrame(add_window, padding="10")
        add_frame.pack(fill=tk.BOTH, expand=True)
        
        # 素材字段
        fields = [
            ("标题", tk.Entry, 0, 0, 50),
            ("主题大类", ttk.Combobox, 1, 0, 48, list(self.material_manager.categories["大类"].keys())),
            ("子主题", ttk.Combobox, 2, 0, 48, []),
            ("素材类型", ttk.Combobox, 3, 0, 48, list(self.material_manager.categories["素材类型"].keys())),
            ("核心内容", tk.Text, 4, 0, 50, 5),
            ("出处", tk.Entry, 5, 0, 50),
            ("适用文体", tk.Entry, 6, 0, 50),
            ("关键词标签", tk.Entry, 7, 0, 50),
            ("个人标注", tk.Text, 8, 0, 50, 3)
        ]
        
        # 创建字段组件
        field_widgets = {}
        for field_name, widget_type, row, column, width, *args in fields:
            add_frame.create_label(f"{field_name}：", row, column, sticky="w", pady=5)
            
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
        
        # 绑定主题大类变化事件
        def update_subcategories(*args):
            category = field_widgets["主题大类"].get()
            if category in self.material_manager.categories["子主题"]:
                field_widgets["子主题"].config(values=self.material_manager.categories["子主题"][category])
            else:
                field_widgets["子主题"].config(values=[])
        field_widgets["主题大类"].bind("<<ComboboxSelected>>", update_subcategories)
        
        # 确定按钮
        def confirm_add():
            # 收集素材数据
            material_data = {}
            for field_name, widget in field_widgets.items():
                if isinstance(widget, tk.Entry) or isinstance(widget, ttk.Combobox):
                    material_data[field_name] = widget.get()
                elif isinstance(widget, tk.Text):
                    material_data[field_name] = widget.get("1.0", tk.END).strip()
            
            # 添加素材
            if self.material_manager.add_material(material_data):
                MessageBox.info("成功", "素材添加成功")
                add_window.destroy()
                self.update_material_list()
            else:
                MessageBox.error("失败", "素材添加失败，请检查必填字段")
        
        confirm_button = ttk.Button(add_frame, text="确定添加", command=confirm_add)
        confirm_button.grid(row=9, column=0, columnspan=2, pady=10, sticky="ew")
        
        # 取消按钮
        cancel_button = ttk.Button(add_frame, text="取消", command=add_window.destroy)
        cancel_button.grid(row=9, column=2, pady=10, sticky="ew")
    
    def edit_material(self):
        """
        编辑素材
        """
        if not self.current_material:
            MessageBox.warning("提示", "请先选择要编辑的素材")
            return
        
        # 创建编辑素材窗口
        edit_window = tk.Toplevel(self.root)
        edit_window.title("编辑素材")
        edit_window.geometry("600x500")
        edit_window.resizable(True, True)
        
        # 创建编辑素材框架
        edit_frame = BaseFrame(edit_window, padding="10")
        edit_frame.pack(fill=tk.BOTH, expand=True)
        
        # 素材字段
        fields = [
            ("标题", tk.Entry, 0, 0, 50),
            ("主题大类", ttk.Combobox, 1, 0, 48, list(self.material_manager.categories["大类"].keys())),
            ("子主题", ttk.Combobox, 2, 0, 48, []),
            ("素材类型", ttk.Combobox, 3, 0, 48, list(self.material_manager.categories["素材类型"].keys())),
            ("核心内容", tk.Text, 4, 0, 50, 5),
            ("出处", tk.Entry, 5, 0, 50),
            ("适用文体", tk.Entry, 6, 0, 50),
            ("关键词标签", tk.Entry, 7, 0, 50),
            ("个人标注", tk.Text, 8, 0, 50, 3)
        ]
        
        # 创建字段组件并填充数据
        field_widgets = {}
        for field_name, widget_type, row, column, width, *args in fields:
            edit_frame.create_label(f"{field_name}：", row, column, sticky="w", pady=5)
            
            if widget_type == tk.Entry:
                widget = tk.Entry(edit_frame, width=width)
                widget.insert(0, self.current_material.get(field_name, ""))
                widget.grid(row=row, column=column+1, sticky="ew", pady=5)
            elif widget_type == ttk.Combobox:
                values = args[0] if args else []
                widget = ttk.Combobox(edit_frame, values=values, width=width-2, state="readonly")
                widget.set(self.current_material.get(field_name, ""))
                widget.grid(row=row, column=column+1, sticky="ew", pady=5)
            elif widget_type == tk.Text:
                height = args[0] if args else 3
                widget = tk.Text(edit_frame, width=width, height=height, wrap=tk.WORD)
                widget.insert("1.0", self.current_material.get(field_name, ""))
                widget.grid(row=row, column=column+1, sticky="ew", pady=5)
                
                # 添加滚动条
                scrollbar = ttk.Scrollbar(edit_frame, orient=tk.VERTICAL, command=widget.yview)
                scrollbar.grid(row=row, column=column+2, sticky="ns", pady=5)
                widget.config(yscrollcommand=scrollbar.set)
            
            field_widgets[field_name] = widget
        
        # 绑定主题大类变化事件
        def update_subcategories(*args):
            category = field_widgets["主题大类"].get()
            if category in self.material_manager.categories["子主题"]:
                field_widgets["子主题"].config(values=self.material_manager.categories["子主题"][category])
            else:
                field_widgets["子主题"].config(values=[])
        field_widgets["主题大类"].bind("<<ComboboxSelected>>", update_subcategories)
        update_subcategories()  # 初始化子主题
        
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
                if new_value != self.current_material.get(field_name, ""):
                    update_data[field_name] = new_value
            
            # 更新素材
            if update_data:
                if self.material_manager.update_material(self.current_material["id"], update_data):
                    MessageBox.info("成功", "素材更新成功")
                    edit_window.destroy()
                    self.update_material_list()
                    # 更新当前素材和详情
                    self.current_material = self.material_manager.get_material_by_id(self.current_material["id"])
                    self.show_material_detail(self.current_material)
                else:
                    MessageBox.error("失败", "素材更新失败")
            else:
                MessageBox.info("提示", "没有修改任何内容")
                edit_window.destroy()
        
        confirm_button = ttk.Button(edit_frame, text="确定更新", command=confirm_edit)
        confirm_button.grid(row=9, column=0, columnspan=2, pady=10, sticky="ew")
        
        # 取消按钮
        cancel_button = ttk.Button(edit_frame, text="取消", command=edit_window.destroy)
        cancel_button.grid(row=9, column=2, pady=10, sticky="ew")
    
    def delete_material(self):
        """
        删除素材
        """
        if not self.current_material:
            MessageBox.warning("提示", "请先选择要删除的素材")
            return
        
        if MessageBox.question("确认", f"确定要删除素材 '{self.current_material['标题']}' 吗？"):
            if self.material_manager.delete_material(self.current_material["id"]):
                MessageBox.info("成功", "素材删除成功")
                self.update_material_list()
                self.current_material = None
                self.detail_text.delete("1.0", tk.END)
            else:
                MessageBox.error("失败", "素材删除失败")
    
    def generate_application(self):
        """
        生成应用段落
        """
        if not self.current_material:
            MessageBox.warning("提示", "请先选择要生成应用段落的素材")
            return
        
        # 创建生成应用段落窗口
        app_window = tk.Toplevel(self.root)
        app_window.title("生成素材应用段落")
        app_window.geometry("500x300")
        app_window.resizable(True, True)
        
        # 创建框架
        app_frame = BaseFrame(app_window, padding="10")
        app_frame.pack(fill=tk.BOTH, expand=True)
        
        # 主题输入
        app_frame.create_label("应用主题（可选）：", 0, 0, sticky="w", pady=5)
        theme_entry = app_frame.create_entry(0, 1, width=40)
        
        # 生成按钮
        def generate_paragraph():
            theme = theme_entry.get().strip()
            paragraph = self.material_manager.generate_application_paragraph(self.current_material["id"], theme)
            
            # 显示生成的段落
            result_text.delete("1.0", tk.END)
            result_text.insert(tk.END, paragraph)
        
        generate_button = app_frame.create_button("生成段落", generate_paragraph, 0, 2, sticky="w", padx=10)
        
        # 结果显示
        app_frame.create_label("生成的应用段落：", 1, 0, sticky="w", pady=10)
        result_text = app_frame.create_text(2, 0, columnspan=3, width=60, height=10, sticky="nsew")
        
        # 复制按钮
        def copy_to_clipboard():
            paragraph = result_text.get("1.0", tk.END).strip()
            if paragraph:
                self.root.clipboard_clear()
                self.root.clipboard_append(paragraph)
                MessageBox.info("成功", "段落已复制到剪贴板")
        
        copy_button = app_frame.create_button("复制到剪贴板", copy_to_clipboard, 3, 0, columnspan=3, sticky="ew", pady=10)
    
    def import_materials(self):
        """
        导入素材
        """
        # 选择文件
        file_path = FileDialog.open_file(
            title="导入素材",
            filetypes=[("Excel文件", "*.xlsx;*.xls"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        
        if file_path:
            success_count = self.material_manager.load_materials_from_file(file_path)
            if success_count > 0:
                MessageBox.info("成功", f"成功导入 {success_count} 条素材")
                self.update_material_list()
            else:
                MessageBox.error("失败", "导入失败，请检查文件格式")
    
    def export_materials(self):
        """
        导出素材
        """
        # 选择导出的素材（当前显示的或所有）
        materials_to_export = self.current_displayed_materials
        
        if not materials_to_export:
            MessageBox.warning("提示", "没有素材可以导出")
            return
        
        # 选择保存路径
        file_path = FileDialog.save_file(
            title="导出素材",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("Word文件", "*.docx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            if self.material_manager.export_materials(materials_to_export, file_path):
                MessageBox.info("成功", f"成功导出 {len(materials_to_export)} 条素材")
            else:
                MessageBox.error("失败", "导出失败")