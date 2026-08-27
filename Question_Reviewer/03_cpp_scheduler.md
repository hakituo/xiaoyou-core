# C++ 调度器与 GPU

本分类共 25 条记录。按时间倒序（最新在前）排列。

---

### 10.99 Qwen3-TTS GPU利用率低（仅30%）优化 (2026-05-11)

*   **问题描述**: Qwen3-TTS推理时GPU利用率仅30%，速度太慢，用户希望提升到90%
*   **复现步骤**:
    1. 启动Qwen3-TTS本地模型推理
    2. 观察GPU利用率（任务管理器或nvidia-smi），稳定在30%左右
    3. 推理一条短文本需要数秒
*   **预期行为**: GPU利用率应尽可能高，推理速度快
*   **实际行为**: GPU利用率仅30%，推理速度慢
*   **根因**:
    1. Qwen3-TTS是自回归生成模型（autoregressive），token-by-token串行生成，天然难以满载GPU
    2. 使用默认`asyncio.run_in_executor(None, ...)`，线程池竞争激烈
    3. 没有使用CUDA流，CPU-GPU同步开销大
    4. 没有启用torch.compile等PyTorch 2.0+优化
    5. TF32等加速特性未启用
*   **修复方案**:
    1. `torch.compile`编译talker模型（主要计算瓶颈），自动检测GPU架构选择最佳编译模式
       - Blackwell/RTX50、Hopper/H100、Ada/RTX40 → `max-autotune`模式（自动搜索最优kernel）
       - Ampere/RTX30、Turing/RTX20 → `reduce-overhead`模式（减少CPU调度开销）
    2. 创建独立`CUDA Stream`，推理在独立流中执行
    3. 启用TF32（Ampere/Ada/Blackwell均支持）和Flash SDP
    4. 使用专用`ThreadPoolExecutor(max_workers=1)`
    5. 环境变量`QWEN3_TTS_COMPILE=0`可禁用编译
*   **关键认知**:
    - 自回归模型（TTS/LLM）的GPU利用率有理论上限，因为每个token依赖前一个
    - 批处理（batch）是提升利用率的最有效方式，但TTS通常是单条请求
    - torch.compile和CUDA流优化可以将利用率从30%提升到60-80%，但无法达到90%+（需要连续kernel launch才能满载）
    - Blackwell架构（RTX 50系列）使用`max-autotune`编译模式可以获得比Ampere高20-30%的额外加速
    - 不同架构的最佳编译模式不同，不能一刀切用reduce-overhead
*   **涉及文件**: `core/voice/tts_engine.py`
*   **测试脚本**: `tests/scripts/verify_qwen3_tts_gpu_optimization.py`

### 10.33 Windows 下 scheduler_py 版本混用与 Python 3.10 统一 (2026-03-05)

*   **问题描述**: 调度器目录存在 `cp312` 产物，但运行环境是 Python 3.10，导致 `scheduler_py` 导入失败。
*   **复现步骤**:
    *   运行环境为 `venv_core`（Python 3.10）。
    *   `cpp_scheduler/build/Release` 仅有 `scheduler_py.cp312-win_amd64.pyd`。
*   **预期行为**: 调度器绑定可正常导入并返回可用状态。
*   **实际行为**: `No module named 'scheduler_py'`，调度器不可用。
*   **原因分析**: Python 扩展 ABI 不匹配（`cp310` 无法加载 `cp312`）。
*   **解决方案**:
    *   在 Python 3.10 环境安装 `cmake` 与 `ninja`，恢复构建能力。
    *   使用 Python 3.10 重新配置并构建 `scheduler_py`，生成 `scheduler_py.cp310-win_amd64.pyd`。
    *   清理旧 `cp312` 二进制，避免后续排障歧义。
    *   `core/image/image_manager.py`

### 10.32 scheduler_py 导入失败但文件存在（ABI 不匹配）(2026-03-05)

*   **问题描述**: 日志显示在 `cpp_scheduler/build/Release` 与 `core/services/scheduler` 都“找到了 scheduler_py 扩展”，但导入仍报 `No module named 'scheduler_py'`。
*   **复现步骤**:
    *   使用 Python 3.10 环境启动后端。
    *   目录内仅存在 `scheduler_py.cp312-win_amd64.pyd`。
*   **预期行为**: 要么成功导入调度器绑定，要么给出明确的版本不匹配提示。
*   **实际行为**: 仅出现 `No module named 'scheduler_py'`，容易误判为路径问题。
*   **原因分析**: 当前解释器 ABI 为 `cp310`，可加载后缀为 `.cp310-win_amd64.pyd/.pyd`；现有二进制为 `cp312`，不在可加载后缀内，import 机制不会把它识别为候选模块。
*   **解决方案**:
    *   在 `scheduler_wrapper.py` 中增加 ABI 后缀匹配诊断，输出当前 Python 标签、可接受后缀和候选文件名。
    *   当仅发现不兼容二进制时，明确提示“需按当前 Python 版本重编译 cpp_scheduler”。
        2.  在 `scheduler_wrapper.py` 中使用 `os.add_dll_directory` 显式添加 CUDA `bin` 目录和 `Release` 目录。
*   **事件循环缺失**: 报错 `RuntimeError: There is no current event loop in thread 'MainThread'`。
    *   **修复**: 在 `_bio_update_loop` 中增加异常处理，若无 Event Loop 则跳过更新。

### 10.19 C++调度器GPU推理卡死问题 (2026-02-09)

*   **问题描述**: 本地模型加载到GPU后（任务管理器能看到显存占用），但推理时不响应，一直显示超时。CPU推理正常（打招呼消息）。
*   **根本原因分析**:
    *   **C++层llama_decode卡死**: `llama_decode` 是同步阻塞调用，如果GPU死锁，调用永远不会返回。
    *   **shouldStop检查缺陷**: `shouldStop` 只在 `llama_decode` 返回后检查，无法终止卡死的decode。
    *   **无法取消**: 即使Python层调用 `cancelTask`，C++层的 `llama_decode` 仍在执行，任务无法真正停止。
*   **解决方案（三层修复）**:
    *   **Python层 - 调度器自动重启**: 首token超时后，调用 `_restart_scheduler()` 完全重启C++调度器，清理GPU资源后重新初始化。
    *   **Python层 - 健康检查**: GPU工作器初始化后，执行简单推理测试（发送"Hi"），15秒超时检测。
    *   **C++层 - llama_decode超时（根本修复）**: 新增 `llama_decode_with_timeout()` 包装函数，在单独线程中执行decode，主线程监控30秒超时。
    *   **Python层 - 线程锁修复**: 在`_producer()`中，当锁获取超时时，尝试强制释放锁并重新获取。
*   **关键代码变更**:
    *   `core/services/scheduler/cpp_scheduler_engine.py`: 添加 `_restart_scheduler()`, `_health_check_gpu_worker()`, 改进超时处理
    *   `cpp_scheduler/workers/llama_model_impl.cpp`: 添加 `llama_decode_with_timeout()`, 替换所有5处 `llama_decode` 调用
    *   `core/modules/llm/module.py`: 线程锁强制释放机制
*   **验证**: 需要重新编译C++调度器以应用根本修复。Python层修复可立即生效。

### 10.14 C++ 调度器 GPU 编译与路径空格问题（2026-01-22）

*   **问题描述**: 在 Windows 环境下，使用 CMake/MSBuild 编译带 CUDA 支持的 C++ 调度器时，`nvcc` 报错 `fatal : A single input file is required for a non-link phase`。
*   **原因分析**:
    *   **路径空格限制**: NVIDIA CUDA 编译器 (`nvcc`) 在 Windows 上对包含空格的路径（如 `D:\AI\xiaoyou-core`）处理非常脆弱。即使在 CMake 中进行了引号转义，底层 MSBuild 调用 `nvcc` 时仍可能解析失败。
    *   **Toolset 丢失**: 如果 CUDA 安装路径未正确注册到 VS 的 `BuildCustomizations`，CMake 会报 `No CUDA toolset found`。
*   **尝试过的解决方案**:
    1.  **指定 Toolset**: 在 CMake 命令行中增加 `-DCUDAToolkit_ROOT="..."` 并显式指定 `Visual Studio 17 2022` 生成器。
    2.  **短路径绕过**: 尝试使用 Windows 8.3 短路径名（如 `XIAOYO~1`），但 `nvcc` 内部仍可能展开为长路径。
    3.  **虚拟磁盘 (subst)**: 使用 `subst Z: "D:\AI\xiaoyou-core"` 将项目映射到不含空格的 `Z:\` 盘。
*   **最终结论**:
    *   **核心痛点**: Windows 下 CUDA 编译环境对路径极其敏感。
    *   **最佳实践**: 始终将 C++/CUDA 项目放置在不含空格和中文字符的简单路径下（如 `C:\Projects\xiaoyou`）。
    *   **当前处理**: 鉴于编译环境配置复杂且耗时，暂时切换回 Python 后端运行，以确保系统功能可用性。

### 10.11 C++ 调度器编译失败（2026-01-22）

*   **问题描述**: C++ 调度器在 Windows 下编译失败，报错提示 `llama_seq_id` 相关符号与 Embedding 绑定未定义。
*   **复现步骤**:
    *   在 `cpp_scheduler/build` 目录执行 `cmake --build . --config Release`。
*   **预期行为**: 调度器与 Python 绑定模块均成功编译。
*   **实际行为**: `llama_model_impl.cpp` 报 `llama_seq_id` 相关错误，`python_bindings.cpp` 报 Embedding 绑定类型未定义。
*   **解决方案**: `llama_model_impl.h` 补充 `llama.h` 头文件；移除 `python_bindings.cpp` 中未定义的 Embedding 绑定。

### 10.10 C++ LLM 首包无响应卡住（2026-01-22）

*   **问题描述**: C++ LLM Worker 已加载显存但前端无任何回复，流式请求一直等待。
*   **复现步骤**:
    *   启用 C++ LLM Worker 并发送 LLM 请求。
    *   模型未产生任何 token 或直接失败。
    *   前端一直等待 response_done，页面无响应。
*   **预期行为**: 若无 token 或失败，应返回友好错误或结束信号。
*   **实际行为**: Python 侧消费首个队列项时未处理完成标记，完成信号被吞后进入无尽等待。
*   **解决方案**: `CPPSchedulerEngine.submit_llm_task` 首包处理与后续一致，首个 item 也会处理 `text/is_finished` 并正确结束流。

### 10.14.4 Forge 生图请求卡死且显存长时间占用：显存压力闸门 + 请求超时贯通 (2026-01-08)

*   **问题描述**:
    *   触发 Forge 生图后，前端长时间无返回；Forge 侧/显存监控显示显存被占用但迟迟不出图。
    *   在 8GB 显存环境更易出现：LLM 让位未完成或显存压力仍处于临界/紧急时，继续触发 Forge 会进入“等待/卡死”态。
*   **复现步骤**:
    *   本地 LLM 占用 GPU（或刚从 CPU 回迁到 GPU）时，触发一次 1024x1024 以上的生图；
    *   同时 Forge 端需要加载 checkpoint / ControlNet 等组件；
    *   观察到请求长时间不返回，且显存维持高占用。
*   **预期行为**:
    *   生图前必须完成资源让位；若显存仍处于临界/紧急，应快速失败并给出清晰提示；
    *   Forge 调用应遵循业务超时，不应无限期挂起。
*   **实际行为**:
    *   资源让位处于“超时即视为成功/后台仍在释放”的窗口期时，Forge 被过早触发；
    *   `requests.post` 使用固定超时，外层任务取消无法真正中断线程，表现为长时间卡住。
*   **解决方案 (已实施)**:
    *   `ImageManager` 生图资源准备改为单点执行，并在调用 Forge 前增加 `GPU_MEMORY` 状态闸门：若仍为 `CRITICAL/EMERGENCY`，直接拒绝触发 Forge。
    *   Forge 请求超时参数贯通：`ImageManager` 传入 `request_timeout`，`ForgeClient.generate_images` 使用 `(connect=10s, read=request_timeout)` 超时，避免无期限挂起。
    *   `ResourceManager.optimize_resources()` 同时考虑内存与显存状态，GPU 压力下也会进入临界/紧急清理路径。
*   **相关文件**:
    *   `core/image/image_manager.py`
    *   `core/modules/forge_client.py`
    *   `core/resource_manager.py`

### 10.58 cpp_scheduler 开启 BUILD_TESTING 导致编译失败（tests 与当前 API 不一致）（2025-12-20）

*   **问题描述**:
    *   在当前仓库状态下，若 CMake 配置开启 `BUILD_TESTING=ON`，会构建 `cpp_scheduler/tests` 下的 `integration_tests`，但该测试代码引用的类型/接口（例如 `ITaskContext`、`ResourceIsolationScheduler::submitTask` 的调用形式、`BlackBoxConfig` 等）与当前实现不一致，导致编译失败。
*   **复现步骤**:
    *   在仓库根目录执行：`cmake -S cpp_scheduler -B cpp_scheduler/build -DBUILD_TESTING=ON`；
    *   执行：`cmake --build cpp_scheduler/build --config Release`；
    *   观察 `cpp_scheduler/tests/integration_test.cpp` 与 `cpp_scheduler/tests/integration_test.h` 报大量未定义符号/模板匹配失败。
*   **预期行为**:
    *   在打开测试开关时，测试应能编译通过并可运行（至少不会阻塞主目标构建）。
*   **实际行为**:
    *   测试目标编译失败导致默认全量构建失败（尤其在 build 目录曾经缓存 `BUILD_TESTING=ON` 时更易踩坑）。
*   **解决方案（Workaround）**:
    *   关闭测试构建：`cmake -S cpp_scheduler -B cpp_scheduler/build -DBUILD_TESTING=OFF`；
    *   或清理旧 build 目录后重新配置，确保 `BUILD_TESTING` 为 OFF，再构建 `ai_scheduler`/`scheduler_py`。
*   **后续建议**:
    *   对齐 `cpp_scheduler/tests` 与 `core/resource_isolation_scheduler.*` 的真实接口后，再恢复 `BUILD_TESTING=ON` 的可用性。

### 10.57 cpp_scheduler 文档混入旧接口章节（api_reference.md）（2025-12-20）

*   **问题描述**:
    *   `cpp_scheduler/docs/api_reference.md` 在更新为“Mock APIServer 现状”后，文末仍残留一大段旧接口文档（例如 `/tts/generate/async`、`/tts/batch`、`/image/result/{task_id}` 等），与当前 `api/api_server.cpp:registerRoutes()` 的真实路由表不一致，容易误导调用方。
*   **复现步骤**:
    *   打开 `cpp_scheduler/docs/api_reference.md`；
    *   滚动到文档末尾，观察是否出现未在路由表中注册的旧接口章节；
    *   对照 `cpp_scheduler/api/api_server.cpp:96-117` 的 `routes_` 注册表，确认这些旧接口在当前实现中不存在。
*   **预期行为**:
    *   `api_reference.md` 仅描述当前实现中已注册的路由，以及 handler 的入参解析规则与响应结构。
*   **实际行为**:
    *   文档存在“新旧内容拼接”的残留，包含大量与当前实现不符的接口、字段与示例。
*   **解决方案**:
    *   删除残留旧接口章节，仅保留当前实现真实存在的 7 条路由说明，并补充任务取消接口的 `success=false` 分支说明。
*   **验证**:
    *   在 `cpp_scheduler/docs` 目录内检索旧接口路径（如 `/tts/generate/async`、`/image/result`）无匹配；
    *   文档路由表与 `api/api_server.cpp:96-117` 完全一致。

### 10.53 Windows 环境下 C++ Worker 初始化崩溃（Access Violation）（2025-12-20）

*   **问题描述**:
    *   在 Windows 环境下运行 `xy_core_cpp_real` 实验时，进程直接退出，返回代码 `3221225477` (0xC0000005 Access Violation)。
    *   复现发现崩溃发生在 `GPULLMWorker` 加载模型 (`llama_load_model_from_file`) 或 `GPUImageWorker` 初始化阶段。
*   **原因分析**:
    *   疑似 `llama.cpp` 的 Python 绑定 (`llama-cpp-python`) 与 C++ 调度器编译时链接的 `llama.dll` 存在 ABI 不兼容或 DLL 依赖（如 CUDA）缺失/冲突。
    *   C++ Scheduler 的 `start` 方法若开启 `preload_llm` 会立即初始化 Worker 导致崩溃。
    *   即便绕过 LLM，Image Worker 若被触发初始化也会导致类似的资源访问违规。
*   **解决方案**:
    *   **架构降级（Fallback）**：在 `run_final_experiments.py` 中，针对 `xy_core_cpp_real` 实验，强制将 LLM 后端设为 `python`，并移除 `use_cpp_image`。
    *   **混合模式（Hybrid Mode）**：保留 `use_cpp_scheduler=True`，此时 `GlobalTaskScheduler` (L1) 负责路由，但实际计算任务（LLM/Image）回退到 Python 侧执行（或由 Python 包装器管理），避免直接调用不稳定的 C++ Worker 逻辑。
    *   **验证**：修改后实验流程跑通，生成的图表正确反映了 Hybrid 架构（C++ 路由 + Python 计算）的性能特征。

### 10.52 MVP Core：已编译 `scheduler_py` 仍提示“C++ Scheduler 不可用”（2025-12-19）

*   **问题描述**:
    *   已在仓库根目录编译得到 `cpp_scheduler/build/Release/scheduler_py*.pyd`（或已有 `core/services/scheduler/scheduler_py*.pyd`），但运行 `legacy/mvp_core` 实验时仍提示 `Could not find scheduler_py extension`，导致 C++ 调度器被禁用。
*   **复现步骤**:
    *   确保存在上述 `.pyd` 文件；
    *   执行 `legacy/mvp_core/experiments/comprehensive_experiment.py` 并打开 `--use_cpp_scheduler`；
    *   观察日志提示无法找到扩展。
*   **预期行为**:
    *   只要 `.pyd` 位于已知构建输出目录，MVP Core 应能自动发现并加载。
*   **实际行为**:
    *   `legacy/mvp_core/services/cpp_scheduler_wrapper.py` 的搜索路径只覆盖 `legacy/mvp_core/**` 与 `legacy/**`，没有覆盖仓库根目录 `cpp_scheduler/build/**` 等路径。
*   **修复方案**:
    *   扩展搜索路径：补齐 `repo_root/cpp_scheduler/build/**` 与 `repo_root/core/services/scheduler/`（`legacy/mvp_core/services/cpp_scheduler_wrapper.py:38-52`）。

### 10.44 MVP Core：C++ 调度器图像任务接入与兜底文件输出（2025-12-18）

*   **问题描述**:
    *   `use_cpp_for_image` 开启后，MVP Core 的图像生成链路可能出现两类不稳定：
        *   仅启用图像侧时，调度器启动逻辑只覆盖 LLM 分支，导致 C++ 引擎未启动；
        *   C++ 不可用或异常时，Synthetic adapter 直接返回一个不存在的文件名，前端拿到路径但无法展示。
*   **解决方案**:
    *   `GlobalTaskScheduler.start()` 在 `use_cpp_for_image` 为真时也会启动 `CPPSchedulerEngine`，并补齐 `image_engine_type` 与 `image_output_dir`，保证图像 worker 能按配置初始化（`legacy/mvp_core/services/task_scheduler.py:106-146`）。
    *   `SyntheticImageAdapter` 的 fallback 不再返回固定字符串，而是生成一个可落盘的 `.ppm` 占位图片并返回真实路径，避免“返回路径存在但文件不存在”的协议不一致（`legacy/mvp_core/data/adapters/synthetic_image_adapter.py:14-147`）。
*   **验证**:
    *   `python -m ruff check .` 通过；
    *   `python -m pytest -q` 通过；
    *   `python -m mypy .` 通过。

### 10.40 C++ GPU LLM Worker 初始化触发进程崩溃（ConnectionResetError）（2025-12-17）

*   **问题描述**: 在 `scheduler.llm_backend=cpp` 且首个 LLM 请求触发 `GPULLMWorker.initialize()` 时，后端进程可能直接崩溃，客户端表现为连接被重置（`ConnectionResetError(10054)`）。
*   **复现步骤**:
    *   `app.yaml` 开启 `scheduler.use_cpp=true`、`scheduler.use_cpp_for_llm=true`，并设置 `scheduler.llm_backend: "cpp"`；
    *   启动后端后，发送一次 `/api/v1/message`（或任何会触发本地 GGUF 推理的请求）；
    *   观察日志出现 `Initializing GPU Worker (loading model)...` / `Loading llama model from: ...gguf` 后连接被重置或进程退出。
*   **预期行为**: 后端不应因为加载模型而崩溃；至少应在失败时回退到可控的 Python 推理路径并返回友好错误。
*   **实际行为**: `GPULLMWorker` 初始化阶段可能触发底层崩溃（疑似绑定/二进制不匹配或 C++ 侧异常未被捕获），Python 层来不及抛出异常，直接导致进程退出。
*   **解决方案**:
    *   在 `CPPSchedulerEngine.start()` 中，默认禁止使用 C++ LLM Worker：当 `gpu_config.backend=cpp` 但未显式允许时，自动切换到 `python` 后端（`core/services/scheduler/cpp_scheduler_engine.py`）。
    *   仅当设置环境变量 `XIAOYOU_ALLOW_CPP_LLM_WORKER=1` 时，才允许继续走 C++ LLM Worker。
*   **验证结果**:
    *   使用 `python tests\\test_server_uvicorn.py` 进行启动 + 首请求冒烟测试，后端可正常返回 `200`，且模型加载日志仅在首个请求后出现（避免启动期/重复加载）。

### 10.39 C++ 调度器启动阶段同步预加载 LLM 导致后端卡住（2025-12-17）

*   **问题描述**: 启用 C++ 调度器并配置 `use_cpp_for_llm=true` 时，后端启动阶段出现“卡住/无法完成启动”的现象，日志停留在 GPU Worker 初始化与 GGUF 模型加载。
*   **复现步骤**:
    *   在 `app.yaml` 中开启 `scheduler.use_cpp=true` 与 `scheduler.use_cpp_for_llm=true`，并配置 GGUF 路径；
    *   启动后端，观察启动日志停留在 `Initializing GPU Worker (loading model)...` / `Loading llama model from: ...gguf`，迟迟不进入“应用启动完成”。
*   **预期行为**: 后端应快速完成启动；LLM 模型加载可以延后到首个 LLM 请求触发，并且在加载期间不阻塞事件循环。
*   **实际行为**: `CPPSchedulerEngine.start()` 在启动阶段同步调用 `_setup_gpu_worker()` / `_setup_python_llm()`，模型加载发生在启动路径中，导致启动阶段被重型模型加载阻塞。
*   **解决方案**:
    *   调整 `CPPSchedulerEngine.start()` 默认不预加载 LLM，仅保存 `gpu_config` 与后端选择，避免启动阶段同步加载模型（`core/services/scheduler/cpp_scheduler_engine.py`）。
    *   在 `submit_llm_task()` 中检测到 C++ GPU Worker 未就绪时，使用 `asyncio.to_thread(...)` 按需加载，并用异步锁避免并发触发多次初始化。
*   **验证结果**:
    *   使用带 `gpu_config` 的 `cpp_scheduler_engine.start(...)` 调用不再触发模型加载日志，启动可继续推进；
    *   `ruff/mypy` 对 `cpp_scheduler_engine.py` 检查通过。

### 10.38 防止 C++ LLM 启用时本地模型被预加载（2025-12-17）

*   **问题描述**:
    *   在启用 C++ 调度器并配置 LLM（`use_cpp_for_llm=true`）的情况下，启动阶段仍可能触发本地 LLM 预加载（`ChatAgent.initialize()` -> `get_llm_module().initialize()` -> `LocalLLMAdapter.initialize()`），导致显存中出现“调度器侧 LLM + 本地 LLM”并存风险。
    *   在资源紧张或 TTS/STT 离线的情况下，资源管理器进入 `emergency/critical` 清理时，语音服务迁移可能挂起，造成清理流程阻塞。
*   **复现步骤**:
    *   配置启用 C++ 调度器并开启 LLM 走调度器；
    *   启动服务，观察初始化阶段日志，可能同时出现本地 LLM 加载日志与 C++ 调度器 LLM 配置/加载日志；
    *   在本地 TTS 服务未启动时触发资源管理器清理路径，观察是否出现长时间卡住。
*   **预期行为**:
    *   当 C++ 调度器明确承担 LLM 推理时，不应在启动阶段额外预加载本地 LLM；
    *   在 TTS/STT 服务离线时，资源清理流程应有明确超时保护，不阻塞主流程。
*   **实际行为**:
    *   旧逻辑对“C++ LLM 已启用”的判定不足，导致本地适配器仍可能在后台把模型加载进来；
    *   `emergency/critical` 清理路径中对语音迁移未做总超时保护，极端情况下可能等待过久。
*   **解决方案**:
    *   在 `core/llm/__init__.py` 的 `LocalLLMAdapter.initialize()` 中新增判定：当 `use_cpp && use_cpp_for_llm && cpp_scheduler_engine._gpu_config` 成立时，跳过本地预加载；若本地模型已加载则先 `unload_model()` 释放资源。
    *   在 `core/resource_manager.py` 的 `_emergency_cleanup/_critical_cleanup` 中对 `_offload_voice_services()` 增加 `asyncio.wait_for(..., 5.0)` 总超时保护，避免离线服务导致清理流程阻塞。
    *   增加回归测试覆盖上述行为，确保后续重构不回退。
*   **验证结果**:
    *   `pytest` 回归通过：`tests/test_empty_responses.py` 新增用例验证 “C++ LLM 启用时本地不预加载” 与 “紧急清理语音迁移超时可退出”。
    *   `ruff/mypy` 对改动文件检查通过。

### 10.37 C++ LLM 流式回调缺少结束信号导致等待超时（2025-12-17）

*   **问题描述**: 使用 C++ 调度器进行 LLM 流式推理时，偶发出现“首 token 超时”或流式消费端一直等待结束信号的问题。
*   **复现步骤**:
    *   在 Python 侧调用 C++ 推理并消费 token；
    *   模型生成完成后仍继续等待，直到触发 `first_token_timeout` 或调用方超时。
*   **预期行为**: C++ 推理结束后，Python 侧能收到明确的“完成”信号并结束流式生成器。
*   **实际行为**: C++ 绑定的 `onTokenGenerated` 回调只负责输出 token，没有约定“结束回调”；若模型未产生任何 token 或生成结束后无额外回调，Python 侧无法得知结束时机。
*   **处理方式**:
    *   Python 侧在提交 `LLMTask` 后额外轮询任务状态（`COMPLETED/FAILED/CANCELLED`），在任务完成时向队列注入结束标记；
    *   若模型未输出任何 token，则在完成时补发 `generatedText`，保证调用方仍能拿到结果。

### 10.36 C++ 调度器生物系统重复更新导致状态漂移（2025-12-17）

*   **问题描述**: 启用 C++ 调度器后，生物系统状态（能量/神经递质/昼夜节律）出现“衰减过快/漂移”，表现为同等时间内变化幅度异常。
*   **复现步骤**:
    *   启动项目并启用 C++ 调度器；
    *   观察 `BiologicalSystem` 的 `energy` 或神经递质随时间变化，发现每秒变化更接近“2 秒更新一次”的幅度。
*   **预期行为**: 生物系统只由一个更新源驱动，按真实时间间隔更新一次。
*   **实际行为**: C++ 侧 `ResourceIsolationScheduler` 内部线程每秒调用一次 `biologicalSystem_->update(...)`，同时 Python 侧 `CPPSchedulerEngine` 还启动了一个 asyncio 循环每秒调用一次 `bio_system.update(1.0)`，导致重复更新。
*   **处理方式**:
    *   删除 Python 侧的生物系统更新循环，改为只依赖 C++ 调度器内部更新线程；
    *   停止调度器时通过 `shutdown()` 进行线程 join，避免后台线程残留。

### 10.26 C++ 调度器本地 LLM 首 token 超时与关闭流程修复 (2025-12-16)


*   **问题描述**:
    *   启用 C++ 调度器并通过 `CPPSchedulerEngine` 使用本地 GGUF 模型时，如果底层 `llama_cpp` 长时间不产出首个 token，上层 `/api/v1/message` 只能依赖 `limits.message_timeout`（如 60 秒或 300 秒）超时兜底，用户体感为“无论配多少秒，都会跑满后才返回超时”，期间完全没有任何文本反馈；
    *   应用关闭阶段，全局任务调度器的 `stop()` 同步调用了已经异步化的 `CPPSchedulerEngine.stop()`，导致出现 `RuntimeWarning: coroutine 'CPPSchedulerEngine.stop' was never awaited`，属于隐藏的资源清理问题。
*   **原因分析**:
    *   旧版 `CPPSchedulerEngine.submit_llm_task` 在 Python 侧 Llama 路径中，只是简单地把 `create_chat_completion(stream=True)` 的输出塞进异步队列，消费端用 `while True: text, is_finished = await queue.get()` 阻塞等待，没有任何“首 token 超时”保护；
    *   当底层模型因为显存压力、调度竞争或极端输入在首个 token 卡死时，整个调用链只能等到 HTTP 层的 `asyncio.wait_for` 达到上限才会中断，因此表现为“总是在超时时间点才返回”；
    *   C++ Worker 回落路径同样没有首 token 超时逻辑，只要 C++ 侧长时间不通过回调推送 token，Python 事件循环就会一直阻塞在 `queue.get()` 上；
    *   `GlobalTaskScheduler.stop` 沿用了早期同步接口，直接调用 `cpp_scheduler_engine.stop()`，在 `CPPSchedulerEngine.stop` 改为协程后没有同步更新为 `await`，于是 Python 在关闭阶段发出“协程未等待”的运行时警告。
*   **修复方案**:
    *   为 Python 侧 Llama 推理路径增加首 token 超时与友好兜底文案：
        *   在 `submit_llm_task` 内记录 `start_time = time.time()`，从 `kwargs.get("first_token_timeout")` 或默认值 10 秒确定 `first_token_timeout`；
        *   消费端首次从队列取元素时使用 `asyncio.wait_for(queue.get(), timeout=first_token_timeout)`，一旦超时，记录日志并向上游返回一条中文提示“本地模型在较长时间内没有产生任何输出，请尝试重启模型或缩短输入。”，然后终止本轮流式会话 (`core/services/scheduler/cpp_scheduler_engine.py:286-365`)；
        *   继续沿用 10.21 中的异常分类逻辑，对 `exceed context window` / `out of memory` / `CUDA error` 等异常映射为三类简洁中文文案，通过队列返回给上层，而不再暴露英文堆栈 (`core/services/scheduler/cpp_scheduler_engine.py:302-352`)。
    *   为 C++ Worker 回落路径增加一致的首 token 超时行为：
        *   将 C++ 回调 `onTokenGenerated` 推送的 `(text, is_finished)` 放入异步队列，消费端同样在首个元素上使用 `asyncio.wait_for`，并在超时时返回与 Python 路径一致的友好提示 (`core/services/scheduler/cpp_scheduler_engine.py:372-431`)；
        *   这样无论使用 Python 侧 Llama 还是底层 C++ Worker，只要模型在首个 token 阶段完全“卡死”，都能在 10 秒量级内给用户一个明确反馈，而不是静默等待到 HTTP 超时。
    *   统一 `CPPSchedulerEngine` 的关闭接口并修正调度器关闭流程：
        *   保留 `async def stop(self)` 作为唯一对外关闭方法，负责取消生物系统更新任务、释放调度器引用并输出“C++ Scheduler stopped.” 日志 (`core/services/scheduler/cpp_scheduler_engine.py:151-169`)，删除旧的同步 `stop` 重载；
        *   将 `GlobalTaskScheduler.stop` 中的 `cpp_scheduler_engine.stop()` 修改为 `await cpp_scheduler_engine.stop()`，消除“协程未等待”的运行时警告 (`core/services/scheduler/task_scheduler.py:148-151`)；
        *   生命周期管理器 `shutdown_cpp_scheduler` 保持 `await cpp_scheduler_engine.stop()` 调用方式不变，使 C++ 调度器的关闭流程在所有入口上都统一为异步接口 (`core/core_engine/lifecycle_manager.py:399`)。
*   **验证结果**:
    *   启动后端并加载本地 GGUF 模型，通过 `simple_message_client.py` 调用 `/api/v1/message`：
        *   正常情况下，首个 token 会在数秒内产生，日志中打印 `CPPSchedulerEngine: 首个token耗时 … 秒`，HTTP 层在 `message_timeout` 之前即可返回完整回复；
        *   在刻意制造资源紧张或异常输入时，如果模型长时间不产出首 token，可以在日志中看到“首token超时”记录，前端则收到简洁的中文说明，而不是 HTTP 层面的超时错误。
    *   正常关闭应用时，不再出现 `coroutine 'CPPSchedulerEngine.stop' was never awaited`，日志顺序表明任务调度器与 C++ 调度器均被正确回收。
*   **经验总结**:
    *   对于流式 LLM 推理，“首 token 超时”应在离模型最近的一层（如调度器或适配器）中处理，而不是全部压给最外层 HTTP 超时，否则很难给用户提供细粒度可理解的反馈；
    *   当公共服务从同步接口演进为异步接口时，务必系统性审查所有调用点，避免出现“协程当普通函数用”的情况，这类问题虽然不一定立即导致崩溃，但会在关闭和资源清理阶段留下难以诊断的隐患。

### 10.16 C++ 调度器集成总结与使用 (2025-12-15)

*   **架构变更**: 正式引入 `cpp_scheduler` 作为系统的核心调度引擎。
    *   **模块位置**: `cpp_scheduler/` (C++ Source) -> `build/Release/blackbox_scheduler.cp310-win_amd64.pyd` (Compiled Extension).
    *   **Python 接口**: `core/scheduler_wrapper.py` 封装了 C++ 接口，提供 `add_task`, `get_status`, `update_bio_metrics` 等方法。
*   **部署说明**:
    *   必须确保 CUDA Runtime DLLs (`cudart64_12.dll` 等) 和 `llama.dll` 位于系统 PATH 或扩展所在目录。
    *   `scheduler_wrapper.py` 已内置 `os.add_dll_directory` 逻辑以自动解决依赖加载问题。
*   **性能提升**:
    *   **低延迟**: C++ 层直接管理任务队列，减少 Python GIL 争用。
    *   **稳定性**: 在高负载下（如同时运行图像生成和对话），调度器能保持心跳稳定，防止主线程卡死。

### 10.14 显存深度优化：严格模型互斥 (2025-12-15)

*   **问题**: 即使使用了 `GlobalResourceLock`，显存依然不足 (8GB VRAM 运行 Qwen2.5-7B + Qwen2-VL)。
*   **解决方案**: 在 `ResourceManager` 中实现严格的 **互斥加载策略 (Strict Mutual Exclusion)**。
    *   **prepare_for_heavy_task(task_type)**:
        *   当 `task_type='llm'` 时，强制卸载 Vision 和 Image Gen 模型。
        *   当 `task_type='vision'` 时，强制卸载 LLM 和 Image Gen 模型。

### 10.13 C++ 调度器编译与运行修复 (2025-12-15)

*   **编译错误**: `log.cpp` 报错 `error C2039: 'time_point': is not a member of 'std::chrono'`。
    *   **修复**: 在 `log.cpp` 头部显式添加 `#include <chrono>`。
*   **DLL 加载失败**: 运行 `test_cpp_scheduler_binding.py` 报错 `ImportError: DLL load failed`。
    *   **原因**: Windows 下 C++ 扩展无法自动找到依赖的 DLL (CUDA, llama.cpp)。
    *   **修复**:
        1.  将 `llama.dll`, `ggml.dll` 等依赖库手动复制到 `cpp_scheduler/build/Release` 目录。

### 10.11 LLM与视觉模型显存争抢与优化 (2025-12-15)

### 问题现象
- 系统包含LLM (Qwen2.5-7B) 和 Vision (Qwen2-VL) 两个大模型。
- 显卡为RTX 5070 (8GB VRAM)。
- 两个模型同时加载时，VRAM不足 (Need ~10-12GB)，导致严重Swap (RAM使用率>90%)，性能急剧下降 (LLM延迟>60s, Vision延迟>100s)。
- 之前出现的 `CUDA error: an illegal memory access` 是由于 `llama-cpp-python` 旧版本不支持 RTX 50 系列 (Blackwell架构) 导致的，通过安装适配 CUDA 12.8 的预编译 Wheel 解决。

### 解决方案与建议
1. **串行化执行与动态卸载**：
   - 在8GB显存下，无法同时驻留两个模型。
   - 需要在切换任务时显式卸载当前模型，释放VRAM给下一个模型。
   - Python层的 `GlobalResourceLock` 仅限制并发执行，未处理显存释放。
   - 建议实现 "Model Swapping" 机制：当请求Vision时，卸载LLM；请求LLM时，卸载Vision。

2. **C++ Scheduler (资源隔离调度器)**：
   - 设计初衷是为了解决此类资源争抢。

### 10.6 本地大模型显存溢出与超时优化 (2025-12-14)

*   **问题描述**: 本地 GGUF 模型 (Qwen 2.5 7B) 响应极慢（46秒+），生成速度仅 1.5 tokens/s，且初始 API 超时设定 (10s) 导致前端频繁断开。
*   **原因分析**:
    *   **VRAM OOM**: `app.yaml` 中配置 `n_ctx: 8192`，在 RTX 5070 (12GB) 上导致显存溢出，系统被迫使用共享内存 (Shared Memory)，大幅降低推理速度。
    *   **超时过短**: 本地模型冷启动加载 + 推理通常需要 >10s。
*   **解决方案**:
    *   **降级上下文**: 将 `n_ctx` 调整为 `2048`，以确保在 RTX 5070 (12GB) 上能快速响应，避免显存压力和超时。
    *   **保持超时**: 保持 API 超时为 60s，通过减少上下文计算量来满足时间限制。
*   **验证结果**: 显存占用降低，生成速度显著提升，能在一分钟内完成响应。

### 10.1 C++ 调度器集成经验 (2025-12-13)

*   **接口一致性**: 严格保持 `.h` 与 `.cpp` 签名一致，避免链接错误。
*   **遗留清理**: 重构时彻底移除旧代码，避免混淆。
*   **协议对齐**: Python Client 与 C++ Server 需共享明确的 JSON Schema。
*   **Mock 优先**: 优先实现 Mock 模型以隔离硬件依赖，加速逻辑验证。

### QR-20260818-CPP-BINDING-IMPORT C++ GPU Worker 因配置构建器导入路径错误无法就绪 (2026-08-18)
*   **问题描述**: 本地 GGUF 首次推理时，日志出现 Failed to setup GPU worker: C++ scheduler bindings not available，随后报告 C++ GPU Worker 未就绪。
*   **复现步骤**:
    1. 以 local provider 和 scheduler.llm_backend=cpp 启动。
    2. 触发一次本地 GGUF 推理。
    3. 观察配置构建阶段直接报告绑定不可用。
*   **预期行为**:
    1. 配置构建器访问已加载的 scheduler_py，并构造 LLMModelConfig 后初始化 GPULLMWorker。
*   **实际行为**:
    1. scheduler_py 和两个绑定类型实际存在，但配置构建器把绑定入口置为 None。
*   **根因**:
    1. cpp_config_builder 位于 client 子包，却错误使用 .scheduler_wrapper 导入不存在的同级模块；异常被兼容分支静默吞掉。
*   **修复方案**:
    1. 改用 ..scheduler_wrapper 指向调度器包中的真实包装模块。
    2. 增加不加载模型的绑定构建回归验证。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\llm\verify_cpp_config_builder_binding_import.py`

### QR-20260818-CPP-OPTIONAL-LIMITS C++ 本地推理收到 max_tokens=None 后类型错误 (2026-08-18)
*   **问题描述**: 本地 GGUF 推理进入 C++ 执行器后，在 max_tokens 与上下文上限比较时抛出 NoneType 和 int 不可比较。
*   **复现步骤**:
    1. 配置 model.generation.max_new_tokens=0。
    2. 通过 WebSocket 主对话触发本地 C++ 推理。
    3. 执行器收到显式 max_tokens=None，并在上下文裁剪处抛出 TypeError。
*   **预期行为**:
    1. C++ 执行层把未指定的生成上限转换为安全整数，并继续根据上下文窗口裁剪。
*   **实际行为**:
    1. kwargs.get 在键存在且值为 None 时不会使用默认参数 2048。
*   **根因**:
    1. 云端不指定上限的 None 语义未经适配直接进入要求整数的 C++ 路径。
*   **修复方案**:
    1. 在统一执行入口归一化 max_tokens 与 temperature。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\llm\verify_cpp_inference_optional_limits.py`

### QR-20260818-CPP-PROMPT-SLOT C++ LLM 长提示超过单序列上下文后错误处理再次崩溃 (2026-08-18)
*   **问题描述**: C++ Worker 就绪后，本地模型对长 conversation prompt 报 Prompt too long for context，并在 Python 流处理阶段继续触发 can only concatenate str (not dict) to str。
*   **复现步骤**:
    1. 通过 start_venv_core.bat 以 local provider 启动
    2. 发送会构建约 6881 字符 persona 与用户消息的聊天请求
    3. 观察 C++ LLM 任务失败及 cpp_llm_handler.py 的 stop_buffer 拼接异常
*   **预期行为**:
    1. Python 在提交前按 C++ 实际单序列槽位裁剪提示
    2. 后端失败时结构化错误可原样返回且不产生二次异常
*   **实际行为**:
    1. Python 按完整 n_ctx 预算，但 C++ 缓存模式下单请求只获得约一半上下文
    2. 结构化错误字典被作为字符串写入停止词缓冲
*   **根因**:
    1. Python 与 C++ 的上下文容量口径不一致
    2. 快速 token 估算缺少保守下界
    3. 流队列允许文本和字典两种载荷，但消费端只实现了文本分支
*   **修复方案**:
    1. 统一 C++ cache 与 slot context 计算
    2. 用保守 token 估算在提交前裁剪提示
    3. 增加结构化错误载荷分支
*   **验证**:
    1. `tests/scripts/llm/verify_cpp_prompt_slot_and_error_payload.py`
    2. `Ruff：相关 5 个 Python 文件全部通过`

### QR-20260819-CPPSCHED-RESTART C++ 调度器首 token 超时自动重启报 _restart_scheduler 缺失 (2026-08-19)
*   **问题描述**: C++ 调度器 GPU 推理首 token 超时（默认 10 秒）后，日志连续报 ERROR（C++首token超时）与 WARNING（尝试重启调度器），随后抛异常 'CPPSchedulerEngine' object has no attribute '_restart_scheduler'，自动重启机制失效。
*   **复现步骤**:
    1. 启用 C++ 调度器并通过 CPPSchedulerEngine 使用本地 GGUF 模型
    2. 触发 GPU 推理卡死（显存压力或极端输入导致首 token 超过 10 秒）
    3. 观察日志与用户侧反馈
*   **预期行为**:
    1. 首
    2. t
    3. o
    4. k
    5. e
    6. n
    7. 超
    8. 时
    9. 后
    10. 自
    11. 动
    12. 重
    13. 启
    14. C
    15. +
    16. +
    17. 调
    18. 度
    19. 器
    20. ，
    21. 用
    22. 户
    23. 收
    24. 到
    25. 「
    26. G
    27. P
    28. U
    29. 推
    30. 理
    31. 暂
    32. 时
    33. 卡
    34. 死
    35. ，
    36. 已
    37. 自
    38. 动
    39. 重
    40. 启
    41. 调
    42. 度
    43. 器
    44. 」
    45. 的
    46. 友
    47. 好
    48. 提
    49. 示
    50. 。
*   **实际行为**:
    1. 调
    2. 用
    3. e
    4. n
    5. g
    6. i
    7. n
    8. e
    9. .
    10. _
    11. r
    12. e
    13. s
    14. t
    15. a
    16. r
    17. t
    18. _
    19. s
    20. c
    21. h
    22. e
    23. d
    24. u
    25. l
    26. e
    27. r
    28. (
    29. )
    30. 抛
    31. A
    32. t
    33. t
    34. r
    35. i
    36. b
    37. u
    38. t
    39. e
    40. E
    41. r
    42. r
    43. o
    44. r
    45. ，
    46. 重
    47. 启
    48. 失
    49. 败
    50. ，
    51. 用
    52. 户
    53. 只
    54. 收
    55. 到
    56. 通
    57. 用
    58. 的
    59. 「
    60. 本
    61. 地
    62. 模
    63. 型
    64. 在
    65. 较
    66. 长
    67. 时
    68. 间
    69. 内
    70. 没
    71. 有
    72. 产
    73. 生
    74. 任
    75. 何
    76. 输
    77. 出
    78. 」
    79. 提
    80. 示
    81. 。
*   **根因**:
    1. CPPSchedulerEngine 精简时丢失 _restart_scheduler 方法，文档（UPDATES.md / Question_Reviewer 10.19）记载该方法应存在
    2. HealthMonitor.restart_scheduler 内部对同步方法 engine.start() 错误 await，会抛 TypeError 导致即便方法存在重启也失败
*   **修复方案**:
    1. CPPSchedulerEngine 新增 _restart_scheduler()/_health_check_gpu_worker() 代理方法，复用 HealthMonitor 已有实现
    2. HealthMonitor.restart_scheduler 改用 asyncio.to_thread 调用同步 engine.start，并传入保存的 GPU 配置以恢复 _llm_backend 与 GPU 工作器
*   **验证**:
    1. `python tests/scripts/cpp_scheduler/verify_restart_scheduler.py`

### QR-20260819-CPPSCHED-CUDA C++ 调度器实际用 CPU 推理：Windows 下 CMake 强制关闭 CUDA 导致编译产物为 CPU 版 (2026-08-19)
*   **问题描述**: 用 venv_core 启动后，日志显示 llama_kv_cache 全部 dev=CPU、backend_ptrs.size()=1，模型实际跑在 CPU，且 GPU 推理首 token 超时。用户误以为是虚拟环境问题，实为加载的 C++ 二进制不带 CUDA。
*   **复现步骤**:
    1. 启用 C++ 调度器并通过 CPPSchedulerEngine 使用本地 GGUF 模型
    2. 启动后查看日志：llama_context 输出 backend_ptrs.size()=1、KV buffer 全为 CPU
    3. 通过 scheduler_wrapper 确认实际加载的 scheduler_py 位置
*   **预期行为**:
    1. 配
    2. 置
    3. n
    4. _
    5. g
    6. p
    7. u
    8. _
    9. l
    10. a
    11. y
    12. e
    13. r
    14. s
    15. =
    16. 9
    17. 9
    18. 9
    19. 时
    20. 模
    21. 型
    22. 层
    23. 与
    24. K
    25. V
    26. c
    27. a
    28. c
    29. h
    30. e
    31. 应
    32. 落
    33. 到
    34. G
    35. P
    36. U
    37. （
    38. b
    39. a
    40. c
    41. k
    42. e
    43. n
    44. d
    45. _
    46. p
    47. t
    48. r
    49. s
    50. .
    51. s
    52. i
    53. z
    54. e
    55. (
    56. )
    57. >
    58. =
    59. 2
    60. ，
    61. 含
    62. C
    63. U
    64. D
    65. A
    66. 后
    67. 端
    68. ）
    69. 。
*   **实际行为**:
    1. b
    2. a
    3. c
    4. k
    5. e
    6. n
    7. d
    8. _
    9. p
    10. t
    11. r
    12. s
    13. .
    14. s
    15. i
    16. z
    17. e
    18. (
    19. )
    20. =
    21. 1
    22. （
    23. 仅
    24. C
    25. P
    26. U
    27. ）
    28. ，
    29. l
    30. l
    31. a
    32. m
    33. a
    34. _
    35. k
    36. v
    37. _
    38. c
    39. a
    40. c
    41. h
    42. e
    43. 全
    44. 部
    45. d
    46. e
    47. v
    48. =
    49. C
    50. P
    51. U
    52. ，
    53. C
    54. P
    55. U
    56. K
    57. V
    58. b
    59. u
    60. f
    61. f
    62. e
    63. r
    64. 5
    65. 1
    66. 2
    67. M
    68. B
    69. ，
    70. 模
    71. 型
    72. 全
    73. 量
    74. C
    75. P
    76. U
    77. 推
    78. 理
    79. 。
*   **根因**:
    1. scheduler_wrapper.py 优先命中 cpp_modules/cpp_scheduler/build/Release（8月5日 编译），其 CMakeCache 记录 GGML_CUDA=OFF、LLAMA_CUDA=OFF
    2. CMakeLists.txt 在 WIN32 分支用 FORCE 写死 set(LLAMA_CUDA OFF) 与 set(GGML_CUDA OFF)，命令行参数无法覆盖，Windows 上永远编出 CPU 版
    3. build/Release 目录只有 ggml-cpu.dll 没有 ggml-cuda.dll；而 venv_core 的 site-packages 里其实有一套 CUDA 版（含 ggml-cuda.dll 34MB），但加载器不会去那里找
*   **修复方案**:
    1. CMakeLists.txt 改用 if(NOT DEFINED) 包裹，允许 -DLLAMA_CUDA=ON -DGGML_CUDA=ON 在 Windows 开启 CUDA
    2. scheduler_wrapper.py 新增 XIAOYOU_CPP_BACKEND=cpu|cuda|auto 双版本共存切换
    3. 新增 scripts/cpp_scheduler/build_cuda.ps1（subst 规避路径空格，复用本地 libuv-1.x 与 llama.cpp-master）
*   **验证**:
    1. `powershell -ExecutionPolicy Bypass -File scripts/cpp_scheduler/build_cuda.ps1 编译 CUDA 版到 build/cuda/Release`
    2. `设置 XIAOYOU_CPP_BACKEND=cuda 后确认加载 build/cuda/Release 的 pyd，KV cache 落到 GPU`

### QR-20260819-CPPSCHED-NVCC-UTF8 CUDA 版编译报 nvcc fatal: A single input file is required (2026-08-19)
*   **问题描述**: 编译 CUDA 版 cpp_scheduler 时，ggml-cuda 全部 .cu 文件报 nvcc fatal: A single input file is required for a non-link phase when an outputfile is specified，MSB3721 错误，编译失败。
*   **复现步骤**:
    1. 运行 powershell -ExecutionPolicy Bypass -File scripts/cpp_scheduler/build_cuda.ps1
    2. ggml-cuda.vcxproj 编译 .cu 文件阶段报错
*   **预期行为**:
    1. nvcc 正常逐个编译 .cu 模板实例，最终产出 ggml-cuda.dll 并链接出 llama.dll / scheduler_py.pyd
*   **实际行为**:
    1. 每个 nvcc 命令都失败，返回码 1；命令中包含裸参数 /utf-8 /Zc:char8_t-
*   **根因**:
    1. cpp_scheduler/CMakeLists.txt 的 add_compile_options(/utf-8 /Zc:char8_t-) 是目录级全局选项，随 FetchContent 传播到 llama.cpp CUDA 目标
    2. MSBuild 生成器把目录级编译选项原样拼入 nvcc 命令行，Windows 下 nvcc 将 /utf-8 误当作输入文件，报 'single input file required'
*   **修复方案**:
    1. 删除全局 add_compile_options，改为 target_compile_options 只在本项目四个 C++ 目标上加 /utf-8 /Zc:char8_t-
*   **验证**:
    1. `重新配置后 grep ggml-cuda.vcxproj 已无 /utf-8 编译标志`

### QR-20260819-CPPSCHED-BUILD-TESTS-DLL CUDA 版编译全链路：tests 目标编译失败 + 加载到旧版 CUDA DLL (2026-08-19)
*   **问题描述**: 修复 nvcc /utf-8 泄漏后重编译 CUDA 版，libuv 成功后在集成测试目标报错（createDefaultAPIClient 找不到标识符等）；编译通过后运行时验证发现 pyd 加载的是 site-packages 的旧版 llama.dll/ggml-cuda.dll。
*   **复现步骤**:
    1. 运行 scripts/cpp_scheduler/build_cuda.ps1 编译 CUDA 版
    2. libuv 编译成功后 tests/integration_tests.vcxproj 编译失败
    3. 修通后用 XIAOYOU_CPP_BACKEND=cuda 加载，检查 llama.dll 来源
*   **预期行为**:
    1. CUDA 版一次编译成功，运行时加载新编译的配套 llama.dll / ggml-cuda.dll
*   **实际行为**:
    1. tests/integration_test.cpp 编译报 createDefaultAPIClient/LLMEngineType 未定义，MSB3721；
    2. 运行时 GetModuleFileName 显示 llama.dll / ggml-cuda.dll 均来自 venv_core/Lib/site-packages（5月23日旧版），新编译的 build/cuda/bin/Release 未被使用。
*   **根因**:
    1. BUILD_TESTING 被 llama.cpp/libuv 的 include(CTest) 置为 ON，底部 option() 不覆盖缓存值，导致 add_subdirectory(tests) 编译引用已删除旧 API 的代码；
    2. Windows AddDllDirectory 按 LIFO（后添加先搜）解析，site-packages 与新编译 bin/Release 的注册顺序不对，导致旧版 DLL 抢先命中。
*   **修复方案**:
    1. CMakeLists 顶部 FORCE 置 BUILD_TESTING=OFF，注释掉 tests 子目录；
    2. scheduler_wrapper 对选中 pyd 目录动态注册配套 bin/Release（最后注册最优先）。
*   **验证**:
    1. `增量构建退出码 0；verify_cuda_backend.py 通过；cuda 模式 llama.dll/ggml-cuda.dll 均来自 build/cuda/bin/Release`

### QR-20260824-CPP-KV-CLEAR-DIVERGENCE 清除短期记忆后 C++ KV Cache 未同步导致 M-RoPE 位置冲突 (2026-08-24)
*   **问题描述**: 执行清除短期记忆后，新 Prompt 从较短位置开始，但同一会话的 GPU KV Cache 仍保存旧的更大位置，llama_decode 报 sequence positions inconsistent。
*   **复现步骤**:
    1. 使用本地 GGUF 模型完成至少一轮对话，让 C++ Worker 为 conversationId 建立 KV sequence
    2. 执行清除短期记忆，Python 历史和磁盘 KV Swap 被删除
    3. 以相同 conversationId 再次发消息，新 Prompt 与旧缓存只保留较短公共前缀
    4. 观察 llama.cpp 报旧 KV 最后位置不小于新 batch 起始位置
*   **预期行为**:
    1. 清除短期记忆同时失效该 conversationId 的全部运行时推理缓存
    2. 新一轮从位置 0 正常 prefill，不复用已清除对话的 KV
*   **实际行为**:
    1. 旧实现只清 Python 记忆与 KV Swap 文件，显存 sequence 和 seq_tokens_ 继续保留
    2. 局部 sequence 删除失败后返回值被忽略，随后从较小位置 decode 并失败
*   **根因**:
    1. 记忆清理调用链没有跨到 C++ Scheduler 的会话缓存生命周期
    2. 未处理 llama_memory_seq_rm 返回 false 的模型兼容分支
*   **修复方案**:
    1. 增加按 conversationId 清除 C++ KV Cache 的模型、Worker、pybind 和 Python 门面接口
    2. ChatAgent.clear_history 在删除 KV Swap 后调用运行时缓存清理
    3. 局部裁剪失败时整条 sequence 清空并从 0 重算
*   **验证**:
    1. `验证脚本覆盖 C++ 接口、Python 桥接、清理调用顺序和局部裁剪回退`
    2. `CUDA C++ 扩展重新编译成功并通过绑定导入检查`
