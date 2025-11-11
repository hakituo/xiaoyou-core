# 虚拟环境管理指南

## 环境说明

根据您的要求，我已创建了以下三个独立的虚拟环境：

- **venv_llm**: 用于LLM模型（Qwen2.5-7B/Qwen2-VL）
  - 包含：transformers, accelerate, bitsandbytes, modelscope等

- **venv_img**: 用于图像生成（SDXL/FLUX）
  - 包含：diffusers, transformers, timm, pillow, opencv-python等

- **venv_voice**: 用于语音合成/克隆
  - 包含：torch, torchaudio, numpy, scipy, librosa, soundfile等

## 使用方法

### 激活环境

在Windows命令提示符(cmd)中：

```batch
rem 激活LLM环境
call venv_llm\Scripts\activate.bat

rem 激活图像生成环境
call venv_img\Scripts\activate.bat

rem 激活语音环境
call venv_voice\Scripts\activate.bat
```

在PowerShell中：

```powershell
# 激活LLM环境
.\venv_llm\Scripts\Activate.ps1

# 激活图像生成环境
.\venv_img\Scripts\Activate.ps1

# 激活语音环境
.\venv_voice\Scripts\Activate.ps1
```

### 验证环境

激活环境后，可以使用以下命令验证环境是否正确设置：

```bash
# 查看已安装的包
pip list

# 确认Python路径
python -c "import sys; print(sys.executable)"
```

### 注意事项

1. **独立管理**：每个环境的依赖包是独立的，不会互相干扰
2. **显存优化**：可以在不同的终端中激活不同的环境，让CPU运行语音，GPU运行图像和LLM
3. **库版本**：已使用清华镜像源加速安装，提高下载速度
4. **模型下载**：对于FLUX等大模型，建议在对应的环境中下载和使用

## 扩展说明

如果需要向环境中添加新的依赖包，请先激活对应环境，然后使用pip安装：

```bash
# 例如，在LLM环境中安装新包
call venv_llm\Scripts\activate.bat
pip install 包名 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 后续步骤

1. 虚拟环境创建完成后，可以开始在各环境中下载和使用对应模型
2. 建议将模型文件统一存放在`models`目录中，便于管理
3. 可以根据具体需求调整各环境的依赖包版本