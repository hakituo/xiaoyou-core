# Stream Utils - 流式输出工具模块

从 streaming.py 中提取出来的流式工具。标签解析、JSON 流式解析与文本平滑
已迁移到 `../streaming_pipeline/`（见 `tag_stream_parser.py`），这里只保留
仍被 streaming / streaming_pipeline 调用的能力。

## 📦 保留能力

| 能力 | 职责 |
|------|------|
| `extract_image_request_prompt` | 图片请求提示词提取（含负面模式拦截） |
| `StreamContextBuilder` | 模式检测与生成参数推断（max_tokens / 软回复长度） |
| `ParallelProcessor` | 并行上下文任务编排与生命统计提取 |

## 🚀 快速开始

### 导入模块

```python
from core.agents.chat_agent_components.stream_utils import (
    StreamContextBuilder,
    ParallelProcessor,
    extract_image_request_prompt,
)
```

### 使用示例

#### 1. 上下文构建

```python
# 检测敏感模式
is_sensitive = await StreamContextBuilder.detect_sensitive_mode(
    agent, user_id, message, system_prompt
)

# 推断 max_tokens：默认不限制，由模型自行决定
max_tokens = StreamContextBuilder.infer_max_tokens(
    mode="chat",
    is_sensitive_mode=False,
    is_system_event=False,
    wants_long=True,
    pref_length="normal",
)
# 返回: None；传入 max_tokens 时原样返回

# 推断软性回复长度：长回复 1000 / 系统事件 300 / 默认 50
soft_limit = StreamContextBuilder.infer_soft_reply_limit(
    "chat", wants_long=False, is_system_event=False, message="你好"
)
# 返回: 50

# 检测用户是否想要长回复
wants_long = StreamContextBuilder.detect_wants_long("详细解释一下")
# 返回: True
```

#### 2. 并行处理

```python
# 并行处理所有任务
results = await ParallelProcessor.process_all(
    agent, message, intimacy_level=0.5
)

# 提取生命统计
mood, shyness, is_sick, immune_dmg, level = \
    ParallelProcessor.extract_life_stats(results["life_stats"])

# 访问其他结果
sensory_feedback = results["sensory_feedback"]
behavior_chain = results["behavior_chain"]
dep_result = results["dep_result"]
triggered_defects = results["triggered_defects"]
```

#### 3. 图片检测

```python
# 提取图片请求
prompt = await extract_image_request_prompt("帮我画一只猫")
# 返回: "猫"

prompt = await extract_image_request_prompt("你好")
# 返回: None
```

## 🧪 测试

```bash
venv_core\Scripts\python.exe -m pytest tests/unit/test_stream_utils.py
```

## 🤝 贡献

欢迎贡献代码！请确保：

1. 每个模块职责单一
2. 函数有清晰的文档字符串
3. 添加相应的单元测试
4. 保持代码风格一致

## 📝 许可

与主项目相同
