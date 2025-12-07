# 依赖安装与环境说明

- 核心依赖：`pip install -r requirements/core.txt`
- 语音与音频：`pip install -r requirements/voice.txt`
- 模型（CPU）：`pip install -r requirements/models-cpu.txt`
- 模型（GPU）：`pip install -r requirements/models-gpu.txt`
- 开发与测试：`pip install -r requirements/dev.txt`

在 Windows 环境下安装 GPU 版 `torch` 时，建议根据本机 CUDA 版本选择官方轮子。
如无需 GPU，可安装 CPU 组以降低依赖复杂度。

