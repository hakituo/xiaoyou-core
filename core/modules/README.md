# Module Layer (模块层)

## 概述

模块层是Xiaoyou-Core系统的功能模块层，封装了LLM、视觉、记忆、语音、图像等基础能力。该层采用模块化设计，每个模块负责特定的AI能力，通过统一的接口与系统其他部分交互。

## 核心组件

### LLMModule (大语言模型模块)

**文件**: `core/modules/llm/module.py`

大语言模型模块负责LLM推理，支持多种模式和云端API。

**主要功能**:
- **双模式支持**:
  - GGUF模式（llama-cpp-python）
  - Transformers模式（HuggingFace）
- **流式生成**:
  - 流式输出
  - 首token超时控制
  - GPU资源管理
- **GPU/CPU切换**:
  - n_gpu_layers配置
  - 动态设备切换
- **云端支持**:
  - 通义千问
  - DeepSeek官方
  - SiliconFlow
  - Aveline

**使用示例**:
```python
from core.modules.llm.module import get_llm_module

# 获取LLM模块
llm_module = get_llm_module()

# 流式生成
async for chunk in llm_module.stream_chat(
    prompt="你好，请介绍一下自己。",
    max_tokens=512,
    temperature=0.7
):
    print(chunk, end="", flush=True)

# 切换到云端API
llm_module.set_provider("deepseek")
```

---

### VisionModule (视觉模块)

**文件**: `core/modules/vision/module.py`

视觉模块负责图像理解和描述。

**主要功能**:
- **支持模型**:
  - Qwen-VL（本地）
  - Qwen2-VL（本地）
  - SiliconFlow（云端）
- **GPU/CPU切换**:
  - 动态设备切换
  - 资源管理器集成
- **图像描述**:
  - 详细的图像描述
  - 多轮对话支持

**使用示例**:
```python
from core.modules.vision.module import get_vision_module

# 获取视觉模块
vision_module = get_vision_module()

# 图像描述
description = await vision_module.describe_image(
    image_path="path/to/image.jpg",
    prompt="请详细描述这张图片的内容。"
)
print(description)
```

---

### MemoryModule (记忆模块)

**文件**: `core/modules/memory/module.py`

记忆模块负责对话上下文和长期记忆的存储与检索。

**主要功能**:
- **AsyncCacheManager**:
  - L1/L2缓存
  - 10分钟TTL
  - 写入模式
- **文件存储**:
  - JSON格式
  - 持久化支持

**使用示例**:
```python
from core.modules.memory.module import get_memory_module

# 获取记忆模块
memory_module = get_memory_module()

# 添加记忆
await memory_module.add_memory(
    user_id="user123",
    content="今天学习了Python的列表推导式。",
    importance=0.8
)

# 检索记忆
memories = await memory_module.retrieve_memories(
    user_id="user123",
    query="上次学了什么？",
    limit=5
)
```

---

### TTSEngine (文本转语音引擎)

**文件**: `core/voice/tts_engine.py`

TTS引擎负责将文本转换为语音。

**主要功能**:
- **支持引擎**:
  - GPT-SoVITS（本地）
  - Cloud TTS（OpenAI兼容）
- **GPU/CPU切换**:
  - 动态设备切换
  - 资源压力处理
- **参考音频**:
  - 支持参考音频
  - 音频参数控制
- **会话管理**:
  - 会话复用
  - 连接池管理

**使用示例**:
```python
from core.voice.tts_engine import get_tts_manager

# 获取TTS管理器
tts_manager = get_tts_manager()

# 文本转语音
audio_path = await tts_manager.synthesize(
    text="你好，我是小优。",
    reference_audio="path/to/reference.wav",
    speed=1.0,
    pitch=0.0
)
print(f"音频已保存到: {audio_path}")
```

---

### STTEngine (语音转文字引擎)

**文件**: `core/voice/stt_engine.py`

STT引擎负责将语音转换为文本。

**主要功能**:
- **支持引擎**:
  - HuggingFace Whisper
  - Faster Whisper（推荐）
  - Cloud STT
- **GPU/CPU切换**:
  - 动态设备切换
  - 显存压力检测和自动降级
- **VAD过滤**:
  - 语音活动检测
  - 静音过滤

**使用示例**:
```python
from core.voice.stt_engine import get_stt_manager

# 获取STT管理器
stt_manager = get_stt_manager()

# 语音转文字
text = await stt_manager.transcribe(
    audio_path="path/to/audio.wav",
    model_size="base"
)
print(f"识别结果: {text}")
```

---

### ImageManager (图像管理器)

**文件**: `core/image/image_manager.py`

图像管理器负责图像生成和管理。

**主要功能**:
- **多后端支持**:
  - ForgeClient（本地SD WebUI Forge）
  - SiliconFlowClient（云端）
  - ComfyClient（ComfyUI）
- **资源管理**:
  - 显存压力检测
  - 模型自动卸载
  - LLM恢复机制
- **LoRA支持**:
  - 多LoRA加载
  - LoRA权重控制
- **加速检测**:
  - Nunchaku/Lightning/Turbo/LCM

**使用示例**:
```python
from core.image.image_manager import get_image_manager, ImageGenerationConfig

# 获取图像管理器
image_manager = get_image_manager()

# 生成图像
config = ImageGenerationConfig(
    width=512,
    height=512,
    num_inference_steps=20,
    guidance_scale=7.5,
    seed=42
)

result = await image_manager.generate_image(
    prompt="一只可爱的猫，坐在窗台上，阳光明媚",
    model_id="sd_xl_base",
    config=config
)

if result["success"]:
    print(f"图像已保存到: {result['image_path']}")
```

---

## 架构设计

### 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| 策略模式 | LLMModule, VisionModule, ImageManager | 多模式/多后端切换 |
| 工厂模式 | TTSEngine, STTEngine | 多引擎创建 |
| 单例模式 | MemoryModule | 确保全局唯一实例 |

### 架构原则

- **单一职责原则**: 每个模块职责明确
- **开闭原则**: 易于扩展新模型/引擎
- **依赖倒置原则**: 通过接口实现松耦合
- **接口隔离原则**: 接口定义清晰

---

## 性能特性

### 推理性能
- 流式生成高效
- GPU/CPU切换优秀
- 无明显性能瓶颈

### 资源利用率
- 资源管理器集成完善
- GPU/CPU热切换优秀
- 模型卸载及时

### 吞吐量
- 单任务性能优秀
- 批处理支持有限
- 建议添加批处理优化

---

## 扩展指南

### 添加新模块

1. **实现模块接口**:
```python
class NewModule:
    def __init__(self, config=None):
        self.config = config or {}
    
    async def initialize(self):
        pass
    
    async def shutdown(self):
        pass
```

2. **注册到CoreEngine**:
```python
from core.core_engine.engine import get_core_engine

core_engine = get_core_engine()
module = await core_engine.load_module("new_module")
```

3. **注册到ResourceManager**:
```python
from core.resource_manager import get_resource_manager

rm = get_resource_manager()
rm.register_model(
    model_id="new_module",
    model_type="new_type",
    priority=ResourcePriority.MEDIUM,
    load_func=module.initialize,
    unload_func=module.shutdown,
    instance=module
)
```

---

## 常见问题

**Q: 如何切换LLM模式？**  
A: 使用LLMModule.set_mode("gguf")或set_mode("transformers")。

**Q: 如何添加新的TTS引擎？**  
A: 在TTSEngine中实现新的引擎类，并在工厂方法中注册。

**Q: 如何启用VAD过滤？**  
A: 在STTEngine中设置enable_vad=True。

**Q: 如何使用LoRA？**  
A: 在ImageGenerationConfig中设置lora_path和lora_weight。

---

## 相关文档

- [系统架构文档](../../PROJECT_TECHNICAL_REFERENCE.md)
- [评估报告](./评估报告.md)
- [核心引擎层文档](../core_engine/README.md)
- [资源管理层文档](../资源管理层README.md)
- [记忆系统文档](../../memory/README.md)
