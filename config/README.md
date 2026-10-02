# config/ — 配置系统

本目录是**配置的唯一集中管理点**（项目规则：所有与 config 相关的内容都在这里）。
运行期代码不直接读 yaml 文件，而是通过这里的 pydantic settings 读取。

## 目录结构

| 文件 / 目录 | 职责 |
| --- | --- |
| `yaml/app.yaml` | 配置入口，通过 `imports` 挂载 `sections/*.yaml` |
| `yaml/sections/modeling.yaml` | 模型本体：**本地模型的唯一真源**、采样参数、上下文窗口 |
| `yaml/sections/model_routing.yaml` | 业务场景路由：主对话 / Active Care / 自愈 / 角色日常各用哪个模型 |
| `yaml/character_*.yaml` | 角色日常、日程骨架、活动实例池（含 `*_sensitive.yaml`，已被 gitignore） |
| `yaml_loader.py` | 读 yaml → 展开 `imports` → 解析 `${ENV}` → 映射到 settings |
| `integrated_config.py` | `AppSettings` 聚合与 `get_settings()` 入口 |
| `settings_*.py` | 各领域字段定义（server / model / voice / life / study / infra ...） |
| `model_detector.py` | 本地模型探测：按 `modeling.yaml` 的声明找第一个存在的路径 |
| `model_config.py` | 云端模型注册池、默认对话模型、日记/总结模型路由 |
| `cache_manager.py` | 启动缓存（yaml 与模型探测结果，签名变化才重算） |
| `asr_config.json` | 语音识别模型路径与类型 |
| `tool_profiles.json` | 角色工具配置 |

## 加载链路

1. `.env`（python-dotenv）→ 进程环境变量
2. `yaml/app.yaml` + `sections/*.yaml`（`${VAR}` 会替换成环境变量）
3. `settings_*.py` 的 pydantic 默认值 ← yaml 覆盖（yaml 优先）
4. `model_detector.py` 按声明探测本地模型，补全缺失路径
5. 结果写入 `cache/startup_settings_cache.json`，下次启动签名一致则直接复用

## 唯一真源约定（重要）

**本地模型**（文本 / 视觉 / 语音识别 / 生图底模）的路径与候选清单**只在
`yaml/sections/modeling.yaml` 声明一次**：

| 字段 | 含义 |
| --- | --- |
| `model.path` | 当前生效的本地文本模型（GGUF） |
| `model.whisper_path` | 本地语音识别模型目录（faster-whisper 格式） |
| `model.vision_path` | 本地视觉模型目录；留空表示视觉走云端 provider |
| `model.llm_candidates` / `image_candidates` / `vision_candidates` / `asr_candidates` | 自动探测候选，按顺序取第一个存在的 |
| `model.image_provider` | 生图后端：`comfyui` / `forge` / `siliconflow` |
| `model.default_image_model` / `fallback_image_model` / `image_model_aliases` | 底模别名与真实文件名映射 |

> 为什么强调这点：2026-09-24 之前，本地模型路径同时写在 `modeling.yaml`、
> `integrated_config.py`、`model_detector.py`、`core/modules/llm/module.py` 四处且互不一致，
> 磁盘上一个都对不上，探测只能退回 `glob + mtime`，甚至会把 `mmproj`（视觉投影层）
> 当成主模型加载。现在这些位置一律从 settings 读，代码里不再出现模型名。

其它真源：

- 云端供应商默认地址 / 默认模型：`settings_model.py` 的 `PROVIDER_BASE_URLS`、`PROVIDER_DEFAULT_MODELS`
- 场景到模型的路由：`yaml/sections/model_routing.yaml`
- 环境变量：仓库根 `.env`（真实值，已 gitignore）+ `.env.example`（模板）

## 环境变量命名约定

1. 本目录的 pydantic 配置用 `SettingsConfigDict(env_prefix=...)` 读取，**必须带前缀**：
   `XIAOYOU_VOICE_ENABLED`、`XIAOYOU_STUDY_ENABLED`、`XIAOYOU_SCHEDULER_*`，
   嵌套字段用双下划线 `XIAOYOU_DEBUG__LIFE_SIMULATION`。**无前缀的裸键不会被读取。**
2. 另一部分字段由代码直接 `os.getenv` 读取（如 `QWEATHER_*`、`ASR_MODEL_PATH`、
   各家 `*_API_KEY`、`XIAOYOU_TEXT_MODEL_PATH`），以 `.env.example` 中列出的为准。
3. 多 API key：`<PROVIDER>_API_KEY_<别名>`，别名转小写后在路由里用
   `cloud:<provider>:<别名>:<model>` 引用；供应商地址用 `<PROVIDER>_BASE_URL` 覆盖。
4. **不要写 `KEY=`（空值）**：空字符串会被当成“显式设为空”，覆盖掉代码默认值；
   用不到的项请整行注释掉。

`.env.example` 由 `tests/scripts/config/verify_env_template.py` 守护：
模板里不允许出现没有读取点的死键，必需键不能漏。

## 常见操作

- **换本地文本模型**：改 `modeling.yaml` 的 `model.path`（并把新文件加到 `llm_candidates` 首位）
- **换生图底模**：改 `modeling.yaml` 的 `default_image_model`，并确认别名在 `image_model_aliases` 里有对应真实文件；若 ComfyUI 换了底模文件，同步更新别名表
- **调整某场景用哪个云端模型**：改 `model_routing.yaml`，不要在代码里写死
- **新增一个可调项**：在对应 `settings_*.py` 加字段（带 `env_prefix`），在 yaml 给默认值，然后按需补 `.env.example`

## 把模型放外接盘（2026-09-24 定稿）

本地模型体积大但平时用不到时，可以把大件挪到外接硬盘。**只搬 `llm` 和 `Image` 两类**，
其余小模型必须留在本机（见文末「搬不得的」）。

### 本地 LLM：`.env` 里加一行绝对路径

```ini
XIAOYOU_TEXT_MODEL_PATH=E:/models/llm/Qwen3.5-9B-Q4_K_M.gguf
```

- 生效原理：`model_detector` 的判断是「yaml 声明的 `model.path` 不存在 → 才读这个环境变量」，
  搬走后原路径自然不存在，env 接管。`models/llm` 是我们**真正要读文件**的部分
  （llama_cpp / C++ 调度器在进程内加载）。
- `.env` 是机器本地且已 gitignore，所以放绝对路径不违反「两平台可运行」的规则。
- **双系统注意**：直接复制目录到 Linux 时 `.env` 会跟着过去，里面 `E:/...` 在 Linux 上无效，
  要改成挂载点（如 `/mnt/ext/models/llm/Qwen3.5-9B-Q4_K_M.gguf`）。两边的 `.env` 各留各的值。

### 生图：仓库侧零改动，改 ComfyUI 自己的配置

**我们的代码从不读 checkpoint 文件**，只把**文件名**（`model.image_model_aliases` 的值）
通过 HTTP 发给 ComfyUI；文件在哪是 ComfyUI 的事。它靠
`models/Image/ComfyUI/extra_model_paths.yaml` 里的绝对 `base_path` 指过去，搬盘改那里即可。

若只搬大资产、ComfyUI 本体留在本机，`text_encoders` 那行是相对 `base_path` 的，会跟着算到
外接盘去，所以要拆成两段、各自带 `base_path`：

```yaml
xiaoyou_models:                 # 大资产在外接盘
  base_path: e:/AI/models/Image/
  diffusion_models: check_point/
  vae: VAE/
  loras: lora/Krea2/
xiaoyou_comfy_local:            # ComfyUI 本体仍在本机
  base_path: d:/AI/xiaoyou-core/models/Image/ComfyUI/
  text_encoders: models/text_encoders/
```

### 外接盘不在时会发生什么

| 项 | 行为 |
| --- | --- |
| 主对话 | 不受影响（默认 provider 是云端 deepseek，见 `modeling.yaml` 的 `model.llm.provider`） |
| 启动 | **不会崩**。`integrated_config.validate()` 里 `mkdir` 失败只 `raise ValueError`，两个调用点（`core/trm_adapter.py`、`core/core_engine/config_manager.py`）都包了 try/except，只记 warning |
| 本地 LLM 预加载 | 不做（`modeling.yaml` 的 `llm_preload_on_startup: false`） |
| 模型探测 | 找不到就跳过，只打日志；启动缓存签名变化会重探一次 |
| 生图 | 失败（连不上 ComfyUI 或 checkpoint 不存在），这正是「平时用不到」的预期 |
| 记忆 / 向量检索 | 不受影响，`models/BERT/bge-small-zh-v1.5` 是硬编码在 `memory/embedding_generator.py`、`core/vector_search.py` 的项目内路径 |

### 搬不得的（小件，留本机）

`models/BERT/`（记忆检索 embedding，硬编码路径）、`models/faster-whisper/`（ASR）、
`models/UIE/`、`models/Qwen3-TTS-12Hz-0.6B-Base/`、`models/voice/`、`models/tts/`。

### 两个坑

1. **不要去改 `settings.model.model_dir`**。它看着像「模型根目录」旋钮，但压不住声明式候选
   （`llm_candidates` / `image_candidates` / `asr_candidates` 是项目相对路径，由
   `first_existing_path(..., project_root)` 解析，不经过 `model_dir`）。改它只会平移 glob 兜底
   扫描与探测监控路径的基准，顺带把 vision / asr 的基准带偏，收益为零还容易产生“我明明设了”的错觉。
   要搬就用上面两个 env 口子。
2. **ComfyUI 的底模形态与我们的工作流还没对齐**（待办）：ComfyUI 本体自带的
   `models/checkpoints` 是空的，底模都在 `check_point/` 且只映射成 `diffusion_models`；
   而 `ComfyClient.build_sdxl_workflow` 用的是 `CheckpointLoaderSimple`（需要完整单文件
   checkpoint）。所以 Krea2 这类「diffusion model + 独立文本编码器（`ComfyUI-Krea2TextEncoder`，
   编码器在 `ComfyUI/models/text_encoders/`）」的底模，走我们这条工作流会报 checkpoint 找不到。
   要么把工作流改成 `UNETLoader + CLIPLoader + VAELoader` 的形态并调 turbo 步数/cfg，
   要么确认生图实际走的是别的入口。

## 守护脚本

```powershell
venv_core\Scripts\python.exe tests\scripts\config\verify_local_model_config.py
venv_core\Scripts\python.exe tests\scripts\config\verify_env_template.py
```
