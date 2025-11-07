# XiaoYou AI (xiaoyou-core)

**A lightweight, high-performance AI chat assistant core system, optimized for low-spec computers.** Supports WebSocket real-time communication, smart memory management, voice synthesis, and multi-platform integration.

---

## 🌟 Features

### Core Features

* **Multi-platform integration**: Web interface ready, with hooks for QQ and WeChat integration
* **Real-time communication**: Efficient asynchronous messaging via WebSocket
* **Smart memory system**

  * Short-term context memory (configurable length & priority)
  * Automatic/manual history saving and loading
  * Importance-based memory pruning
  * Long-term memory storage in database
* **Voice synthesis**: Dual-engine support (Edge TTS cloud service + pyttsx3 offline backup)
* **System integration**: Real-time system monitoring and resource management
* **Performance optimized**: Runs smoothly even on low-spec computers

### Resource Optimization

* Lazy-load non-core dependencies to reduce startup time & memory usage
* Smart caching using LRU algorithm
* Strict memory monitoring & limits
* Automatic garbage collection & resource cleanup

### Data Handling

* Default history length: 10 messages (adjustable)
* Importance-based pruning
* Text length limits to avoid overuse
* Batch processing & async handling of heavy tasks

### Connections & Concurrency

* WebSocket heartbeat every 30s, 60s timeout
* Default max connections: 10
* Async I/O for maximum throughput
* Task queue with concurrency limit

### Stability

* Full error handling & exception capture
* Auto-retry for better reliability
* Graceful shutdown releasing resources
* Detailed logging for debugging

---

## 💻 Commands

**System Commands**

```
/system   - Show current system info & resource usage
/clear    - Clear current conversation history
/memory   - Check memory system status & stats
/save     - Save current conversation to file
/load     - Load conversation history from file
/help     - Show all commands
/setmemory [n] - Set max history length (default 10)
```

---

## 🛠️ Tech Stack

### Backend

* Python 3.7+
* Flask
* WebSocket (native)
* SQLite for long-term memory
* AI integration: TongYi QianWen API (dashscope)
* Voice synthesis: Edge TTS (primary) + pyttsx3 (backup)
* Libraries: jieba, SnowNLP, python-dotenv, psutil
* Vector DB: ChromaDB

### Frontend

* HTML5, CSS3, JavaScript
* WebSocket API for communication
* LocalStorage for browser storage

### System Architecture

* Async I/O
* Custom LRU cache
* WebSocket heartbeat & connection management
* Lazy-load non-core dependencies & smart memory management

---

## 📁 Project Structure

```
xiaoyou-core/
├── start.py                                # 【系统启动入口】: 负责按顺序启动所有独立的 Python 进程。
|                                           #    - 职责：使用 subprocess/multiprocessing 启动 app_main.py, trm_reflector.py 和 desktop_pet.py。
|
├── app_main.py                             # 【核心服务】Agent Core Server (WebSocket)
|                                           #    - 职责：WebSocket 通信、用户连接/内存/心跳管理、任务调度中心。
|                                           #    - 关键：所有 I/O（TRM/TTS/STT/DB）都必须通过 **asyncio 异步调用** 或 **to_thread()** 执行。
|
├── trm_reflector.py                        # 【微服务】TRM/STT 推理 I/O 终点 (FastAPI Server)
|                                           #    - 职责：提供异步 HTTP 接口，接收 app_main 的请求，并执行耗时的推理操作（LLM Query, STT Decode, Image Generation）。
|                                           #    - 关键：在此处模拟或接入真正的 LLM/STT 模型 API。
|
├── desktop_pet.py                          # 【客户端】桌宠 UI 应用程序 (PyQt Lottie)
|                                           #    - 职责：独立的桌面客户端进程，通过 WebSocket 连接 app_main.py。
|                                           #    - 关键：处理 Lottie 动画渲染、用户输入、TTS 音频播放。
|
├── .env                                    # 【配置】本地环境变量文件
|                                           #    - 职责：存储端口号、API Keys、模型路径、默认 LLM 名称等配置信息。
|
├── long_term_memory.db                     # 【数据】持久化数据库文件
|                                           #    - 职责：实际的 SQLite 数据库文件，用于存储所有用户的历史、配置和向量索引。
|
├── README.md                               # 【文档】项目说明文件
|                                           #    - 职责：包含项目简介、安装步骤、运行指南和所有服务的端口信息。
|
├── requirements/                           # 【依赖】依赖配置文件目录
│   ├── requirements_main.txt               #    - 依赖项：websockets, httpx, PyQt6, Lottie, asyncio, logging
│   └── requirements_trm.txt                #    - 依赖项：fastapi, uvicorn, LLM SDK, Whisper/STT 库
|
├── bots/                                   # 【适配层】第三方平台适配器
│   ├── wx_bot.py                           #    - 职责：微信机器人客户端。启动后，通过 WebSocket 连接到 app_main.py 转发消息。
│   └── qq_bot.py                           #    - 职责：QQ 机器人客户端。
|
├── core/                                   # 【核心逻辑】Agent 的大脑和逻辑层
│   ├── trm_adapter.py                      #    - 职责：【异步通信】负责封装所有对 trm_reflector.py (HTTP) 的异步调用逻辑。
│   ├── llm_connector.py                    #    - 职责：【业务逻辑】保留了 LLM Prompt 模板、Token 计算、安全过滤等业务逻辑（供 trm_adapter.py 引用）。
│   ├── vector_search.py                    #    - 职责：向量搜索的核心算法和索引管理。
│   └── utils.py                            #    - 职责：通用的辅助函数（如 JSON 序列化、时间戳处理、日志格式化）。
|
├── multimodal/                             # 【多模态】STT/TTS 调度和执行
│   ├── tts_manager.py                      #    - 职责：【TTS 引擎】封装 TTS SDK，提供线程安全的**同步**方法（供 app_main.py 调用 to_thread()）。
│   └── stt_connector.py                    #    - 职责：【STT 异步连接】负责封装所有对 trm_reflector.py (STT 接口) 的异步调用逻辑。
|
├── memory/                                 # 【记忆系统】数据读写和管理
│   ├── memory_manager.py                   #    - 职责：【逻辑层】封装业务逻辑，如上下文压缩、历史检索、使用 long_term_db.py 驱动。
│   └── long_term_db.py                     #    - 职责：【驱动层】封装所有低级的数据库连接、查询、写入操作 (SQL/ORM)。
|
├── voice/                                  # 【I/O 数据】语音缓存和运行时文件
|                                           #    - 职责：运行时存放 TTS 生成的音频文件缓存 (.mp3) 和 STT 待处理的原始音频文件。
|
├── history/                                # 【I/O 数据】日志和会话审计
|                                           #    - 职责：存放详细的系统日志 (system.log)、API 请求日志、和非数据库形式的会话记录。
|
├── templates/                              # 【前端视图】Web 应用的 HTML 结构
│   ├── ultimate_xiaoyou_optimized.html     #    - 职责：主要的 Web Chat 客户端视图，包含所有 HTML/JS/CSS（或引用 static）。
│   └── error.html                          #    - 职责：通用错误页面模板。
|
└── static/                                 # 【静态资源】Web 客户端引用的不可变资源
    ├── css/style.css                       #    - 职责：Web Chat 客户端的样式表。
    ├── lottie/pet_idle.json                #    - 职责：桌宠和 UI 动画的 Lottie JSON 数据。
    ├── images/                             #    - 职责：预定义的图片，如用户/Agent 头像、图标、背景纹理。
    └── generated/                          #    - 职责：AI **运行时生成** 的图片输出文件夹（供 Web 异步访问）。
```

---

## 🚀 Quick Start

### Requirements

* Python 3.7+
* Minimum 1GB RAM (2GB+ recommended)
* Minimum 50MB disk space
* Windows, macOS, Linux

### Install Dependencies

```bash
pip install flask websockets python-dotenv jieba snownlp pyttsx3 chromadb
pip install dashscope  # for TongYi QianWen API
```

### Configure Environment Variables (.env)

```
QIANWEN_API_KEY=your_api_key_here
MAX_HISTORY_LENGTH=10
MAX_CONNECTIONS=10
```

### Start the App

```bash
python start.py
```

Open browser at `http://localhost:5000` to start chatting.

### Advanced (Debugging)

```bash
python ws_server.py  # WebSocket only
python app.py        # Flask server only
```

---

## 💡 Usage

* Use `/help` to check all commands
* Click 🔊 icon to play AI voice replies
* History auto-saves to `history/`
* Important info stored in long-term memory
* Each user has independent history via `user_id`

## 🔧 Troubleshooting

* **WebSocket issues**: check network/firewall, confirm server is running
* **Voice issues**: pyttsx3 installed, Edge TTS needs network, check audio device & logs
* **Memory/performance**: reduce history with `/setmemory`, clear with `/clear`, restart to free resources
* **Logs**: stored in `flask_app.log` & `startup.log`

---

## 🔮 Roadmap

* Better context & long-term memory
* More performance optimization
* Support more third-party AI models
* Improve speech recognition & synthesis
* Multi-platform integration & UI/UX improvements
* Plugin system for custom extensions
* I will make a table pet and put it on Steam, and of course it is also free and open source

## 🤝 Contact

Leslie Qi – [[2991731868@qq.com](mailto:2991731868@qq.com)]

## 📄 License

This project is open-sourced under the MIT License.

```
MIT License

Copyright (c) 2025 Xiaoyou AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

Xiaoyou AI - A high-performance AI chat assistant optimized for low-spec computers!

© 2025 hakituo
