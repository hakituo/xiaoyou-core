# cpp_audio_processor

C++ 音频预处理与 VAD（Voice Activity Detection）模块，通过 pybind11 暴露为 Python 模块 `audio_processor_py`。

## 功能

- **语音活动检测（VAD）**：基于 RMS 能量阈值判断音频帧是否包含语音
- **静音移除**：按帧（默认 30ms）扫描 PCM 音频，过滤静音帧，返回仅含语音的音频数据

## 架构

```
cpp_audio_processor/
├── CMakeLists.txt              # CMake 构建配置
├── build_audio.py              # 一键构建 + 测试脚本
├── src/
│   ├── audio_vad.h             # AudioVAD 类声明
│   └── audio_vad.cpp           # RMS 能量计算、静音移除实现
└── bindings/
    └── python_bindings.cpp     # pybind11 绑定，numpy 零拷贝交互
```

## 核心 API

### C++ (`xiaoyou::audio::AudioVAD`)

| 方法 | 说明 |
|------|------|
| `AudioVAD(int sample_rate, float energy_threshold)` | 初始化，默认 16000Hz / 0.05 阈值 |
| `bool is_speech(const int16_t* data, size_t length)` | 判断一段 PCM int16 音频是否包含语音 |
| `vector<int16_t> remove_silence(const int16_t* data, size_t length, int frame_ms=30)` | 移除静音帧，返回干净音频 |

### Python (`audio_processor_py.AudioVAD`)

```python
import audio_processor_py
import numpy as np

vad = audio_processor_py.AudioVAD(sample_rate=16000, energy_threshold=0.05)

# 检测语音
is_speech = vad.is_speech(audio_np_int16)  # 输入: 1D numpy int16 数组

# 移除静音
clean_audio = vad.remove_silence(audio_np_int16, frame_ms=30)  # 返回: numpy int16 数组
```

## 构建

```bash
python build_audio.py
```

该脚本会自动执行 CMake 配置、Release 构建，并运行集成测试（生成 3 秒混合音频，验证静音移除效果）。

## 依赖

- **C++17** 编译器
- **pybind11 3.0.3**（从 `cpp_bert_engine/third_party/` 复用本地 zip）
- **CMake ≥ 3.14**
- 编译优化：AVX2 + 快速浮点（`/arch:AVX2 /O2 /fp:fast` on MSVC）
