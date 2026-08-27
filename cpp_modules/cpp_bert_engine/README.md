# cpp_bert_engine

C++ BERT 推理引擎，基于 ONNX Runtime 运行导出的 ONNX 模型，通过 pybind11 暴露为 Python 模块 `bert_engine_py`。

## 功能

- **BERT 文本分类推理**：加载 ONNX 格式的 BERT 模型，输出 logits 概率向量
- **内置 WordPiece 分词器**：支持中文逐字切分 + 英文整词，基于 vocab 文件
- **ONNX Runtime 加速**：使用预编译的 ONNX Runtime 1.24.4 (Windows x64)

## 架构

```
cpp_bert_engine/
├── CMakeLists.txt              # CMake 构建配置（含 ONNX Runtime 集成）
├── build_engine.py             # 一键构建脚本
├── test_engine.py              # 导入验证脚本
├── src/
│   ├── bert_engine.h           # BertTokenizer + BertEngine 类声明
│   └── bert_engine.cpp         # 分词 + ONNX 推理实现
├── bindings/
│   └── python_bindings.cpp     # pybind11 绑定，暴露为 BertPredictor
└── third_party/
    ├── onnxruntime-win-x64-1.24.4.zip   # ONNX Runtime 预编译库
    └── pybind11-3.0.3.zip               # pybind11 源码
```

## 核心 API

### C++ (`xiaoyou::bert::BertEngine`)

| 类/方法 | 说明 |
|---------|------|
| `BertTokenizer(const string& vocab_path)` | 加载 vocab 文件构建词表映射 |
| `BertTokenizer::tokenize(const string& text, int max_length=128)` | WordPiece 分词，返回 token ID 向量 |
| `BertEngine(const string& model_path, const string& vocab_path)` | 加载 ONNX 模型 + 词表 |
| `BertEngine::predict(const string& text)` | 推理，返回 logits 浮点向量 |

### Python (`bert_engine_py.BertPredictor`)

```python
import bert_engine_py

predictor = bert_engine_py.BertPredictor(
    model_path="model.onnx",
    vocab_path="vocab.txt"
)

logits = predictor.predict("今天天气怎么样？")
# logits: List[float] — 模型输出的原始概率/logits
```

## 构建

```bash
python build_engine.py
```

构建完成后验证：

```bash
python test_engine.py
```

## 性能优化

| 优化项 | 说明 |
|--------|------|
| **UTF-8 路径转换** | 使用 `MultiByteToWideChar(CP_UTF8, ...)` 替代 `wstring(str.begin(), str.end())`，正确处理含中文的模型路径（如 `D:\AI\小优\model.onnx`） |
| **推理 Buffer 复用** | `input_ids_` / `attention_mask_` / `token_type_ids_` 预分配为成员变量，`predict()` 中使用 `assign()` 复用已分配内存，避免每次推理重复堆分配 |

## 依赖

- **C++17** 编译器
- **ONNX Runtime 1.24.4**（预编译 zip，内含 `onnxruntime.lib` / `onnxruntime.dll`）
- **pybind11 3.0.3**（本地 zip）
- **CMake ≥ 3.14**
- 可选：**OpenMP**（若检测到则自动启用并行计算）
- 编译优化：AVX2 + 快速浮点；MSVC 构建会自动复制 `onnxruntime.dll` 到输出目录
