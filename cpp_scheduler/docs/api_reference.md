# C++ 异步调度器系统 - API 参考文档

## 1. API 概述

本文档详细描述了C++异步调度器系统提供的REST API接口，包括LLM推理、TTS语音合成和图像生成功能的调用方法。系统采用统一的API设计风格，提供标准的HTTP接口和JSON格式的数据交换。

### 1.1 基础URL

默认情况下，API服务运行在`http://your-server:8080/api/v1/`，可通过配置文件自定义。

### 1.2 请求格式

所有API请求都应使用JSON格式，设置合适的Content-Type头：

```
Content-Type: application/json
```

### 1.3 响应格式

所有API响应都使用JSON格式，包含以下基本字段：

```json
{
  "ok": true,                  // 请求是否成功
  "data": {...},               // 响应数据，根据端点不同而变化
  "error": null,               // 错误信息，成功时为null
  "task_id": "uuid-string",   // 任务ID，异步任务返回
  "timestamp": 1672531200      // 响应时间戳
}
```

### 1.4 错误码

系统使用标准HTTP状态码和自定义错误代码：

| HTTP状态码 | 错误码 | 描述 |
|------------|--------|------|
| 200 | 0 | 成功 |
| 400 | 400 | 请求参数错误 |
| 401 | 401 | 未授权 |
| 403 | 403 | 禁止访问 |
| 404 | 404 | 资源不存在 |
| 408 | 408 | 请求超时 |
| 429 | 429 | 请求过于频繁 |
| 500 | 500 | 服务器内部错误 |
| 503 | 503 | 服务不可用 |

## 2. 系统状态接口

### 2.1 健康检查

**GET /health**

检查系统是否正常运行。

**请求参数**：无

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "status": "healthy",
    "version": "1.0.0",
    "uptime": 3600,
    "components": {
      "gpu_llm": "online",
      "cpu_tts": "online",
      "gpu_image": "online",
      "api_server": "online"
    }
  },
  "error": null,
  "timestamp": 1672531200
}
```

### 2.2 系统状态

**GET /status**

获取详细的系统状态信息。

**请求参数**：无

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "version": "1.0.0",
    "uptime": 3600,
    "config": {
      "workers_enabled": {
        "gpu_llm": true,
        "cpu_tts": true,
        "gpu_image": true
      }
    },
    "resources": {
      "cpu_usage": 35.5,
      "memory_usage": 42.1,
      "gpu_usage": 65.2,
      "gpu_memory": "4.8GB / 8GB"
    },
    "queues": {
      "gpu_llm": {
        "size": 2,
        "capacity": 100
      },
      "cpu_tts": {
        "size": 5,
        "capacity": 200
      },
      "gpu_image": {
        "size": 3,
        "capacity": 50
      }
    }
  },
  "error": null,
  "timestamp": 1672531200
}
```

### 2.3 任务状态查询

**GET /tasks/{task_id}**

查询指定任务的状态。

**路径参数**：
- `task_id`：任务ID

**查询参数**：
- `include_result`：是否包含结果数据，默认false

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "task_id": "uuid-string",
    "type": "image_generation",
    "status": "completed",  // pending, processing, completed, failed, cancelled
    "created_at": 1672531200,
    "started_at": 1672531201,
    "completed_at": 1672531210,
    "progress": 100,
    "result": {...}  // 仅当include_result=true且任务完成时包含
  },
  "error": null,
  "timestamp": 1672531200
}
```

### 2.4 取消任务

**DELETE /tasks/{task_id}**

取消正在执行或等待执行的任务。

**路径参数**：
- `task_id`：任务ID

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "task_id": "uuid-string",
    "status": "cancelled",
    "message": "Task cancelled successfully"
  },
  "error": null,
  "timestamp": 1672531200
}
```

## 3. LLM 推理接口

### 3.1 同步LLM推理

**POST /llm/generate**

执行同步LLM推理，等待结果返回。适用于对实时性要求较高的场景。

**请求体**：

```json
{
  "prompt": "Write a short story about a robot learning to paint",
  "model": "qwen2.5-7b",
  "parameters": {
    "temperature": 0.7,
    "max_tokens": 500,
    "top_p": 0.95,
    "top_k": 40,
    "stop_sequences": ["\n\n", "<|endoftext|>"],
    "stream": false
  }
}
```

**参数说明**：
- `prompt`：推理提示文本（必填）
- `model`：使用的模型名称（可选，默认使用配置的模型）
- `parameters`：推理参数配置
  - `temperature`：采样温度，0-1之间，控制输出随机性
  - `max_tokens`：最大生成令牌数
  - `top_p`：核采样参数
  - `top_k`：top-k采样参数
  - `stop_sequences`：停止序列
  - `stream`：是否流式返回（同步接口通常设置为false）

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "text": "Once upon a time, in a bustling robotic workshop, there was a small robot named Pixel who dreamed of becoming an artist...",
    "tokens": 450,
    "model": "qwen2.5-7b",
    "execution_time_ms": 1250
  },
  "error": null,
  "timestamp": 1672531200
}
```

### 3.2 异步LLM推理

**POST /llm/generate/async**

提交异步LLM推理任务，立即返回任务ID，不阻塞请求。适用于较长的文本生成任务。

**请求体**：与同步接口相同

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "task_id": "uuid-llm-123456",
    "status": "pending",
    "message": "Task submitted successfully"
  },
  "error": null,
  "task_id": "uuid-llm-123456",
  "timestamp": 1672531200
}
```

### 3.3 流式LLM推理

**POST /llm/generate/stream**

执行流式LLM推理，以Server-Sent Events (SSE) 格式流式返回结果。

**请求体**：与同步接口相同，但`stream`应设为true

**响应格式**：SSE流，每个事件为一个JSON对象

```
data: {"text":"Once","token_count":1,"finished":false}

data: {"text":" upon","token_count":2,"finished":false}

...

data: {"text":".","token_count":450,"finished":true,"execution_time_ms":1250}
```

## 4. TTS 语音合成接口

### 4.1 同步TTS合成

**POST /tts/generate**

执行同步TTS语音合成，等待结果返回。

**请求体**：

```json
{
  "text": "Hello, this is a text-to-speech test",
  "voice": "en-US",
  "parameters": {
    "sample_rate": 22050,
    "speed": 1.0,
    "pitch": 1.0,
    "format": "wav"
  }
}
```

**参数说明**：
- `text`：要合成的文本（必填）
- `voice`：语音标识符（可选）
- `parameters`：合成参数
  - `sample_rate`：采样率，常用值22050、44100
  - `speed`：语速，默认1.0
  - `pitch`：音调，默认1.0
  - `format`：输出格式，支持wav、mp3、pcm等

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "audio_base64": "UklGRiQDAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=",
    "format": "wav",
    "sample_rate": 22050,
    "duration_ms": 2500,
    "voice": "en-US",
    "execution_time_ms": 350
  },
  "error": null,
  "timestamp": 1672531200
}
```

### 4.2 异步TTS合成

**POST /tts/generate/async**

提交异步TTS语音合成任务，立即返回任务ID。

**请求体**：与同步接口相同

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "task_id": "uuid-tts-123456",
    "status": "pending",
    "message": "Task submitted successfully"
  },
  "error": null,
  "task_id": "uuid-tts-123456",
  "timestamp": 1672531200
}
```

### 4.3 批量TTS合成

**POST /tts/batch**

批量提交TTS语音合成任务。

**请求体**：

```json
{
  "items": [
    {
      "text": "First text to synthesize",
      "voice": "en-US"
    },
    {
      "text": "Second text to synthesize",
      "voice": "zh-CN"
    }
  ],
  "parameters": {
    "sample_rate": 22050,
    "format": "wav"
  }
}
```

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "task_id": "uuid-batch-123456",
    "status": "pending",
    "item_count": 2,
    "message": "Batch task submitted successfully"
  },
  "error": null,
  "task_id": "uuid-batch-123456",
  "timestamp": 1672531200
}
```

## 5. 图像生成接口

### 5.1 文本到图像生成

**POST /image/generate**

根据文本提示生成图像。这是一个异步接口，会立即返回任务ID。

**请求体**：

```json
{
  "prompt": "A beautiful sunset over mountains with lake reflection",
  "negative_prompt": "blurry, low quality, distorted",
  "parameters": {
    "width": 512,
    "height": 512,
    "steps": 20,
    "guidance_scale": 7.5,
    "seed": 42,
    "model": "sd15-turbo"
  }
}
```

**参数说明**：
- `prompt`：图像生成提示词（必填）
- `negative_prompt`：负面提示词，指导模型避免生成某些元素
- `parameters`：生成参数
  - `width`：图像宽度
  - `height`：图像高度
  - `steps`：采样步数
  - `guidance_scale`：引导尺度，控制提示词的影响程度
  - `seed`：随机种子，使用相同种子可生成相似图像
  - `model`：使用的模型名称

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "task_id": "uuid-image-123456",
    "status": "pending",
    "message": "Image generation task submitted successfully",
    "estimated_time_ms": 8000
  },
  "error": null,
  "task_id": "uuid-image-123456",
  "timestamp": 1672531200
}
```

### 5.2 图像生成任务结果获取

**GET /image/result/{task_id}**

获取已完成的图像生成任务结果。

**路径参数**：
- `task_id`：任务ID

**查询参数**：
- `format`：返回格式，可选值：base64、url
- `quality`：图像质量（仅适用于某些格式）

**响应示例**：

```json
{
  "ok": true,
  "data": {
    "task_id": "uuid-image-123456",
    "status": "completed",
    "image": {