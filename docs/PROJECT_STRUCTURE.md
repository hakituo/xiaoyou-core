# 项目结构说明

## 整合后的目录结构

```
xiaoyou-core/
├── app.py                # Flask应用主入口
├── app_main.py           # 应用主程序
├── start.py              # 启动脚本
├── start_server.py       # 服务器启动脚本
├── ws_server.py          # WebSocket服务器
├── desktop_pet.py        # 桌面宠物功能
├── trm_reflector.py      # TRM反射器
├── run_llm_interactive.py # LLM交互运行脚本
├── test_model.py         # 模型测试脚本
├── test_qwen_models.py   # 千问模型测试脚本
├── md_to_format.py       # Markdown格式化工具
├── multimodal_scheduler.py # 多模态调度器
├── 
├── bots/                 # 机器人适配器
│   ├── qq_bot.py         # QQ机器人
│   └── wx_bot.py         # 微信机器人
├── 
├── core/                 # 核心功能模块
│   ├── __init__.py
│   ├── cache.py          # 缓存系统
│   ├── llm_connector.py  # LLM连接器
│   ├── model_adapter.py  # 模型适配器
│   ├── models/           # 模型定义
│   │   ├── __init__.py
│   │   └── qianwen_model.py # 千问模型
│   ├── utils.py          # 工具函数
│   └── vector_search.py  # 向量搜索
├── 
├── demo/                 # 演示示例
│   ├── demo_multimodal.py    # 多模态演示
│   └── demo_new_models.py    # 新模型演示
├── 
├── docs/                 # 文档目录
│   ├── cache_implementation.md      # 缓存实现文档
│   ├── cache_performance_report.md  # 缓存性能报告
│   ├── comprehensive_cache_documentation.md # 综合缓存文档
│   ├── GITHUB_GUIDE.md           # GitHub使用指南
│   ├── MANUAL_INSTALL_GUIDE.md   # 手动安装指南
│   ├── MODEL_DEPLOYMENT_GUIDE.md # 模型部署指南
│   ├── environments_guide.md     # 环境配置指南
│   └── PROJECT_STRUCTURE.md      # 项目结构说明（当前文件）
├── 
├── history/              # 历史记录目录
├── 
├── memory/               # 内存管理
│   ├── __init__.py
│   ├── long_term_db.py   # 长期记忆数据库
│   └── memory_manager.py # 记忆管理器
├── 
├── models/               # 模型文件目录（单独管理）
├── 
├── multimodal/           # 多模态功能（语音、视觉等）
│   ├── stt_connector.py  # 语音识别连接器
│   ├── tts_manager.py    # 语音合成管理器
│   └── voice/            # 语音相关功能
├── 
├── paper/                # 项目论文和实验资料
│   ├── CN/               # 中文资料
│   ├── EN/               # 英文资料
│   ├── experiment/       # 实验相关
│   ├── paper.pdf         # 论文PDF
│   └── paper.tex         # 论文LaTeX源码
├── 
├── requirements/         # 依赖要求
│   └── requirements.txt
├── 
├── scripts/              # 脚本文件
│   ├── setup_env.ps1            # 环境设置脚本
│   ├── simple_check.ps1         # 简单检查脚本
│   ├── simple_sdk_download.py   # SDK下载脚本
│   ├── run_local.bat            # 本地运行批处理
│   └── pytorch_install_commands.txt # PyTorch安装命令
├── 
├── static/               # 静态资源
│   ├── css/              # CSS样式
│   ├── generated/        # 生成的资源
│   ├── images/           # 图片资源
│   ├── lottie/           # Lottie动画
│   ├── script.js         # JavaScript脚本
│   └── style.css         # 样式表
├── 
├── templates/            # 模板文件
│   ├── error.html        # 错误页面
│   └── ultimate_xiaoyou_optimized.html # 主页面模板
├── 
├── tests/                # 测试代码
│   ├── __init__.py
│   └── test_cache.py     # 缓存测试
└── 
    ├── venv_img/         # 图片处理虚拟环境
    ├── venv_llm/         # LLM处理虚拟环境
    ├── venv_new/         # 新功能虚拟环境
    └── venv_multimodal/  # 多模态处理虚拟环境
```

## 目录功能说明

- **bots/**: 包含各种聊天平台的机器人适配器
- **core/**: 核心功能模块，包含缓存、模型连接、向量搜索等
- **demo/**: 演示示例代码，展示各种功能的使用方法
- **docs/**: 项目文档，包含安装指南、部署说明、性能报告等
- **history/**: 存储聊天历史记录
- **memory/**: 记忆管理系统，包含短期和长期记忆功能
- **models/**: AI模型文件存储目录
- **multimodal/**: 多模态功能，包含语音识别和合成
- **paper/**: 项目相关的论文和实验资料
- **requirements/**: 项目依赖要求文件
- **scripts/**: 各种实用脚本，用于环境设置、模型下载等
- **static/**: Web界面的静态资源文件
- **templates/**: Web界面的HTML模板文件
- **tests/**: 自动化测试代码
- **venv_**: 各种功能的虚拟环境目录

## 文件命名规范

- 模块和功能文件：使用小写字母和下划线组合，如 `llm_connector.py`
- 测试文件：以 `test_` 开头，如 `test_cache.py`
- 演示文件：以 `demo_` 开头，如 `demo_multimodal.py`
- 配置文件：清晰表明用途，如 `model_config.py`

## 后续优化建议

1. 考虑将虚拟环境移至项目外，通过符号链接引用
2. 为每个主要模块创建详细的README文件
3. 建立统一的日志目录和配置
4. 实现自动化测试流程
5. 优化模型文件的组织和管理