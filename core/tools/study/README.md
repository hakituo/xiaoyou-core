# Xiaoyou Core Study Tools

这里是小优核心学习工具集，包含了针对高考各学科的实用辅助脚本。这些工具旨在帮助学生更高效地进行知识管理、练习和复习。

所有工具均支持 GUI 图形界面操作，也可以作为模块被其他程序调用。

## 目录结构

```
core/tools/study/
├── biology/           # 生物学科工具
├── chinese/           # 语文学科工具
├── english/           # 英语学科工具
├── geography/         # 地理学科工具
├── math/              # 数学学科工具
├── common/            # 通用工具库
└── README.md          # 本文档
```

## 各学科工具详解

### 1. 英语 (English)

*   **`english/vocabulary_manager.py` (核心单词管理)**
    *   **功能**：基于 **SM-2 间隔重复算法** (Spaced Repetition) 的背单词引擎。
    *   **特点**：科学计算复习时间，支持导入外部词库，追踪学习进度。
    *   **数据**：默认加载高考/四六级核心词汇。
    *   **联动**：为 `ChatAgent` 提供每日单词推送服务。

*   **`english/vocab_tester.py` (单词测试器)**
    *   **功能**：独立的单词测试 GUI 程序。
    *   **特点**：**与 VocabularyManager 统一后端**，测试结果直接计入记忆曲线。
    *   **模式**：支持“看词选义”、“看义写词”等多种测试模式。
    *   **启动**：`python core/tools/study/english/vocab_tester.py`

*   **`english/grammar_checker.py` (语法检测器)**
    *   **功能**：基于 `language_tool_python` 的英语语法错误自动检测工具。
    *   **特点**：专为中国学生优化，特别检测“中式英语”错误。
    *   **检测项**：时态、主谓一致、冠词、介词、从句连接词等 15 类常见错误。
    *   **输出**：提供详细的错误分析报告和修改建议。

### 2. 数学 (Math)

*   **`math/problem_generator.py` (基础题型生成器)**
    *   **功能**：自动生成数学基础练习题。
    *   **覆盖模块**：三角函数、立体几何、概率统计、导数、解析几何。
    *   **特点**：支持难度分级（基础/中档/难题），支持导出题目、答案及分步解析。

*   **`math/math_image_generator.py` (数学图像生成器)**
    *   **功能**：自动绘制高质量的数学函数图像和几何体。
    *   **类型**：立体几何（长方体、球体等）、三角函数、圆锥曲线（椭圆、双曲线等）。
    *   **用途**：辅助理解几何关系，生成复习资料插图。

*   **`math/error_analysis.py` (错题分析器)**
    *   **功能**：数学错题整理与归因分析工具。
    *   **特点**：支持按知识点（如数列、向量）和错误原因（如计算错误、思路偏差）分类统计。
    *   **可视化**：生成图表展示薄弱环节。

### 3. 语文 (Chinese)

*   **`chinese/poetry_quiz.py` (古诗文默写抽查)**
    *   **功能**：高考必背古诗文随机挖空测试。
    *   **特点**：支持关键字挖空模式，自动统计易错字，强化记忆。

*   **`chinese/composition_material.py` (作文素材管理)**
    *   **功能**：作文素材的分类管理与检索工具。
    *   **架构**：三级分类（大类-子主题-类型），支持多关键词检索。
    *   **预设**：内置“坚持”、“创新”、“家国情怀”等常见高考作文主题分类。

### 4. 生物 (Biology)

*   **`biology/genetics_calculator.py` (遗传概率计算器)**
    *   **功能**：解决复杂的遗传学概率计算问题。
    *   **能力**：支持单/双/三基因杂交计算，自动生成棋盘图，计算表现型/基因型比例。

*   **`biology/concept_comparison.py` (易混概念对比)**
    *   **功能**：生物易混淆概念的对比记忆工具。
    *   **模式**：支持选择题、判断题等测试模式，生成对比记忆卡片。

### 5. 地理 (Geography)

*   **`geography/contour_simulator.py` (等值线模拟器)**
    *   **功能**：交互式等高线/等压线/等温线图模拟。
    *   **特点**：支持地形类型切换（山地/盆地等），直观演示地形特征判读。

*   **`geography/climate_judger.py` (气候类型判断)**
    *   **功能**：基于气温和降水数据的气候类型自动判断工具。
    *   **特点**：内置详细的判断规则库（以温定带、以水定型），提供核心特征和高考考点解析。

## 通用模块 (Common)

*   **`common/gui_base.py`**：封装了统一的 Tkinter GUI 基类，确保所有工具界面风格一致。
*   **`common/data_io.py`**：统一的数据导入导出接口，支持 JSON, Excel, CSV, TXT 等格式。
*   **`common/utils.py`**：通用工具函数库。

## 使用方法

### 命令行/独立运行
所有带有 GUI 的工具均可直接作为脚本运行。例如启动数学错题分析器：
```bash
python core/tools/study/math/error_analysis.py
```

### 模块调用
在其他 Python 代码中导入并使用：
```python
from core.tools.study.english.vocabulary_manager import VocabularyManager

vm = VocabularyManager()
daily_words = vm.get_daily_words(limit=20)
print(daily_words)
```
