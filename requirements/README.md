# Python 依赖布局

项目使用两层依赖定义，职责不同：

- `pyproject.toml` 与 `uv.lock`：项目包的直接依赖、可选功能组及跨平台解析结果。
- `base.txt`：当前 Windows 完整运行环境的精确版本锁；包含历史模块和可选运行链实际需要的传递依赖。
- `cpu.txt` / `gpu.txt`：仅锁定对应 PyTorch 索引和 Torch 三件套，必须在 `base.txt` 之后单独安装。

不要在同一条 pip 命令中同时传入 `base.txt` 和 CPU/GPU 文件，因为后者使用独立的 PyTorch `--index-url`。

## CPU 环境

```powershell
.\venv_cpu\Scripts\python.exe -m pip install -r requirements\base.txt
.\venv_cpu\Scripts\python.exe -m pip install -r requirements\cpu.txt
.\venv_cpu\Scripts\python.exe tests\scripts\environment\verify_runtime_dependencies.py --environment cpu
```

## GPU 环境

```powershell
.\venv_core\Scripts\python.exe -m pip install -r requirements\base.txt
.\venv_core\Scripts\python.exe -m pip install -r requirements\gpu.txt
.\venv_core\Scripts\python.exe tests\scripts\environment\verify_runtime_dependencies.py --environment gpu
```

更新 `qwen-tts` 后，还应按 `config/patch_qwen_tts.py` 的说明重新应用项目兼容补丁。

## 外部原生工具

`sox`、`ffmpeg-python` 等 PyPI 包只是 Python 封装，不会安装 SoX / FFmpeg 可执行文件。
启用依赖这些命令的语音分析功能时，需要另行提供项目本地二进制并加入进程 `PATH`；
它们不属于 `venv_cpu` / `venv_core` 的 pip 完整性检查范围。
