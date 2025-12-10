# QQ 机器人使用指南

## 功能概述

这个QQ机器人基于go-cqhttp + OneBot v11协议开发，具有以下特点：

- ✅ **单模型多角色**：使用同一个模型实例，通过不同的角色设定区分QQ群聊和私聊场景
- ✅ **智能路由**：自动根据消息来源（群聊/私聊）切换人格
- ✅ **资源高效**：仅加载一个模型，节省GPU内存，避免OOM
- ✅ **上下文管理**：支持群聊和私聊的上下文记忆
- ✅ **用户记忆**：为私聊用户提供长期记忆能力
- ✅ **异步处理**：基于Python asyncio，高性能处理消息
- ✅ **可配置性**：支持灵活的配置选项

## 架构设计

```
                   +------------------+
 QQ群消息 -------> |  Router.py       | ----> 人格 A → 同一个模型调用
 私聊消息 -------> |  (你的逻辑层)     | ----> 人格 B → 同一个模型调用
                   +------------------+
                   
                   后端模型（只加载一次）
```

## 快速开始

### 1. 环境准备

- Python 3.8+
- go-cqhttp（推荐最新版本）
- 所需Python依赖：
  ```
  pip install aiohttp
  ```

### 2. 配置go-cqhttp

1. 下载并安装 [go-cqhttp](https://github.com/Mrs4s/go-cqhttp/releases)
2. 创建go-cqhttp配置文件 `config.yml`，参考示例：

```yaml
# go-cqhttp 配置示例
account:
  uin: 1234567890  # 你的QQ号
  password: ''     # 密码为空，使用扫码登录
  encrypt: false
  status: 0
  relogin:
    delay: 3
    interval: 3
    max-times: 0
  use-sso-address: true
  enable-media-data: false

sync:
  interval: 5000
  timeout: 0

message:
  post-format: array
  ignore-invalid-cqcode: true
  force-fragment: false
  fix-url: true
  proxy-rewrite: ''
  report-self-message: false
  remove-reply-at: false
  extra-reply-data: false

oapi:
  - name: ''
    url: ''

heartbeat:
  interval: 0
  timeout: 0
  message: ''
  post-format: string
  disabled: false

http:
  - host: 127.0.0.1
    port: 5700
    timeout: 0
    long-polling:
      max-queue-size: 2000
    middlewares:
      <<: *default
    post:
      - url: http://127.0.0.1:8080/qq/event

ws:
  - host: 127.0.0.1
    port: 6700
    middlewares:
      <<: *default

experimental:
  ignore-invalid-cqcode: false
  support-mqtt: false
  enhanced-media-data: false
  use-database: false

```

### 3. 配置QQ机器人

1. 复制配置示例文件：
   ```
   cp qq_bot_config.example.json qq_bot_config.json
   ```

2. 编辑 `qq_bot_config.json`，主要配置项：
   - `model.type`: 选择模型框架（transformers/ollama/vllm）
   - `model.model_path`: 设置模型路径
   - `model.system_prompts`: 自定义群聊和私聊的人格设定

### 4. 启动服务

1. 先启动go-cqhttp：
   ```
   ./go-cqhttp -faststart
   ```
   首次运行需要扫码登录

2. 启动QQ机器人：
   ```
   python qq_bot.py
   ```

## 使用说明

### 群聊使用

在群聊中，机器人会在以下情况回复：
1. @机器人时
2. 消息中包含配置的触发关键词（如"机器人"、"AI"、"小助手"）

群聊模式下，机器人会使用活泼、友好的语气，回答简洁有趣。

### 私聊使用

在私聊中，机器人会回复所有消息，使用专业、贴心的语气，提供更详细的回答。

## 高级配置

### 自定义人格

在配置文件中修改 `model.system_prompts`：

```json
"system_prompts": {
  "group": "你是一个活泼、友好的QQ群聊天机器人。...",
  "private": "你是一个专业、贴心的私人AI助手。..."
}
```

### 调整历史记录长度

- 群聊默认保留5轮对话历史
- 私聊默认保留10轮对话历史

可在配置中调整：
```json
"max_group_history": 5,
"max_private_history": 10
```

### 内存管理

机器人会自动清理24小时未活跃的用户记忆，可以通过配置调整：
```json
"auto_cleanup_hours": 24
```

## 常见问题

### 1. 机器人不响应怎么办？

- 检查go-cqhttp是否正常运行且已登录
- 检查配置文件中的端口是否正确
- 查看日志文件 `../logs/qq_bot.log` 排查错误

### 2. 如何更换模型？

在配置文件中修改 `model.model_path` 即可，无需修改代码。

### 3. 如何修改触发关键词？

在配置文件中修改 `trigger_keywords`：
```json
"trigger_keywords": ["机器人", "AI", "小助手", "@机器人"]
```

### 4. 如何开启TTS语音功能？

在配置文件中启用TTS：
```json
"tts": {
  "enabled": true,
  "voice": "default",
  "output_dir": "../audio"
}
```

## 性能优化建议

1. 对于大型模型，建议使用 vllm 或 ollama 框架
2. 适当调整 `max_tokens` 参数，避免生成过长回复
3. 群聊历史记录不宜设置过长，避免上下文过大
4. 定期监控内存使用情况

## 注意事项

1. 请遵守QQ使用协议，文明使用机器人
2. 避免使用机器人发送垃圾信息或恶意内容
3. 合理设置回复频率，避免被系统判定为滥用
4. 定期更新go-cqhttp以获取最新的协议支持

## 相关资源

- [go-cqhttp官方文档](https://docs.go-cqhttp.org/)
- [OneBot v11协议规范](https://github.com/botuniverse/onebot-11)
- [Python asyncio教程](https://docs.python.org/zh-cn/3/library/asyncio.html)