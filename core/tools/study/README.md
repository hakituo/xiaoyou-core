# Study Tools Module

此模块包含了辅助学习的各种工具脚本，主要分为以下几个部分：

## 1. Core Tools (`core/tools/study/`)

- **study_tools.py**: 
  - 定义并注册了所有学习相关的 Agent Tools (LangChain Tools)。
  - 包括 `MathPlotTool` (函数绘图), `FileCreationTool` (文件生成), `TextToSpeechTool` (语音合成), `KnowledgeRetrievalTool` (知识库检索), `UpdateWordProgressTool` (单词进度更新)。

## 2. English Learning (`core/tools/study/english/`)

- **vocabulary_manager.py**: 
  - 核心单词管理模块。
  - 实现了 **SM-2 间隔重复算法** (Spaced Repetition) 用于科学背单词。
  - 管理词库加载、每日单词推送、进度追踪。
  - 支持导入外部词表 (Excel/TXT)。

- **vocab_tester.py**: 
  - 单词测试 GUI 界面。
  - 这是一个独立的图形化程序，可以直接运行用于自测。
  - **已与 VocabularyManager 统一后端**：它现在直接使用 `vocabulary_manager.py` 的数据和算法，测试结果会同步更新到用户的记忆曲线中。
  - 支持“看词选义”和“看义写词”模式。

## 3. Common Utilities (`core/tools/study/common/`)

- **data_io.py**: 数据导入导出工具，支持 JSON, Excel, TXT 等格式。
- **gui_base.py**: GUI 基础类库 (基于 Tkinter)。
- **utils.py**: 通用工具函数。

## 使用说明

### 启动单词测试器
直接运行脚本即可启动 GUI：
```bash
python core/tools/study/english/vocab_tester.py
```

### 每日单词推送机制
`ChatAgent` 会自动调用 `VocabularyManager` 获取每日单词，并在对话中自然地推送给用户。用户对单词的反馈（记得/忘记）会通过 `UpdateWordProgressTool` 回写到进度文件中。

### 数据存储
用户的学习进度数据存储在 `output/user_data/vocab_progress.json`。
