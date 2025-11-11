# 手动安装指南

## 1. 安装Python

1. 使用已下载的 `python-3.12.4-amd64.exe` 安装程序
2. 运行安装程序，确保勾选以下选项：
   - Add Python to PATH
   - Install for all users (可选)
3. 选择自定义安装路径，例如：`C:\Python312`
4. 完成安装

## 2. 验证Python安装

打开命令提示符(cmd.exe)，运行以下命令：

```cmd
python --version
pip --version
```

如果命令无法识别，请手动将Python添加到环境变量PATH：
- 右键点击"此电脑" > "属性" > "高级系统设置" > "环境变量"
- 在"系统变量"中找到"Path"并编辑
- 添加Python路径，例如：`C:\Python312` 和 `C:\Python312\Scripts`
- 点击确定并重启命令提示符

## 3. 创建虚拟环境

在项目目录中执行以下命令：

```cmd
python -m venv venv
```

## 4. 激活虚拟环境

```cmd
venv\Scripts\activate
```

激活后，命令行提示符前应该会显示 `(venv)`

## 5. 安装依赖

```cmd
pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
pip install -r requirements\requirements.txt
```

## 6. 安装PyTorch GPU版本

根据您的CUDA版本，选择以下命令之一：

对于CUDA 12.1：
```cmd
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

对于CUDA 11.8：
```cmd
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

对于CPU版本（不推荐，无法充分利用GPU）：
```cmd
pip install torch torchvision torchaudio
```

## 7. 运行应用

```cmd
python start.py
```

## 注意事项

- 确保您的GPU驱动支持CUDA
- 如果遇到内存不足问题，可以考虑使用较小的模型
- 对于首次运行，系统可能需要下载额外的依赖文件