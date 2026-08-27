# Tools & Utilities Layer (工具与辅助系统)

## 概述

工具与辅助系统是Xiaoyou-Core系统的工具和辅助功能层，包含工具系统（Tools）、工具函数（Utils）、管理器（Managers）、情绪系统（Emotion）、语音系统（Voice）、图像系统（Image）等核心组件。

## 核心组件

### Tools (工具系统)

**目录**: `core/tools/`

工具系统提供丰富的工具集，支持LLM工具调用。

**主要功能**:
- **基础工具**:
  - WebSearchTool - 网络搜索
  - ImageGenerationTool - 图像生成
  - TimeTool - 时间获取
  - CalculatorTool - 计算器
- **学习工具**:
  - MathPlotTool - 数学绘图
  - FileCreationTool - 文件创建
  - TextToSpeechTool - 语音合成
  - KnowledgeRetrievalTool - 知识库检索
  - UpdateWordProgressTool - 单词进度更新
  - 学科专用工具（生物、语文、地理、数学）
- **数据管理工具**:
  - StudyDataTool - 学习数据管理
  - AvelineDailyDataTool - 日常数据管理
- **日常工具**:
  - DiaryTool - 日记工具
  - ReminderTool - 提醒工具

**使用示例**:
```python
from core.tools.registry import get_tool_registry

# 获取工具注册表
registry = get_tool_registry()

# 获取工具
web_search_tool = registry.get_tool("web_search")

# 执行工具
result = await web_search_tool.run(query="Python教程")
print(result)
```

---

### Utils (工具函数)

**目录**: `core/utils/`

工具函数提供通用的工具函数集合。

**主要功能**:
- **logger.py** - 日志系统
- **common.py** - 通用工具
- **error_handler.py** - 错误处理
- **time_utils.py** - 时间工具
- **performance_tracker.py** - 性能跟踪
- **profiler.py** - 资源监控
- **prompt_loader.py** - 提示词加载
- **text_processor.py** - 文本处理

**使用示例**:
```python
from core.utils.logger import get_logger
from core.utils.common import get_project_root
from core.utils.time_utils import get_current_time

# 获取日志器
logger = get_logger(__name__)

# 获取项目根目录
root = get_project_root()

# 获取当前时间
current_time = get_current_time()
logger.info(f"当前时间: {current_time}")
```

---

### Managers (管理器)

**目录**: `core/managers/`

管理器提供通知、偏好、会话等管理功能。

**主要功能**:
- **NotificationManager** - 通知管理器
- **PreferenceManager** - 偏好管理器
- **SessionManager** - 会话管理器

**使用示例**:
```python
from core.managers.notification_manager import get_notification_manager
from core.managers.preference_manager import get_preference_manager
from core.managers.session_manager import get_session_manager

# 获取管理器
notification_mgr = get_notification_manager()
preference_mgr = get_preference_manager()
session_mgr = get_session_manager()

# 发送通知
await notification_mgr.send_notification(
    user_id="user123",
    notification={
        "title": "新消息",
        "body": "你有一条新消息"
    }
)

# 获取偏好
preferences = preference_mgr.get_preferences("user123")

# 创建会话
session = await session_mgr.create_session("user123")
```

---

### Emotion (情绪系统)

**目录**: `core/emotion/`

情绪系统提供情绪检测、计算、响应和管理功能。

**主要功能**:
- **models.py** - 情绪数据模型
- **calculator.py** - 情绪计算器
- **detector.py** - 情绪检测器
- **responder.py** - 情绪响应器
- **manager.py** - 情绪管理器

**使用示例**:
```python
from core.emotion.manager import get_emotion_manager

# 获取情绪管理器
emotion_mgr = get_emotion_manager()

# 检测情绪
emotion_state = emotion_mgr.detect_emotion("我今天很开心！")
print(f"情绪: {emotion_state.emotion}")

# 更新情绪
emotion_mgr.update_emotion(
    user_id="user123",
    emotion="happy",
    intensity=0.8
)

# 获取情绪状态
current_emotion = emotion_mgr.get_emotion_state("user123")
print(current_emotion)
```

---

### Voice (语音系统)

**目录**: `core/voice/`

语音系统提供STT和TTS功能。

**主要功能**:
- **stt_engine.py** - STT引擎
- **tts_engine.py** - TTS引擎

**使用示例**:
```python
from core.voice.stt_engine import get_stt_manager
from core.voice.tts_engine import get_tts_manager

# 获取管理器
stt_mgr = get_stt_manager()
tts_mgr = get_tts_manager()

# 语音转文字
text = await stt_mgr.transcribe(
    audio_path="path/to/audio.wav",
    model_size="base"
)
print(f"识别结果: {text}")

# 文字转语音
audio_path = await tts_mgr.synthesize(
    text="你好，我是小优。",
    reference_audio="path/to/reference.wav"
)
print(f"音频已保存到: {audio_path}")
```

---

### Image (图像系统)

**目录**: `core/image/`

图像系统提供图像生成和管理功能。

**主要功能**:
- **image_manager.py** - 图像管理器
- **image_utils.py** - 图像工具
- **model_loader.py** - 模型加载器
- **prompt_processor.py** - 提示词处理器

**使用示例**:
```python
from core.image.image_manager import get_image_manager, ImageGenerationConfig

# 获取图像管理器
image_mgr = get_image_manager()

# 生成图像
config = ImageGenerationConfig(
    width=512,
    height=512,
    num_inference_steps=20
)

result = await image_mgr.generate_image(
    prompt="一只可爱的猫",
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
| 单例模式 | NotificationManager, PreferenceManager, SessionManager | 确保全局唯一实例 |
| Facade模式 | EmotionManager | 简化子系统访问 |
| 工厂模式 | TTSEngine, STTEngine | 多引擎创建 |

### 架构原则

- **单一职责原则**: 每个组件职责明确
- **开闭原则**: 易于扩展新工具
- **依赖倒置原则**: 通过接口实现松耦合
- **接口隔离原则**: 接口定义清晰

---

## 性能特性

### 工具性能
- 异步设计优秀
- 性能优化良好
- 无明显性能瓶颈

### 资源占用
- 资源占用合理
- 内存管理良好

### 并发性能
- 异步设计良好
- 并发支持完善

---

## 扩展指南

### 添加新工具

1. **继承BaseTool**:
```python
from core.tools.base import BaseTool

class NewTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="new_tool",
            description="新工具描述"
        )
    
    async def _run(self, **kwargs):
        # 工具逻辑
        pass
```

2. **注册到工具注册表**:
```python
from core.tools.registry import get_tool_registry

registry = get_tool_registry()
registry.register_tool(NewTool())
```

---

## 常见问题

**Q: 如何添加新工具？**  
A: 继承BaseTool类，实现_run方法，然后注册到工具注册表。

**Q: 如何自定义情绪映射？**  
A: 修改EmotionManager中的情绪映射配置。

**Q: 如何切换TTS引擎？**  
A: 使用TTSManager.set_engine("gpt_sovits")或set_engine("cloud")。

**Q: 如何优化图像生成速度？**  
A: 在ImageGenerationConfig中减少num_inference_steps或启用加速模型。

---

## 相关文档

- [系统架构文档](../PROJECT_TECHNICAL_REFERENCE.md)
- [评估报告](./工具与辅助系统评估报告.md)
- [核心引擎层文档](./core_engine/README.md)
- [模块层文档](./modules/README.md)
- [记忆系统文档](../memory/README.md)
