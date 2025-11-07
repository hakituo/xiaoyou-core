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


- [ ] Further optimize resource usage efficiency
- [ ] Expand support for more third-party AI models
- [ ] Improve speech recognition and synthesis features
- [ ] Enhance multi-platform integration and adaptation
- [ ] Optimize user interface and interaction experience
- [ ] Add plugin system to support custom functionality extensions
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
