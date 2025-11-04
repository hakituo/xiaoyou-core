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
├── app.py
├── ws_server.py
├── start.py
├── bots/
│   ├── qq_bot.py
│   └── wx_bot.py
├── core/
│   ├── llm_connector.py
│   ├── vector_search.py
│   ├── models/
│   │   └── qianwen_model.py
│   └── utils.py
├── memory/
│   ├── memory_manager.py
│   └── long_term_db.py
├── voice/
├── history/
├── templates/
├── static/
├── .env
├── long_term_memory.db
└── readme.md
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

MIT License © 2025 XiaoYo


# 小悠 AI (xiaoyou-core)
>>>>>>> 75cb3a10fffad3cb59a287dc83793f38183baaa7

A lightweight, high-performance multi-platform AI chat assistant core system, specifically optimized for running on low-spec computers. The system supports WebSocket real-time communication, intelligent memory management, text-to-speech synthesis, and multi-platform integration capabilities.

## 🌟 Features

### Core Features
- 📱 **Multi-platform Integration**: Web interface support with reserved interfaces for QQ and WeChat platforms
- 💬 **Real-time Communication**: Efficient asynchronous message transmission system based on WebSocket
- 🧠 **Intelligent Memory System**
  - Short-term context memory (configurable length and priority)
  - Automatic and manual history saving and loading
  - Importance-based intelligent memory pruning algorithm
  - Long-term memory database storage for key information
- 🔊 **Text-to-Speech**: Dual-engine support (Edge TTS high-quality cloud service + pyttsx3 local backup)
- 💻 **System Integration**: Real-time system status monitoring and resource management

### Performance Optimization (Suitable for Low-spec Computers)
- 🚀 **Resource Optimization Strategies**
  - Dynamic lazy loading of non-core dependencies, significantly reducing startup time and memory usage
  - Intelligent cache management using LRU algorithm to automatically eliminate infrequently used items
  - Strict memory usage monitoring and limitation
  - Automatic garbage collection and resource cleanup mechanisms

- 💾 **Data Processing Optimization**
  - Default history limit of 10 messages, dynamically adjustable
  - Intelligent pruning algorithm based on message importance
  - Text length limits to prevent resource abuse
  - Batch processing and asynchronous execution of time-consuming operations

- 🔌 **Connection and Concurrency Management**
  - WebSocket heartbeat mechanism (30-second interval, 60-second timeout) ensures connection stability
  - Connection limit (default 10) prevents resource exhaustion
  - Asynchronous I/O model maximizes system throughput (isolating I/O-intensive tasks through asyncio.to_thread)
  - Task queue limits the number of concurrent executions

- 🛡️ **Stability Assurance**
  - Comprehensive exception capture and error handling
  - Automatic retry mechanism improves reliability
  - Graceful shutdown ensures proper resource release
  - Detailed logging system facilitates problem diagnosis

### Performance Experiment Results

#### LRU Cache Memory Optimization Test Results (Using psutil Real-time Sampling)
- Without Cache:
  - Average Memory Usage: 24.73 MB
  - Peak Memory Usage: 25.00 MB
- With LRU Cache:
  - Average Memory Usage: 24.83 MB
  - Peak Memory Usage: 25.11 MB
- Memory Change Rate: -0.41%

**Analysis**: Actual test results show a slight increase in memory usage for the cached version, which may be related to the specific test scenario and data access patterns. In scenarios with small data scale and simple access patterns, the memory overhead of the cache may exceed the optimization benefits.

### Command System
- 💻 **System Commands**:
  - `/system` - Get current system information and resource usage
  - `/clear` - Clear current conversation history
  - `/memory` - View memory system status and statistics
- 🔍 **Advanced Features**:
  - `/save` - Save current conversation to file
  - `/load` - Load conversation history from file
- 📋 **Convenient Tools**:
  - `/help` - View all available commands and their usage
  - `/setmemory [num]` - Set maximum history length (default 10 messages)

## 🛠️ Technology Stack

### Backend
- **Language**: Python 3.7+
- **Web Framework**: Flask
- **WebSocket**: Native WebSockets
- **Database**: SQLite (long-term memory storage)
- **AI Integration**: Tongyi Qianwen API (dashscope)
- **Text-to-Speech**: Edge TTS (primary) + pyttsx3 (backup)
- **Tool Libraries**: jieba, SnowNLP, python-dotenv, psutil
- **Vector Storage**: ChromaDB (knowledge base retrieval)

### Frontend
- **Core**: HTML5, CSS3, JavaScript
- **UI**: Native JavaScript implementation
- **Communication**: WebSocket API
- **Local Storage**: localStorage

### System Architecture
- **Asynchronous Processing**: Asynchronous I/O model
- **Cache System**: Custom LRU cache
- **Connection Management**: WebSocket heartbeat mechanism
- **Resource Optimization**: Dynamic lazy loading, intelligent memory management

## 📁 Project Structure

```
xiaoyou-core/
├── app.py                  # Flask Web server
├── ws_server.py            # WebSocket real-time communication service implementation
├── start.py                # One-click startup script
├── bots/                   # Multi-platform integration modules
│   ├── qq_bot.py           # QQ platform integration support
│   └── wx_bot.py           # WeChat platform integration support
├── core/                   # Core functionality modules
│   ├── llm_connector.py    # LLM connector (with command system)
│   ├── vector_search.py    # Vector search and knowledge base integration
│   ├── models/             # AI model implementations
│   │   └── qianwen_model.py # Tongyi Qianwen model wrapper
│   └── utils.py            # Utility functions and performance optimization features
├── memory/                 # Memory management system
│   ├── memory_manager.py   # Context memory and history management
│   └── long_term_db.py     # Long-term memory database management
├── voice/                  # Voice file storage directory
├── history/                # Conversation history saving directory
├── templates/              # Frontend templates
│   ├── index.html          # Web chat main interface
│   └── ultimate_xiaoyou_optimized.html  # Optimized interface
├── static/                 # Frontend static resources
│   ├── script.js           # Frontend JavaScript interaction logic
│   └── style.css           # Frontend interface styles
├── .env                    # Environment variable configuration
├── long_term_memory.db     # Long-term memory database file
└── README.md               # Project documentation
```

## 🚀 Quick Start

### Environment Requirements
- Python 3.7+
- At least 1GB RAM (2GB+ recommended)
- At least 50MB disk space
- Supported operating systems: Windows, macOS, Linux

### Installation

1. Clone or download the project locally
2. Install necessary dependencies:
   ```bash
   pip install flask websockets python-dotenv jieba snownlp pyttsx3 chromadb
   
   # For Tongyi Qianwen API usage, also install
   pip install dashscope
   ```

3. Configure environment variables:
   Edit the `.env` file and fill in the following configuration:
   ```
   # Tongyi Qianwen API Key (optional, simulated responses will be used if not configured)
   QIANWEN_API_KEY=your_api_key_here
   
   # System configuration (adjust as needed)
   MAX_HISTORY_LENGTH=10
   MAX_CONNECTIONS=10
   ```

### Starting the Application

```bash
# Run the startup script directly
python start.py
```

Once started, the application serves at http://localhost:5000 by default, with WebSocket for real-time communication. Open this address in your browser to start using it.

> Note: The one-click startup feature starts both the WebSocket server and Flask web application simultaneously, no need to run them separately.

#### Advanced User Option: Separate Startup (for debugging)

1. First start the WebSocket server:
```bash
python ws_server.py
```

2. Start the Flask application in a new window:
```bash
python app.py
```

## ⚙️ Configuration

### System Core Configuration
- `MAX_HISTORY_LENGTH`: Maximum history length (default 10 messages, adjustable via command)
- `MAX_CONNECTIONS`: Maximum concurrent connection limit (default 10)
- `HEARTBEAT_INTERVAL`: WebSocket heartbeat detection interval (default 30 seconds)
- `HEARTBEAT_TIMEOUT`: WebSocket connection timeout (default 60 seconds)

### Text-to-Speech Configuration
- Automatic TTS engine selection (Edge TTS preferred, fallback to pyttsx3 on failure)
- Support for speech rate and volume adjustment (with safety range limits)
- Automatic voice file cache management

### Performance Optimization Options
- Lazy loading of non-core dependencies (jieba, snownlp, etc.)
- Intelligent cache system (automatically managed with LRU algorithm)
- Text length limits prevent resource abuse

## 💡 Usage Guide

### Basic Conversation
1. After starting the application, open http://localhost:5000 in your browser
2. Enter messages in the input box, click the send button or press Enter
3. Conversation content will be displayed in real-time in the chat interface
4. After receiving an AI response, click the 🔊 icon next to the message to play audio

### Command System Usage
Enter the following commands in the chat input box:

- **View Help**: `/help` - Display all available commands and their usage
- **Clear Conversation**: `/clear` - Clear current conversation history
- **Save History**: `/save` - Save current conversation to file
- **Load History**: `/load` - Load conversation history from file
- **View Memory**: `/memory` - View current memory system status and statistics
- **Adjust Memory Length**: `/setmemory [num]` - Set maximum history length (default 10 messages)
- **System Information**: `/system` - View system information and resource usage

### Memory and History Management
- Conversation history is automatically saved in the `history/` directory
- Important information is stored in the long-term memory database
- Use `/save` and `/load` commands to manually manage history
- Different users' history records are independent (distinguished by user_id)
- The memory system intelligently prunes, prioritizing important messages

## 🔧 Troubleshooting

### Common Issues
1. **WebSocket Connection Failure**
   - Check if network connection is normal
   - Confirm firewall isn't blocking port access
   - Check service logs to confirm WebSocket service started successfully
   - Try refreshing the page or restarting the browser

2. **Text-to-Speech Not Working**
   - Check if pyttsx3 library is installed correctly
   - Edge TTS requires network connection, pyttsx3 is the local backup
   - Confirm system audio device settings are correct
   - Check specific error information in logs

3. **High Memory Usage**
   - Use `/setmemory [smaller value]` command to reduce history length
   - Regularly use `/clear` command to empty conversation history
   - Restart the application to release resources

4. **History Management Issues**
   - Check if `history/` directory permissions are correct
   - Ensure sufficient disk space
   - Manually check if history file format is correct

### Logs and Debugging
- System logs are saved in `flask_app.log` and `startup.log`
- Important errors are displayed in both console and log files
- For debugging, it's recommended to start WebSocket and Flask services separately

## 📝 Notes

- **Resource Optimization**: The system is optimized for low-spec computers, but regular restarts are still recommended to release resources
- **API Key Protection**: Please keep your Tongyi Qianwen API key secure, avoid exposure
- **Data Security**: History and memory data are stored locally, please pay attention to file system security
- **Voice Features**: Edge TTS requires network connection with better sound quality; pyttsx3 is an offline backup solution
- **Connection Limits**: Default maximum concurrent connections is 10, can be adjusted based on system performance

## 🔮 Future Plans

<<<<<<< HEAD
- [ ] Enhance context understanding and long-term memory capabilities
- [ ] Further optimize resource usage efficiency
- [ ] Expand support for more third-party AI models
- [ ] Improve speech recognition and synthesis features
- [ ] Enhance multi-platform integration and adaptation
- [ ] Optimize user interface and interaction experience
- [ ] Add plugin system to support custom functionality extensions

## 📄 License
=======
- [ ] 增强上下文理解和长期记忆能力
- [ ] 进一步优化资源使用效率
- [ ] 扩展更多第三方AI模型支持
- [ ] 完善语音识别与合成功能
- [ ] 增强多平台集成和适配
- [ ] 优化用户界面和交互体验
- [ ] 增加插件系统支持自定义功能扩展
- [ ] 我会做一个桌宠放steam上当然也是免费开源的

## 🤝 合作与支持

本项目核心架构成熟，非常适合作为定制 AI Agent 的基础。

如果您有以下需求，欢迎联系作者（Leslie Qi）：

1.  **定制开发：** 基于 XiaoYou 框架，定制接入您的企业知识库、内部 API 或特定平台（飞书、钉钉等）。
2.  **技术咨询：** 关于高性能 Python 异步架构的指导和优化。
3.  **商业部署：** 协助将 XiaoYou 部署到您的生产环境或云服务器。

**💌 联系邮箱：** [2991731868@qq.com]
      
## 📄 许可证
>>>>>>> 75cb3a10fffad3cb59a287dc83793f38183baaa7

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
