# cpp_fast_tokenizer

C++ 超轻量 Token 计数与截断模块，用于 LLM 上下文窗口管理，通过 pybind11 暴露为 Python 模块 `fast_tokenizer_py`。

## 功能

- **快速 Token 估算**：无需加载模型，基于 UTF-8 字符类型快速近似 LLM token 数量
- **从后截断**：保留最近 `max_tokens` 个 token 的文本，适用于聊天历史截断

## Token 估算规则

| 字符类型 | 估算 token 数 |
|----------|--------------|
| 中文字符 (3-byte UTF-8) | 1.5 |
| 英文单词（连续字母） | 1.3 |
| 标点 / 2-byte UTF-8 | 1.0 |
| Emoji / 4-byte UTF-8 | 2.0 |

> 该估算面向 Qwen 等 LLM 的 BPE 分词器，避免加载完整 tokenizer 模型的开销。

## 架构

```
cpp_fast_tokenizer/
├── CMakeLists.txt              # CMake 构建配置
├── build_tokenizer.py          # 一键构建 + 测试脚本
├── src/
│   ├── bpe_tokenizer.h         # FastBPETokenizer 类声明
│   └── bpe_tokenizer.cpp       # Token 计数 + 截断实现
└── bindings/
    └── python_bindings.cpp     # pybind11 绑定，暴露为 FastTokenizer
```

## 核心 API

### C++ (`xiaoyou::tokenizer::FastBPETokenizer`)

| 方法 | 说明 |
|------|------|
| `int count_tokens(const string& text)` | 快速估算文本的 LLM token 数量 |
| `string truncate_from_back(const string& text, int max_tokens)` | 从前面截断，保留最近 max_tokens 个 token |

### Python (`fast_tokenizer_py.FastTokenizer`)

```python
import fast_tokenizer_py

tokenizer = fast_tokenizer_py.FastTokenizer()

# 估算 token 数
token_count = tokenizer.count_tokens("主人你好！今天天气不错。")

# 截断聊天历史（保留最近的 token）
truncated = tokenizer.truncate_from_back(long_chat_history, max_tokens=2048)
```

## 构建

```bash
python build_tokenizer.py
```

该脚本会自动构建并运行测试：对 1000 次重复的长文本计数并计时，然后截断至 10 token 验证输出。

## 依赖

- **C++17** 编译器
- **pybind11 3.0.3**（从 `cpp_bert_engine/third_party/` 复用本地 zip）
- **CMake ≥ 3.14**
- 编译优化：AVX2 + 快速浮点（`/arch:AVX2 /O2 /fp:fast` on MSVC）
