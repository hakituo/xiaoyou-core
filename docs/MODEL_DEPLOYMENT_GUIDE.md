# 小优AI 模型部署完整指南

本指南将帮助您完成小优AI系统的模型部署，包括依赖安装、模型下载、服务启动等全流程。

## 🚀 快速开始

### 步骤1：安装依赖

运行完整的依赖安装脚本：

```bash
# Windows系统
install_all_deps_complete.bat

# 或使用Python直接运行（如果没有bat执行权限）
python -m pip install -r requirements/requirements.txt
```

> 脚本会自动检测CUDA环境并安装相应版本的PyTorch，建议使用Python 3.8+

### 步骤2：下载模型文件

运行模型下载脚本：

```bash
python download_models.py
```

脚本会：
- 提示输入Hugging Face的Access Token
- 自动下载三个模型：
  - **Qwen2.5-7B-Instruct**：语言模型（位于 `./models/qwen2_5/`）
  - **Qwen2-VL-7B-Instruct**：视觉理解模型（位于 `./models/qwen2_vl/`）
  - **SDXL-Turbo**：图像生成模型（位于 `./models/sdxl_turbo/`）

> 注意：模型文件较大（总计约20GB+），请确保有足够的磁盘空间和网络带宽

### 步骤3：启动服务

```bash
# 默认配置启动（自动检测设备）
python start_server.py

# 使用CPU运行（适合无GPU环境）
python start_server.py --device cpu

# 指定端口启动
python start_server.py --api-port 8000 --ws-port 8765

# 预加载特定模型
python start_server.py --preload-models qwen2_5 qwen2_vl
```

## 📁 模型文件说明

### 模型文件结构

下载完成后，模型目录结构如下：

```
models/
├─ qwen2_5/              # Qwen2.5-7B-Instruct 语言模型
│  ├─ config.json        # 模型配置文件
│  ├─ model.safetensors  # 模型权重文件
│  ├─ tokenizer.json     # 分词器配置
│  └─ ...
├─ qwen2_vl/             # Qwen2-VL-7B-Instruct 视觉模型
│  ├─ config.json
│  ├─ model.safetensors
│  ├─ processor_config.json
│  └─ ...
├─ sdxl_turbo/           # SDXL-Turbo 图像生成模型
│  ├─ model.safetensors
│  ├─ config.yaml
│  └─ ...
```

### 模型文件用途

- **model.safetensors**：模型权重文件，包含神经网络的参数
- **config.json**：模型配置，定义模型结构、维度等参数
- **tokenizer.json**：分词器配置，用于文本处理
- **processor_config.json**：视觉模型处理器配置

## 🔧 服务功能说明

### API接口

服务启动后，提供以下API接口：

| 接口 | 方法 | 功能 | URL |
|------|------|------|-----|
| 聊天接口 | POST | 文本对话生成 | http://localhost:8000/api/chat |
| 图像描述 | POST | 上传图像获取描述 | http://localhost:8000/api/describe-image |
| 图像生成 | POST | 根据文本生成图像 | http://localhost:8000/api/generate-image |
| 状态检查 | GET | 获取服务状态 | http://localhost:8000/api/status |

### WebSocket服务

同时提供WebSocket接口（端口8765），支持实时双向通信：

- **聊天操作**：`{"action": "chat", "prompt": "你的问题"}`
- **图像描述**：`{"action": "describe_image", "image_path": "图像路径"}`
- **图像生成**：`{"action": "generate_image", "prompt": "图像描述"}`
- **状态查询**：`{"action": "status"}`

## 📊 显存管理

### 自动显存优化

服务内置了智能显存管理功能：

1. **模型缓存机制**：默认缓存最近使用的2个模型
2. **显存监控**：定期检查显存使用情况
3. **自动清理**：当显存使用超过90%时自动清理缓存
4. **设备降级**：如果CUDA不可用，自动切换到CPU模式

### 手动控制参数

启动时可以通过参数控制显存使用：

```bash
# 限制最大显存使用
python start_server.py --max-memory 70%

# 调整模型缓存大小
python start_server.py --model-cache-size 1
```

## 🛠 常见问题解决

### 1. CUDA内存不足

- 使用CPU模式：`--device cpu`
- 减小模型缓存：`--model-cache-size 1`
- 关闭不必要的模型预加载

### 2. 模型下载失败

- 检查Hugging Face Token是否正确
- 确保网络连接正常
- 检查磁盘空间是否充足（至少需要25GB）
- 尝试使用代理（可在脚本中配置）

### 3. 依赖安装失败

- 更新pip：`python -m pip install --upgrade pip`
- 尝试使用清华镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`
- 检查Python版本（推荐3.8+）

### 4. 服务启动慢

- 首次启动会加载模型，需要较长时间
- 预加载模型会增加启动时间但减少后续请求延迟
- CPU模式下加载会比GPU模式慢

## 📱 移动客户端接入

### API调用示例

**聊天接口示例**（Python）：

```python
import requests

response = requests.post(
    "http://localhost:8000/api/chat",
    json={
        "prompt": "你好，请介绍一下自己",
        "model": "qwen2_5",
        "max_tokens": 1024,
        "temperature": 0.7
    }
)

print(response.json())
```

**WebSocket示例**（JavaScript）：

```javascript
const socket = new WebSocket('ws://localhost:8765');

socket.onopen = () => {
    socket.send(JSON.stringify({
        action: 'chat',
        prompt: '你好，请介绍一下自己'
    }));
};

socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data.response);
};
```

## ⚙️ 高级配置

### 环境变量配置

可以通过环境变量自定义配置：

| 环境变量 | 描述 | 默认值 |
|---------|------|-------|
| XIAOYOU_DEVICE | 运行设备（cpu/cuda） | auto |
| XIAOYOU_MODEL_DIR | 模型目录 | ./models |
| XIAOYOU_API_PORT | API端口 | 8000 |
| XIAOYOU_WS_PORT | WebSocket端口 | 8765 |
| XIAOYOU_MAX_MEMORY | 最大显存比例 | 80% |

### 自定义模型路径

如需使用自定义路径的模型，可以修改配置：

```bash
# 使用环境变量
set XIAOYOU_MODEL_DIR=D:\models
python start_server.py

# 或通过参数
python start_server.py --model-dir D:\models
```

## 📈 性能优化建议

### GPU环境优化

- 使用CUDA 12.x以获得最佳性能
- 确保显卡驱动是最新版本
- 对于显存较小的GPU，可以使用`--model-cache-size 1`减少缓存

### CPU环境优化

- 增加swap空间以避免内存不足
- 使用Intel MKL或OpenBLAS加速
- 考虑使用量化模型减小内存占用

## 🎯 测试验证

运行测试脚本验证模型功能：

```bash
python test_model.py
```

测试会检查：
1. 模型文件完整性
2. 模型加载功能
3. 基础生成能力

## 📋 任务清单

- [x] 安装所有依赖
- [x] 下载模型文件
- [x] 启动服务
- [x] 测试API接口
- [x] 接入移动客户端

---

**注意事项**：
- 模型文件受版权保护，请遵守开源协议
- 大型模型需要较高的计算资源，推荐8GB+显存
- 首次使用会自动下载模型，建议在网络良好的环境下进行

祝您使用愉快！如有问题请参考错误日志或联系技术支持。