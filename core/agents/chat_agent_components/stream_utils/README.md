# Stream Utils - 流式输出工具模块

这个目录包含了从streaming.py中提取出来的模块化组件。

## 📦 模块列表

| 模块 | 行数 | 职责 |
|------|------|------|
| `text_utils.py` | 140 | 文本处理工具（边界检测、颜文字识别等） |
| `image_detection.py` | 100 | 图片请求检测和意图分类 |
| `stream_smoother.py` | 180 | 流式文本平滑器和智能断句 |
| `naturalness.py` | 20 | 自然度增强（动态填充词） |
| `context_builder.py` | 200 | 上下文构建（模式检测、参数推断） |
| `tag_parser.py` | 300 | 标签解析（[GEN_IMG:], [EMO:]等） |
| `parallel_processor.py` | 150 | 并行任务处理（生命模拟、感官触发） |
| `json_parser.py` | 200 | JSON流式解析（analysis/response） |

## 🚀 快速开始

### 导入模块

```python
from core.agents.chat_agent_components.stream_utils import (
    StreamContextBuilder,
    TagParser,
    ParallelProcessor,
    JSONStreamParser,
    StreamTextSmoother,
    extract_image_request_prompt,
    normalize_tilde_ending,
    looks_formal_user_text,
    looks_mostly_english,
)
```

### 使用示例

#### 1. 上下文构建

```python
# 检测敏感模式
is_sensitive = await StreamContextBuilder.detect_sensitive_mode(
    agent, user_id, message, system_prompt
)

# 推断max_tokens
max_tokens = StreamContextBuilder.infer_max_tokens(
    mode="chat",
    is_sensitive_mode=False,
    is_system_event=False,
    wants_long=True,
    pref_length="normal"
)
# 返回: 2048

# 检测用户是否想要长回复
wants_long = StreamContextBuilder.detect_wants_long("详细解释一下")
# 返回: True
```

#### 2. 标签解析

```python
# 创建解析器
parser = TagParser()

# 查找下一个标签
buffer = "你好 [EMO: happy] 世界"
idx, tag_type = parser.find_next_tag(buffer)
# 返回: (3, "emo")

# 解析情感标签
parser.in_emo_tag = True
done, remaining, emotion = parser.parse_emotion_tag("happy]more text")
# 返回: (True, "more text", "happy")

# 获取收集的结果
image_prompts = parser.collected_image_prompts
think_store = parser.collected_think_store
topics = parser.extracted_topics
```

#### 3. 并行处理

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

#### 4. JSON解析

```python
# 创建解析器
parser = JSONStreamParser()

# 尝试进入JSON模式
content = '{"analysis": "thinking...", "response": "hello"}'
entered, remaining = parser.try_enter_json_mode(content, allow_json=True)
# 返回: (True, "")

# 解析chunk
visible, thought, state = parser.parse_chunk("")
# visible: 可见文本
# thought: 思考内容
# state: 当前状态

# 检查是否卡住
if parser.check_stall():
    # 中止推理
    pass
```

#### 5. 流式平滑器

```python
# 创建平滑器（禁用模式）
smoother = StreamTextSmoother(
    enabled=False,
    min_chars=1,
    hard_chars=1,
    max_delay_ms=0
)

# 推送文本
chunks = smoother.push("你好", force=False)
# 返回: ["你好"] (直接透传)

# 清空缓冲区
remaining = smoother.drain()
```

#### 6. 文本工具

```python
# 规范化波浪号
text = normalize_tilde_ending("你好~~~")
# 返回: "你好~"

# 判断是否正式
is_formal = looks_formal_user_text("请问您好")
# 返回: True

# 判断是否英文
is_english = looks_mostly_english("Hello world")
# 返回: True

# 查找边界
pos = find_stream_boundary("你好。世界", min_chars=1, max_chars=10)
# 返回: 3 (句号后的位置)
```

#### 7. 图片检测

```python
# 提取图片请求
prompt = await extract_image_request_prompt("帮我画一只猫")
# 返回: "一只猫"

prompt = await extract_image_request_prompt("你好")
# 返回: None
```

## 📖 详细文档

- [../STREAMING_REFACTOR.md](../STREAMING_REFACTOR.md) - 重构说明
- [../MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) - 迁移指南
- [../REFACTOR_SUMMARY.md](../REFACTOR_SUMMARY.md) - 收益分析

## 🧪 测试

```bash
# 运行单元测试
python tests/test_stream_utils.py

# 运行验证脚本
python tests/verify_stream_utils.py
```

## 🤝 贡献

欢迎贡献代码！请确保：

1. 每个模块职责单一
2. 函数有清晰的文档字符串
3. 添加相应的单元测试
4. 保持代码风格一致

## 📝 许可

与主项目相同
