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

## Linux 新环境（推荐目标：Python 3.13）

`base.txt` 是在 **Windows + Python 3.10.11** 上采集的精确锁，跨到 Linux 时不要无条件照装（里面有纯 Windows 项、
py<3.11 垫片，以及若干只有 Windows 轮的绑架项）。这些坑已经在 `base.txt` 里用 PEP 508 marker 标掉，
pip/uv 会自动跳过带不满足 marker 的行。

Python 版本选 **3.13**，理由是实测的依赖覆盖率：

| 目标 | 有 manylinux wheel 的 pin | 装不上的主要项 |
| --- | --- | --- |
| 3.13 | 197/208（其余多为只有 sdist、本机编译即可） | `paddle2onnx`（已 marker 跳过）、`pywin32`（Windows 专属） |
| 3.14 | 193/208 | 上面两项 + `numpy 2.2.3` / `scipy 1.15.3` / `contourpy 1.3.2` / `onnxruntime 1.23.2` 都缺 cp314 轮，**且 `paddlepaddle` 最新版也只到 cp313 且无 sdist——这是无法绕过的一票否决** |

`paddlepaddle` 只被 UIE 抽取链路用到；如果那条链路不再使用，删掉它之后 3.14 才是可选项（届时还要把
numpy / scipy / contourpy / onnxruntime 升到带 cp314 轮的版本）。

Linux 上建议直接走 `pyproject.toml` + `uv.lock`（跨平台锁，`requires-python = ">=3.10, <3.15"` 且已含 3.14 分支）：

```bash
uv python install 3.13
uv sync --extra dev --frozen
```

只有当需要包含 `base.txt` 里那些没写进 pyproject 的可选/历史依赖时，才追加 `-r requirements/base.txt`。

## 外部原生工具

`sox`、`ffmpeg-python` 等 PyPI 包只是 Python 封装，不会安装 SoX / FFmpeg 可执行文件。
启用依赖这些命令的语音分析功能时，需要另行提供项目本地二进制并加入进程 `PATH`；
它们不属于 `venv_cpu` / `venv_core` 的 pip 完整性检查范围。
