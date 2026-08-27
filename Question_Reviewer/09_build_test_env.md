# 构建 / 测试 / 环境

本分类共 30 条记录。按时间倒序（最新在前）排列。

---

### 10.142 诊断脚本直接运行时报 `ModuleNotFoundError: No module named 'core'`（根因：tests 子目录脚本缺少项目根路径注入）(2026-06-28)

*   **问题描述**: 直接执行 `venv_core\Scripts\python.exe tests\character_daily\verify_character_daily_plan_tool.py` 时，脚本在导入 `core.services...` 前就报 `ModuleNotFoundError: No module named 'core'`，导致 tests 子目录下的独立验证脚本无法单独运行。
*   **复现步骤**:
    1. 在项目根目录打开 PowerShell
    2. 执行 `venv_core\Scripts\python.exe tests\character_daily\verify_character_daily_plan_tool.py`
    3. 观察到 Python 解释器只把脚本所在目录 `tests\character_daily` 加入 `sys.path`
    4. 导入 `core.*` 失败并抛出 `ModuleNotFoundError`
*   **预期行为**: tests 子目录下的独立诊断脚本应能直接运行，不要求额外设置 `PYTHONPATH`
*   **实际行为**: 脚本依赖项目根目录在 `sys.path` 中，但直接运行时并不存在该前提
*   **根因**: 直接执行单文件脚本时，Python 默认只把脚本目录放进 `sys.path[0]`；`tests/character_daily/verify_character_daily_plan_tool.py` 位于子目录下，没有主动把仓库根目录注入路径
*   **修复**:
    1. 在脚本开头增加 `Path(__file__).resolve().parents[2]` 计算项目根目录
    2. 将项目根目录插入 `sys.path`
    3. 保持脚本既可被直接执行，也可被 IDE/CI 从项目根调用
*   **验证**: 修复后再次执行 `venv_core\Scripts\python.exe tests\character_daily\verify_character_daily_plan_tool.py`，脚本成功输出 `PASS`
*   **教训**:
    1. 放在 `tests/` 子目录下的独立验证脚本，不要假设运行者一定从模块模式 `python -m` 启动
    2. 需要直接执行的脚本，应显式处理项目根路径，避免环境相关偶发失败

### 10.140 logs/errors/ 文件夹不再收集后端 ERROR 日志（根因：仅 ErrorReporter.report_error() 写入，多数 logger.error 不经过）(2026-06-27)

*   **问题描述**: [logs/errors/](file:///d:/AI/xiaoyou-core/logs/errors/) 文件夹只有 6 月 17 日的错误文件，今天（6 月 27 日）后端有大量 ERROR 日志（get_write_lock NameError、siliconflow_client Stream Request Failed、openai_client Stream request failed 等）却从未写入 errors 文件夹。用户还要求每天的 error 复制一份到根目录方便注意。
*   **复现步骤**:
    1. 启动后端服务
    2. 触发任意 ERROR 级别日志（如模型调用失败、NameError 等）
    3. 检查 `logs/errors/` 文件夹——无当天的错误文件
    4. 检查 `logs/YYYY/M/D/xiaoyou_main.log`——ERROR 日志确实存在
*   **预期行为**: 所有 ERROR+ 级别日志都应写入 `logs/errors/` 文件夹，并在根目录生成 `errors_YYYYMMDD.json` 每日聚合文件方便注意
*   **实际行为**: 只有走 `ErrorReporter.report_error()` 路径的错误（如 `global_exception_handler` 捕获的未处理异常）才写入 `logs/errors/`，绝大多数 `logger.error(...)` 调用只写到 `xiaoyou_main.log`
*   **根因**: `logs/errors/` 仅由 [log_sanitizer.py](file:///d:/AI/xiaoyou-core/core/utils/log_sanitizer.py) 的 `ErrorReporter.report_error()` → `_save_errors_to_file()` 写入。代码库中绝大多数 `logger.error(...)` 调用不经过此方法。6 月 17 日的文件来自 `/api/v1/models` 的 TypeError 走了 `global_exception_handler` → `ErrorReporter.report_error()` 路径，属特例而非通用收集机制
*   **修复**:
    1. 新建 [error_collector.py](file:///d:/AI/xiaoyou-core/core/utils/error_collector.py)（256 行）：`ErrorCollectorHandler(logging.Handler)` 附加到 `_queue_listener.handlers`，捕获所有 ERROR+ 日志
    2. 每条 ERROR+ 同时写入两处：① 转发给 `ErrorReporter.report_error()` 写入 `logs/errors/` ② 写入根目录 `errors_YYYYMMDD.json` 每日聚合文件
    3. 排除自身 logger（LOG_SANITIZER / _rotation_failure / uvicorn.error / uvicorn.access）避免递归
    4. `_skip_collector` 标记：`global_exception_handler` 已直接调用 `report_error`，通过 `extra={"_skip_collector": True}` 避免重复调度
    5. 跨线程调度：QueueListener 在独立线程运行，用 `asyncio.run_coroutine_threadsafe()` 转发到主事件循环
    6. [service_registry.py](file:///d:/AI/xiaoyou-core/core/core_engine/service_registry.py) 新增 `error_collector` 服务（优先级 1，在 `log_sanitizer` 之后）
    7. [error_handlers.py](file:///d:/AI/xiaoyou-core/core/utils/error_handlers.py) 先调用 `report_error` 拿 `error_id` 再 `logger.error`，通过 `_skip_collector` 避免重复收集
*   **验证**: [verify_error_collector.py](file:///d:/AI/xiaoyou-core/tests/diagnostics/verify_error_collector.py) 9/9 测试通过
*   **教训**:
    1. 日志收集不能只靠单一入口（`ErrorReporter.report_error`），必须通过 logging.Handler 在日志系统层面统一捕获
    2. QueueListener 在独立线程运行，handler 的 emit 是同步调用，跨线程调用 async 函数需用 `asyncio.run_coroutine_threadsafe(coro, loop)` 并提前捕获主事件循环引用
    3. 因 logger.py（851 行）和 log_sanitizer.py（566 行）已超项目 500 行限制，不能继续追加代码，必须新建独立模块
*   **关键文件**: [error_collector.py](file:///d:/AI/xiaoyou-core/core/utils/error_collector.py)、[service_registry.py](file:///d:/AI/xiaoyou-core/core/core_engine/service_registry.py)、[error_handlers.py](file:///d:/AI/xiaoyou-core/core/utils/error_handlers.py)

### 10.134 Python 字符串字面量内嵌双引号导致 SyntaxError 行号偏移（2026-06-20）

*   **问题描述**: `plan_prompts.py` 第 9 行报 `SyntaxError: invalid syntax. Perhaps you forgot a comma?`，但实际错误在第 22 行。
*   **复现步骤**:
    *   在双引号字符串中直接使用 `"` 包裹中文内容，如 `"如"完成数学卷子第3套"可以不指定时间"`；
    *   Python 解析时第一个 `"` 之后的内容被当作裸标识符，触发语法错误。
*   **预期行为**: 字符串中包含引号应正确转义或使用不同引号类型。
*   **实际行为**: Python 报语法错误，且错误行号指向括号表达式的起始行（第 9 行）而非实际出错行（第 22 行），造成定位困难。
*   **原因分析**: 双引号字符串内直接使用了 ASCII 双引号 `"` 而未转义；Python 的语法错误行号在多行括号表达式中可能指向表达式起始位置。
*   **解决方案**: 将字符串内的双引号改为全角书名号 `「」`（`plan_prompts.py:22`）。

### 10.129 .git 目录反复莫名消失，导致 Git 历史丢失 (2026-06-18)

*   **问题描述**: 项目根目录的 `.git` 文件夹多次莫名消失，导致本地 Git 仓库被破坏、提交历史全部丢失，不得不 `git init` 重新初始化并 `--force` 推送覆盖 GitHub 历史
*   **复现步骤**:
    1. 正常使用项目（开发、运行服务、IDE 操作）
    2. 过一段时间执行 `git status` 报 `fatal: not a git repository`
    3. 检查发现 `d:\AI\xiaoyou-core\.git` 目录已不存在
*   **预期行为**: `.git` 目录应一直存在，除非用户主动删除
*   **实际行为**: `.git` 目录在无明显操作的情况下消失
*   **排查过程**:
    *   搜索项目代码中的 `shutil.rmtree`、`Remove-Item -Recurse`、`rmdir`、`git clean` 等危险命令，均未发现针对 `.git` 或项目根目录的删除操作
    *   `Path.rmdir()` 只能删空目录，无法删除 `.git`
    *   启动脚本（`start_scripts/`）中无删除命令
    *   怀疑是 IDE（Trae）操作、杀毒软件（MsMpEng）、文件索引（SearchIndexer）或同步工具导致
*   **应对措施**: 创建 `tests/scripts/git_watchdog.ps1` 看门狗脚本，采用轮询（每 2 秒）监控 `.git` 目录，一旦消失立即采集可疑进程快照（含命令行）、项目根目录最近文件变动、`.git` 是否被重命名，日志输出到 `logs/.git_watch.log`
*   **教训**: 大型项目应监控关键目录的异常变动；`.git` 丢失后本地 reflog 也一并丢失，无法恢复历史，重要提交应及时推送远端

### 问题 1: debug 字段名冲突导致 YAML debug 配置全部失效 (2026-06-17)


*   **问题描述**: `config/integrated_config.py` 中 `AppSettings` 类在第 128 行定义了 `debug: DebugSettings = DebugSettings()`，在第 139 行又定义了 `debug: bool = Field(default=False)`。Python 类中后定义的字段覆盖前者，导致 `settings.debug` 实际是 `bool` 类型而非 `DebugSettings`。
*   **复现步骤**:
    1. 在 `config/yaml/app.yaml` 的 `debug:` 节设置 `auto_eat: true`
    2. 运行 `venv_core\Scripts\python.exe -c "from config.integrated_config import get_settings; print(type(get_settings().debug).__name__)"`
    3. 观察输出为 `bool` 而非 `DebugSettings`
    4. `is_debug_enabled('auto_eat')` 始终返回 False（fallback 到默认 DebugSettings()）
*   **预期行为**: `settings.debug` 应为 `DebugSettings` 类型，YAML 配置的 22 个 debug 开关应能正常生效。
*   **实际行为**: `settings.debug` 是 `bool` 类型，YAML debug 配置全部失效，只有环境变量 `XIAOYOU_DEBUG__*` 能生效（通过 fallback 路径）。
*   **修复方案**: 删除第 139 行无用的 `debug: bool` 字段（全项目 grep 确认无业务代码引用 `settings.debug` 作为 bool），保留第 128 行的 `debug: DebugSettings`。
*   **验证**: `tests/verification/test_p0_fixes.py` 的 `test_p0_1_debug_field_conflict` 通过。

### 10.37 asyncio.run() 在 FastAPI 异步环境中导致 RuntimeError (2026-04-26)

*   **问题描述**: `summary_worker.py` 和 `task_planner_worker.py` 在同步方法中直接调用 `asyncio.run()` 来执行异步函数，在 FastAPI 的异步环境中会抛出 `RuntimeError: This event loop is already running`。
*   **复现步骤**:
    1. 启动 FastAPI 服务
    2. 调用 `DataOpsService.submit_daily_digest()` 或 `submit_task_plan()`
    3. 内部同步方法尝试调用 `asyncio.run()` 执行异步函数
    4. 抛出 `RuntimeError: This event loop is already running`
*   **预期行为**: 在已有事件循环的异步环境中，应该使用 `asyncio.run_coroutine_threadsafe(loop, coro)` 将协程提交到现有事件循环执行，而非创建新的事件循环。
*   **实际行为**: `asyncio.run()` 尝试创建新的事件循环，但当前线程已有一个运行中的事件循环，导致崩溃。
*   **解决方案**: 使用 `asyncio.get_running_loop()` + `run_coroutine_threadsafe()` 作为主要方式，`asyncio.run()` 仅作为 `RuntimeError`（无事件循环）时的 fallback。
*   **涉及文件**: `core/services/data_ops/summary_worker.py`, `core/services/data_ops/task_planner_worker.py`

### 10.33 异步恢复断言使用固定 sleep 容易引发偶发失败 (2026-04-04)

*   **问题描述**: `tests/scheduler/test_concurrent_generation.py` 通过固定 `sleep(0.3)` 等待后台恢复逻辑，机器稍慢时会误判失败。
*   **复现步骤**:
    *   在项目根目录执行 `.\venv_core\Scripts\python.exe -m pytest tests\scheduler\test_concurrent_generation.py -q -o addopts= --ignore=lib64`
*   **预期行为**: 测试应等待到后台恢复逻辑真正发生，而不是依赖固定时间片
*   **实际行为**: 某些环境下 `restore_llm_to_gpu` 尚未触发，断言提前失败
*   **解决方案**:
    *   改为轮询等待 `restore_llm_to_gpu.call_count`
    *   设置合理截止时间，既保留异步语义又减少误报

### 10.32 单文件脚本测试使用了错误的项目根路径 (2026-04-04)

*   **问题描述**: `tests/unit/test_image_models_fix.py` 直接运行时，把 `tests` 目录而不是项目根目录加入 `sys.path`，导致无法导入 `core` 包。
*   **复现步骤**:
    *   在项目根目录执行 `.\venv_core\Scripts\python.exe tests\unit\test_image_models_fix.py`
*   **预期行为**: 测试脚本能直接导入 `core.image.image_manager`
*   **实际行为**: 报 `ModuleNotFoundError: No module named 'core'`
*   **解决方案**:
    *   将根路径解析改为 `Path(__file__).resolve().parents[2]`
    *   同时把终端输出改成 ASCII 标记，避免 Windows 控制台字符集问题

### 10.31 Windows 下 pytest 会因 `lib64` 目录探测报 WinError 1920 (2026-04-03)

*   **问题描述**: 在 Windows 环境直接执行 `pytest` 单测时，测试还没开始收集就因为访问项目根目录下的 `lib64` 路径失败而中断。
*   **复现步骤**:
    *   在项目根目录执行 `.\venv_core\Scripts\python.exe -m pytest tests\integration\test_resource_manager.py -q -o addopts=`。
*   **预期行为**: pytest 正常收集并执行指定测试文件。
*   **实际行为**: pytest 在 `pytest_ignore_collect` 阶段访问 `D:\AI\xiaoyou-core\lib64`，抛出 `OSError: [WinError 1920] 系统无法访问此文件`。
*   **解决方案**:
    *   临时执行命令时显式加上 `--ignore=lib64`。
    *   后续如果要彻底收敛，可在 pytest 配置或目录布局里继续处理该路径的 Windows 兼容性。

### 10.30 安全改造验证阶段缺少基础开发依赖 (2026-03-12)

*   **问题描述**: 执行安全改造后的校验命令时，`ruff` / `mypy` 无法运行；使用 `TestClient` 导入 `main.py` 时触发 `ModuleNotFoundError: transformers`。
*   **复现步骤**:
    *   在项目根目录执行 `python -m ruff check ...`、`python -m mypy ...`。
    *   执行 `python -c "from fastapi.testclient import TestClient; import main; ..."`。
*   **预期行为**: 可以直接完成 lint/typecheck 与最小化接口行为验证。
*   **实际行为**:
    *   提示 `No module named ruff` / `No module named mypy`。
    *   导入主应用链路时因缺少 `transformers` 依赖中断。
*   **解决方案**:
    *   在验证环境安装开发依赖（至少 `ruff`、`mypy`）与运行时关键依赖（至少 `transformers`）。
    *   依赖不全时，先执行 `py_compile` 做语法校验，并在变更说明中标记“运行时验证受环境依赖阻断”。

### 10.35 本地 venv_core 缺少 ruff/mypy 导致静态校验不可执行 (2026-03-09)

*   **问题描述**: 按项目流程执行 lint/typecheck 时，`python -m ruff` 与 `python -m mypy` 均报模块不存在。
*   **复现步骤**:
    *   在 `venv_core` 环境执行 `python -m ruff check ...`。
    *   在 `venv_core` 环境执行 `python -m mypy ...`。
*   **预期行为**: 能正常执行 ruff 与 mypy 校验。
*   **实际行为**: 返回 `No module named ruff` / `No module named mypy`。
*   **解决方案**: 当前先以诊断脚本联调验证功能正确性；后续统一补齐 dev 依赖后恢复静态校验流程。

### 10.30 压力测试结束阶段周期任务仍提交导致报错 (2026-02-18)

*   **问题描述**: 运行大规模压力测试后，日志出现 `Periodic task cleanup_completed_tasks submission failed: Scheduler not started`。
*   **复现步骤**:
    *   运行 `legacy/mvp_core/experiments/scalability/large_scale_stress_test.py`，结束阶段观察日志。
*   **预期行为**: 调度器停止后不再提交新的周期任务，且不应出现“未启动”类错误日志。
*   **实际行为**: stop 触发后仍有周期任务 wrapper 尝试提交新任务，提交时调度器已停止导致报错。
*   **原因分析**: 周期任务循环未在每次提交前检查运行标志，停止流程与下一次 tick 存在竞态窗口。
*   **解决方案**: 周期任务 wrapper 在 sleep 与提交前均检查运行标志；stop 时先取消周期任务并等待退出，避免 stop 后继续提交。

### 10.29 崩溃恢复无背板对照实验崩溃前任务统计为0 (2026-02-18)

*   **问题描述**: 运行崩溃恢复对比实验时，无背板场景输出 `pre_crash_task_count = 0`，导致对照结论无效（看不出“丢失了什么任务”）。
*   **复现步骤**:
    *   在 WSL2 激活 `venv_mvp_core_cu128` 后执行 `legacy/mvp_core/experiments/recovery/crash_recovery_experiment.py --tasks 10 --comparison`。
*   **预期行为**: 无背板场景也应统计到崩溃前已提交的任务数量（例如 10），并在恢复后显示任务无法恢复（lost > 0）。
*   **实际行为**: 只有有背板场景会从 `StateBackplane.get_active_tasks()` 读取崩溃前任务；无背板场景不采集导致计数为 0。
*   **原因分析**: 崩溃前任务统计逻辑与 `StateBackplane` 强绑定，未提供无背板的统计口径。
*   **解决方案**: 从子进程输出中解析 `submitted with id ...` 的任务 ID 作为无背板场景的崩溃前任务集合，确保对照实验可量化。

### 10.29 pytest 单测大量失败与收集异常 (2026-02-16)

*   **问题描述**: 在 Windows 下运行全量单测时，出现大量失败；并且部分测试对接口的假设与当前实现不一致，导致收集/运行阶段报错或断言失败。
*   **复现步骤**:
    *   在项目根目录执行 `python -m pytest -q`。
*   **预期行为**: 现有单测应能通过，或至少能完整跑完并只跳过标注的 integration/gpu/e2e/slow 测试。
*   **实际行为**:
    *   多个测试失败（本次输出为 33 failed, 117 passed, 14 skipped）。
    *   典型失败包括：
        *   `tests/test_image_trigger_tightening.py`: `core.trm_adapter` 的图像意图识别与期望不一致（正例被判为 False）。
        *   `tests/test_context_overflow.py`: 期望 `core.agents.chat_agent_components.streaming` 暴露 `get_life_simulation_service` 等符号，但当前模块不存在该导出，导致 `AttributeError`。
        *   `tests/scripts/test_active_care_dynamic.py`: `ActiveCareService` 缺少 `consecutive_non_responses` 属性，导致多条用例直接 `AttributeError`。
        *   `tests/test_stream_utils.py`: `stream_utils` 的 `normalize_tilde_ending / looks_mostly_english / find_stream_boundary / StreamContextBuilder / TagParser / JSONStreamParser` 等接口/行为与单测预期不一致，出现断言失败或属性缺失。
*   **补充信息**:
    *   该问题与 `legacy/mvp_core` 的迁移实验脚本不直接耦合，但会阻塞用“全量 pytest”作为回归验证手段。
    *   运行脚本时出现 `torch.cuda` 关于 `pynvml` 的 FutureWarning（不影响执行，但建议后续统一处理依赖）。
*   **历史记录管理**: 新增前端清空历史记录功能（侧边栏/移动端底部），并在后端实现了 `POST /api/v1/memory/clear` 接口。
*   **异步保存机制**: 实现了异步保存线程和保存队列，减少频繁 IO 操作对系统性能的影响。
*   **延迟修剪机制**: 实现了记忆的延迟修剪，避免频繁修剪导致的性能问题。
*   **关键词索引优化**: 实现了关键词索引，加速搜索过程。

### 10.28 WSL2 运行实验脚本找不到 services 模块 (2026-02-16)

*   **问题描述**: 在 WSL2 中运行 `tests/verify_scheduler_overhead.py` 时，报错 `ModuleNotFoundError: No module named 'services'`。
*   **复现步骤**:
    *   在 WSL2 的 `~/mvp_core` 目录执行 `./venv/bin/python tests/verify_scheduler_overhead.py --preload`。
*   **预期行为**: 脚本能正常导入 `services.cpp_scheduler_engine` 并输出调度器开销 JSON。
*   **实际行为**: Python 无法解析 `services` 顶层包导致脚本直接退出。
*   **原因分析**: 以脚本方式运行时，`sys.path` 不一定包含 `mvp_core` 根目录，导致 `services/` 目录不可见。
*   **解决方案**: 在脚本启动时将 `mvp_core` 根目录插入 `sys.path`（以 `_find_mvp_root()` 结果为准）。

### 10.20 Windows 后端 Study Tool 路径解析失败 (2026-02-04)

*   **问题描述**: 在 Project 标签页下，文件列表显示为空，提示无法加载。
*   **原因分析**: 前端请求路径默认为 `/`，在 Windows 后端环境下，Python 的 `os.path.abspath('/')` 会解析为驱动器根目录（如 `D:\`），而该目录通常不在项目的允许访问路径内，导致安全校验失败或找不到文件。
*   **解决方案**: 在 `StudyFileManager.tsx` 中增加路径转换逻辑，将根路径 `/` 映射为相对路径 `.`。
*   **经验总结**: 处理文件路径时需警惕 Unix-like 风格的路径在 Windows 下的副作用，优先使用相对路径或明确的子路径。

### 10.15 幽灵进程与内存泄漏修复 (2026-01-23)

*   **问题描述**: 主程序退出后，任务管理器中仍残留不可见的幽灵进程，占用大量内存 (3-4GB)，且多次启动会叠加导致系统 OOM，必须重启电脑才能解决。
*   **原因分析**: 
    *   **残留线程**: `uvicorn` 或依赖库（如 `transformers` / `pytorch` / `apscheduler`）的非守护线程在主程序收到退出信号后未能正确终止，阻止了 Python 进程的销毁。
    *   **Watchdog 失效**: 原有的 `_shutdown_watchdog` 仅在 `lifespan` 超时未完成时触发，而 `lifespan` 完成后控制权交回 `uvicorn`，若 `uvicorn` 自身卡死，则无机制兜底。
*   **解决方案**:
    *   **强制自杀机制**: 在 `core/lifecycle/lifespan.py` 的 `finally` 块末尾（即应用层清理完全结束后），增加 `_force_kill_self()` 调用。
    *   **进程树清理**: `_force_kill_self` 使用 `psutil` 递归终止当前进程及其所有子进程，确保无论 `uvicorn` 状态如何，进程树都会被彻底清除。
*   **效果**: 验证确认应用退出后进程彻底消失，内存被立即释放，无需重启系统。

### 10.38 Pytest 收集期 NameError 记录（2026-01-19）

*   **问题描述**: 运行 `python -m pytest` 时在收集阶段报错 `NameError: name 'Optional' is not defined`，导致多条测试用例无法收集。
*   **复现步骤**:
    *   在项目根目录运行 `python -m pytest`；
    *   观察 `core/core_engine/lifecycle_manager.py` 抛出 `Optional` 未定义异常。
*   **预期行为**: pytest 能正常完成收集阶段并继续执行测试。
*   **实际行为**: 收集阶段直接中断，多个测试文件因导入失败报错。
*   **解决方案**: 在 `lifecycle_manager.py` 中补齐 `Optional` 的类型导入。
*   **验证结果**:
    *   `benchmark_llm.py --mode tts`：首句（warmup）约 8.7s；稳态 p50≈1.97s，音频最大幅度约 0.55~0.70，非静音。
    *   `benchmark_llm.py --mode tts_concurrent --tts-concurrency 4`：并发下 per_req p50≈5.28s，表明单实例服务更接近串行处理，建议业务侧限流/排队。
    *   详细复测与命令记录见根目录 `TTS_EVALUATION_OPTIMIZATION_REPORT.md`。

### 10.8 优雅关闭与生命周期超时控制 (2026-01-02)

*   **多层级超时体系**: 建立了“总关闭超时 -> 单服务关闭超时 -> 强制退出看门狗”的三级防御体系。
    *   **Level 1 (Service)**: 每个服务在 `lifecycle_manager` 中拥有独立关闭时间窗口（默认 4s），防止单个服务（如数据库挂起）阻塞整体流程。
    *   **Level 2 (Application)**: FastAPI lifespan 整体关闭超时（默认 10s），协调 Uvicorn 与业务逻辑的退出节奏。
    *   **Level 3 (Watchdog)**: 后台守护线程（默认 20s），作为最后的兜底手段，通过 `os._exit` 强制终止僵尸进程。
*   **Windows 信号增强**: 通过 `SetConsoleCtrlHandler` 捕获 Windows 控制台关闭事件，确保在点击窗口关闭按钮时也能触发完整的优雅清理流程。
*   **日志降噪策略**: 针对关机时的预期异常（如 `CancelledError` 或已知库的运行时报错）进行拦截，避免输出大量无意义的堆栈信息，提升生产环境日志的可读性。

### 10.7 修复 UnboundLocalError (2025-12-21)

*   **问题**: `LLMModule.stream_chat` 中的 `_producer` 闭包直接引用外部 `prompt` 变量，在特定路径下重新赋值导致作用域混淆。
*   **修复**: 引入局部变量 `prompt_value` 承接外部值，消除作用域冲突。

### 10.67 `python -m pytest -q` 长时间无输出/疑似卡住（2025-12-21）

*   **问题描述**: 在仓库根目录执行 `python -m pytest -q`，长时间无输出，疑似卡在收集或某个测试启动阶段。
*   **复现步骤**:
    *   执行 `python -m pytest -q`；
    *   观察到命令长时间无输出或不结束。
*   **预期行为**: 测试应在合理时间内收集并执行，输出通过/失败信息。
*   **实际行为**: 无输出且不结束，需要手动终止。
*   **临时处置**:
    *   改为运行子集用例（例如 `python -m pytest -q tests/test_chat_agent.py tests/test_llm_module.py`）先保障核心链路可回归。

### 10.56 PowerShell PSReadLine 偶发崩溃（IndexOutOfRangeException）（2025-12-20）

*   **问题描述**:
    *   在 Trae/VSCode 集成终端中执行命令后，控制台出现 “Oops, something went wrong.”，并抛出 `System.IndexOutOfRangeException`，堆栈位于 `Microsoft.PowerShell.PSConsoleReadLine.*Render*`。
    *   现象多发生在输出较长、快速输入/粘贴较长命令或光标重绘频繁的场景下，导致当前终端会话不可用。
*   **复现步骤**:
    *   在 PowerShell 交互式终端中运行会产生较长输出的命令（例如 `git status -sb` / `git diff` / 打印长文本）；
    *   或在提示符处粘贴较长的提交信息/脚本片段后回车；
    *   观察终端出现 PSReadLine 的异常报告并中断输入循环。
*   **预期行为**:
    *   终端可稳定渲染长输出并继续接受输入。
*   **实际行为**:
    *   PSReadLine 渲染时越界，导致交互式输入循环崩溃。
*   **解决方案（Workaround）**:
    *   对自动化/脚本类命令使用 `pwsh -NoProfile -NonInteractive -Command "<cmd>"` 执行，绕过 PSReadLine；
    *   或在当前会话执行 `Remove-Module PSReadLine -ErrorAction SilentlyContinue` 临时卸载 PSReadLine 后继续操作。

### 10.55 性能报告指标数字漂移：文案与真实实验 JSON 不一致（2025-12-20）

*   **问题描述**:
    *   `legacy/mvp_core/System_Architecture_and_Performance_Report.tex` 中“真实负载性能对比”小节的吞吐量、P50/P95/P99 与 Event-loop lag 文案数字，与同次实验输出的 `legacy/mvp_core/experiment_results/*_real.json` 不一致。
*   **复现步骤**:
    *   打开 `legacy/mvp_core/experiment_results/xy_core_real.json`、`naive_async_real.json`、`single_thread_real.json`；
    *   对比 `results.exp1`（并发=10 的 `rps`）、`results.exp3_metrics`（p50/p95/p99）与 `results.exp2.max_lag`；
    *   在 TeX 中定位“真实负载吞吐量对比/延迟分布对比/详细指标分析”对应段落，观察数字不一致。
*   **预期行为**:
    *   图表与文字描述的关键数字应与 `*_real.json` 一致，可直接溯源。
*   **实际行为**:
    *   文案数字存在漂移（硬编码/旧实验残留），导致报告“可验证性”下降。
*   **解决方案**:
    *   以 `legacy/mvp_core/experiment_results/*_real.json` 为唯一来源，更新 TeX 中对应数字与日期；
    *   运行 `legacy/mvp_core/experiments/generate_real_charts.py` 重新生成 `real_throughput_comparison.pdf` 与 `real_latency_percentiles.pdf`，确保图表与文案同步。
*   **验证**:
    *   `xelatex -interaction=nonstopmode -halt-on-error System_Architecture_and_Performance_Report.tex` 成功输出 PDF；
    *   报告中的吞吐、分位数与卡顿峰值与 `*_real.json` 对齐。

### 10.54 LaTeX 编译失败：`lstlisting` 的 `caption` 逗号触发 `keyval` 解析错误（2025-12-20）

*   **问题描述**:
    *   在 XeLaTeX 编译 `legacy/mvp_core/System_Architecture_and_Performance_Report.tex` 时，若 `lstlisting` 的选项里写 `caption=... (Real Workload Capture, 2025-12-20)`，会报错 `Package keyval Error: 2025-12-20) undefined.`。
*   **复现步骤**:
    *   进入目录：`legacy/mvp_core`；
    *   执行：`xelatex -interaction=nonstopmode -halt-on-error System_Architecture_and_Performance_Report.tex`；
    *   观察日志中出现 `keyval` 相关错误并中止编译。
*   **预期行为**:
    *   报告应可稳定编译输出 PDF。
*   **实际行为**:
    *   编译在 `lstlisting` 环境处失败，提示 `keyval` 把 `caption` 中的逗号后内容当成了新的键值参数。
*   **解决方案**:
    *   将 `caption` 的值用花括号包裹，确保 `keyval` 不会把逗号当作选项分隔符：`caption={...}`。
*   **验证**:
    *   使用 XeLaTeX 成功输出 `System_Architecture_and_Performance_Report.pdf`。

### 10.46 Linux 安装依赖失败：`pywin32` / `pyreadline3` 等 Windows-only 包（2025-12-19）

*   **问题描述**: 在 Linux 环境执行 `pip install -r requirements.txt` 时，安装过程会因为 `pywin32` / `pyreadline3` / `win32_setctime` 等仅 Windows 可用的包而失败。
*   **复现步骤**:
    *   在 Linux 环境进入项目根目录；
    *   执行 `pip install -r requirements.txt`；
    *   观察到上述包下载/构建失败并中断安装。
*   **预期行为**: Linux 环境应自动跳过 Windows-only 依赖，至少能完成核心后端依赖安装。
*   **实际行为**: `requirements.txt` 无条件固定了 Windows-only 依赖，导致 Linux 无法安装。
*   **解决方案**: 为 Windows-only 依赖增加 PEP 508 平台条件（例如 `; platform_system == "Windows"`），使其仅在 Windows 环境安装。文件：`requirements.txt`。

### 10.35 编译exe时遇到的问题记录（2025-12-17）


*   **启动 EXE 弹窗 `ModuleNotFoundError: No module named 'torch._C'`**:
    *   **问题描述**: 打包后的 `XiaoyouCore.exe` 启动时弹出 torch 相关错误，导致无法进入主流程。
    *   **复现步骤**: 在未正确安装/打包 PyTorch（或 PyTorch 二进制不匹配）的环境启动 `XiaoyouCore.exe`。
    *   **预期行为**: 无论是否具备本地推理环境，应用都应能启动；仅在用户触发本地模型功能时再提示依赖缺失。
    *   `python -m pytest -q` 通过（存在第三方 `chromadb` 的 DeprecationWarning，未影响回归）；
    *   `python -m mypy .` 通过。
    *   **实际行为**: 启动阶段因顶层 `import torch` 触发 `torch._C` 导入失败而崩溃/弹窗。
    *   **解决方案**: 将 `torch` 作为可选依赖处理，避免在启动路径顶层导入；在需要使用本地推理/图像/语音模型时再做延迟导入，并在缺失时给出明确错误提示。

*   **启动 `XiaoyouCore.exe` 报错 `Unable to configure formatter 'default'` / `sys.stderr isatty`**:
    *   **问题描述**: PyInstaller `--windowed` 模式下 `sys.stdout/sys.stderr` 可能为 `None`，导致 Uvicorn 默认日志 formatter 初始化失败。
    *   **复现步骤**: 使用 `--windowed` 打包后运行 `XiaoyouCore.exe`，启动阶段触发 Uvicorn 日志配置。
    *   **预期行为**: 无控制台也能正常启动服务，并将日志输出到文件。
    *   **实际行为**: 启动时抛出 `AttributeError: 'NoneType' object has no attribute 'isatty'`，随后异常处理中的 `input()` 进一步报错 `lost sys.stdin`。
    *   **解决方案**: 在冻结环境检测到 `sys.stdout/sys.stderr` 不可用时，为 Uvicorn 提供基于文件的 `log_config`，并对 `input()` 做可用性保护。

*   **Electron 启动弹窗 `Cannot find package 'electron-updater'`**:
    *   **问题描述**: `electron-builder` 的 `build.files` 仅包含 `dist/**/*` 与 `electron/**/*`，未包含依赖模块时，生产环境无法解析 `electron-updater`。
    *   **复现步骤**: 打包后运行桌面端，主进程加载 `electron/main.js` 并初始化更新模块。
    *   **预期行为**: 桌面端可以启动；更新模块缺失时应自动降级。
    *   **实际行为**: 主进程抛出模块找不到错误并弹窗。
    *   **解决方案**: 将更新模块改为可选依赖（运行时动态导入，失败则跳过），后续如需启用自动更新再调整 `build.files` 以包含必要依赖。

### 10.33 技术参考拆分对齐与“文档漂移”问题记录 (2025-12-17)

*   **问题描述**: 技术参考文档（拆分版/总文档）与真实代码存在偏差，导致排查时误以为存在 `'/ws/message'` 等端点，实际路由为 `'/api/v1/ws'`。
*   **复现步骤**:
    *   先按文档尝试连接 `'/ws/message'`；
    *   再对照 `routers/websocket_router.py` 发现实际 WebSocket 路由前缀为 `'/api/v1/ws'`；
    *   继续对照 `core/interfaces/websocket/fastapi_websocket_adapter.py` 确认消息协议与处理落点。
*   **预期行为**: 文档中的“端点/入口/关键类”可以直接用来定位到源码。
*   **实际行为**: 文档中的端点与实现漂移，导致定位链路中断。
*   **处理方式**:
    *   在 `docs/technical_reference/02_system_architecture.md` 与 `PROJECT_TECHNICAL_REFERENCE.md` 增加“实现校对（代码落点）”小节；
    *   拆分版仅做主题分割与补充校对，不删除旧经验，避免丢失历史上下文。
*   **附带发现：缓存实现并存**:
    *   项目同时存在 `core/async_cache.py`（异步 LRU）与 `core/cache/async_cache_manager.py`（L1 内存 + L2 diskcache）。
    *   在新增/排障时应先确认调用方实际使用的是哪套缓存，避免误判“功能已接入但实际未使用”。

### 10.32 代码规范严格度、Flake8 与接口返回格式踩坑 (2025-12-17)

*   **结论**:
    *   “严格”本身不是目的，目的是 **把低成本可自动发现的问题前置**（上线前、合并前、提交前），让线上问题更少、定位更快。
    *   建议采用“分层严格”：先保证 **能跑、可测、可回归**，再逐步收紧风格类规范，避免一次性全项目推倒重来。
*   **Flake8 是什么**:
    *   Python 的静态检查工具（lint），能在运行前发现一类常见问题：未使用导入、未定义变量、语法/缩进错误、过宽异常捕获、风格不一致等。
    *   它的价值主要在于：把“运行时才爆炸”的问题，提前变成“保存/CI 就红”的问题。
*   **严格与不严格有什么区别**:
    *   **严格一点的收益**: 更早暴露低级错误（`NameError`、导入未用、异常吞掉、返回结构不一致）、减少线上灰度/回滚成本、减少多人协作时的风格摩擦。
    *   **过度严格的成本**: 旧代码/第三方/遗留目录会产生大量噪音，短期降低开发效率，导致“忽略一切告警”的反效果。
    *   **推荐策略**: 先修会导致 bug 的告警（未定义名、缩进、潜在异常吞掉、返回格式不一致），再对遗留目录做隔离或渐进治理。
*   **问题记录：超时路径返回了 StreamingResponse 导致测试失败**:
    *   **问题描述**: `test_handle_message_timeout_response_format` 报错 `TypeError: 'StreamingResponse' object is not subscriptable`。
    *   **复现步骤**:
        1. 运行 `pytest`；
        2. 触发 `/api/v1/message` 的超时逻辑；
        3. 测试代码按 JSON 结构读取返回值时发生类型错误。
    *   **预期行为**: 超时也应返回标准 JSON（例如 `{"success": False, "error": "...", ...}`），保证前端与测试一致解析。
    *   **实际行为**: 超时路径返回了 `StreamingResponse`（或与流式返回同型），导致调用方按字典访问失败。
    *   **修复方案**: 在超时分支强制走非流式 JSON 返回，避免出现“同一接口两种返回结构在异常路径下混用”的情况。
*   **问题记录：FastAPI 的 Query 参数 regex 弃用**:
    *   **问题描述**: 运行测试或启动服务时出现 `DeprecationWarning: 'regex' has been deprecated, please use 'pattern' instead`。
    *   **修复方案**: 将 `Query(..., regex=...)` 更新为 `Query(..., pattern=...)`，减少噪音并避免未来版本破坏性变更。
*   **经验总结：怎么把规范落地成“有用”**:
    *   用 lint/test 的输出推动“可执行”的改动：保证返回格式、错误分支、输入校验等对外契约一致。
    *   对遗留目录（`legacy/`、`demo/`、第三方）优先隔离，再逐步重构，避免规范变成阻塞开发的噪音源。
    *   对根目录进行归位整理：将散落的测试脚本统一移动到 `tests/`，将维护/排障脚本统一移动到 `maintenance/`，并同步维护两处 `README.md`，降低新成员上手成本。

### 10.18 PyInstaller 构建优化 (2025-12-15)

*   **问题描述**: 执行 `python build_exe.py` 时，PyInstaller 卡在 `Building PKG (CArchive) XiaoyouCore.pkg` 阶段，长时间无响应。
*   **原因分析**:
    *   **--onefile 模式**: 原配置使用单文件模式，试图将数 GB 的 PyTorch、CUDA 库及其他依赖压缩进单个 EXE 文件。此过程极度消耗 CPU 和内存，且耗时极长（看似卡死）。
    *   **启动缓慢**: 即使构建成功，单文件 EXE 每次启动时需解压临时文件，导致冷启动时间过长。
*   **解决方案**:
    *   **切换至 --onedir**: 修改 `build_exe.py` 使用目录模式。虽然总文件体积不变，但省去了压缩步骤，构建速度提升 10 倍以上，且启动速度更快。
    *   **禁用 UPX**: 添加 `--noupx` 参数，避免对大型二进制文件进行耗时的压缩尝试。
    *   **兼容性修复**: 更新 `main.py` 中的静态资源加载逻辑，兼容 `_MEIPASS` (onefile) 和 `onedir` (sys.executable dir) 两种模式，防止运行时找不到前端资源。

### 10.12 Windows环境下C++扩展编译避坑指南 (2025-12-15)

*   **问题描述**: 在 Windows 环境下编译 `llama-cpp-python` 或其他 CUDA 扩展时，常遇到 `cl.exe` 找不到、CMake 版本不兼容或 DLL 加载失败 (`ImportError: DLL load failed`)。

### QR-20260709-MEM-WATCHDOG MemoryWatchdog 屎山导致看门狗本身就是内存大户 + UIE 无谓加载 paddle 库 (2026-07-09)
*   **问题描述**: 用户反馈 `python main.py` 跑 14 小时后 RSS 飙到 8.5GB，想用 memory watcher 诊断却不知道看门狗默认关闭且代码本身是屎山。
*   **复现步骤**:
    1. tasklist 查看 python 进程 → PID 24008/24084/27612/5256/2872/21312/35948/31868 多个，其中 PID 24084 RSS=8.5GB
    2. Get-CimInstance Win32_Process -Filter 'ProcessId=24084' → cmdline=`python main.py`, cwd=D:\AI\xiaoyou-core, n_threads=478
    3. psutil.Process(24084).memory_maps() top 20 → 几乎全是 torch CUDA DLL（torch_cuda 763MB / cudnn 778MB / cublasLt 645MB / cusparse 341MB / cusolver 355MB / cufft 173MB / torch_cpu 208MB），还有 libpaddle.pyd 99MB + mklml.dll 80MB
    4. config/yaml/app.yaml: memory_watchdog.enabled=false → 看门狗根本没启动，今天的 xiaoyou_main.log 搜不到任何 MemoryWatchdog 记录
    5. core/utils/memory_watchdog.py 行 1-315 是轻量异步版、行 316-1101 是旧重量级版（_log_detailed_analysis 多次遍历 gc.get_objects()），同一文件两个 MemoryWatchdog 类共存
    6. core/services/data_ops/uie_extractor.py 行 126 `import paddle` 在行 148 模型文件检查之前 → ONNX 模型不存在 + paddle 模型也不存在时，paddle 库被无谓加载
*   **预期行为**:
    1. 看门狗默认应启用，主循环只采集 psutil 指标不阻塞
    2. 深度分析（gc.get_objects 遍历）只在 API 主动调用时执行，不应在主循环里反复跑
    3. UIE 在 ONNX 和 paddle 模型都不存在时，不应触发 `import paddle`
*   **实际行为**:
    1. 看门狗默认 enabled=false，从未启动
    2. memory_watchdog.py 文件里两个 MemoryWatchdog 类共存，旧版主循环每 5 次检查就会 3 次遍历 gc.get_objects()
    3. routers/admin/memory_watchdog.py 依赖旧版字段（loaded_models/object_counts/dump_top_objects），新版启用后 API 会报错
    4. UIE 在 ONNX 不存在时回退 paddle 分支，先 import paddle 再检查模型文件，导致 paddle 库常驻 ~180MB
*   **根因**:
    1. memory_watchdog.py 历史演进未清理：新版轻量异步类加在文件开头，旧版重量级类未删除，导致两个类共存
    2. routers/admin/memory_watchdog.py 跟着旧版字段写，未跟随新版同步更新
    3. uie_extractor._init_paddle_backend() 写法不严谨：import paddle 应在所有前置检查通过后才执行
*   **修复方案**:
    1. 重写 core/utils/memory_watchdog.py：删除旧版 MemoryWatchdog，统一为轻量异步版 + DetailedMemorySnapshot 按需接口
    2. 修复 routers/admin/memory_watchdog.py：top-objects/snapshot/ws/leak-analysis/trend 全部改用新接口
    3. 修复 uie_extractor._init_paddle_backend()：paddle 模型文件检查移到 `import paddle` 之前
    4. config/yaml/app.yaml: memory_watchdog.enabled=true，下次重启自动启动
*   **验证**:
    1. `ruff check core/utils/memory_watchdog.py routers/admin/memory_watchdog.py core/services/data_ops/uie_extractor.py → All checks passed`
    2. `python -c 'from core.utils.memory_watchdog import get_memory_watchdog; w=get_memory_watchdog(); w.take_detailed_snapshot(); w.analyze_top_objects(3); w.analyze_leak_source()' → 接口全部正常`

### QR-20260730-ERR-DOWNGRADE 紧急降级 perform_downgrade 非幂等导致 ErrorCollector LoggedError 重复上报 (2026-07-30)
*   **问题描述**: 错误上报系统持续产生 LoggedError（err_fa14c1475137），错误消息为「[降级执行] 应用紧急降级措施」，源自 resource_monitor.py:458 _emergency_downgrade。系统资源紧张期间错误日志被大量重复写入。
*   **复现步骤**:
    1. 系统内存≥96% 或 CPU≥99% 触发免疫系统紧急降级
    2. immune/service._apply_resource_response 每 10s tick 调用 monitor.perform_downgrade(level=3)
    3. perform_downgrade 非幂等，每次调用执行 _emergency_downgrade 并 logger.error 记录
    4. ErrorCollectorHandler 捕获 ERROR+ 日志，作为 LoggedError 上报（每条带新 error_id）
    5. 紧急状态持续 1 分钟即产生 6 条错误上报，并触发错误暴增检测
*   **预期行为**:
    1. perform_downgrade 幂等：同级别重复调用不应重复执行降级动作和日志
    2. 紧急降级日志应为 WARNING 级别（保护性响应），不应被 ErrorCollector 当作 LoggedError 上报
    3. immune 服务同级别状态下不应每 tick 重复调用 perform_downgrade
    4. 恢复(level=0)时应清除降级环境变量标记
*   **实际行为**:
    1. perform_downgrade 每次调用都重新执行降级并记录日志，无幂等控制
    2. _emergency_downgrade 使用 logger.error，被 ErrorCollectorHandler 捕获为 LoggedError 重复上报
    3. immune 紧急/中度分支无状态转移检查，每 tick 重复调用 perform_downgrade
    4. 恢复时不清除降级环境变量标记，其他模块误判系统仍处于降级状态
*   **根因**:
    1. perform_downgrade 缺少 _applied_downgrade_level 幂等跟踪字段
    2. _emergency_downgrade 日志级别错误使用 error 而非 warning（与 _medium_downgrade/_heavy_downgrade 的 warning 不一致）
    3. immune/service._apply_resource_response 紧急/中度分支遗漏状态转移检查（恢复分支有）
    4. perform_downgrade(level=0) 未实现环境变量清理
*   **修复方案**:
    1. perform_downgrade 增加 _applied_downgrade_level 幂等控制，同级别跳过执行
    2. _emergency_downgrade 日志级别 error → warning
    3. 新增 _clear_downgrade_markers，level=0 时清除 5 个降级环境变量
    4. immune 紧急/中度分支增加 _last_downgrade_level 转移检查
*   **验证**:
    1. `venv_core\Scripts\python tests\scripts\monitoring\verify_downgrade_idempotent_2026_07_30.py → 5/5 通过`
    2. `venv_core\Scripts\python -m ruff check → All checks passed`

### AOS-0805-07 TRAE sandbox 禁止新建 Gradle daemon 日志导致编译失败 (2026-08-05)
*   **问题描述**: 在 TRAE Agent 内部运行 gradlew :app:compileDebugKotlin 时，Gradle 尝试在 D:\gradle_cache\daemon\8.14.3\daemon-<pid>.out.log 新建日志文件被 TRAE 沙箱阻止，报 FileNotFoundException(拒绝访问)；即使用 --no-daemon 也会先 fork 一个单用途 daemon 初始化而失败。
*   **复现步骤**:
    1. 先 Stop-Process 杀掉残留 Java Gradle daemon
    2. 在 TRAE Agent 中执行 gradlew :app:compileDebugKotlin --no-daemon
*   **预期行为**:
    1. 允许 Gradle 在 GRADLE_USER_HOME 下写入 daemon/caches/wrapper 等子目录
    2. 或提供可替代的 GRADLE_USER_HOME 到项目内目录，同时避免 wrapper 重新下载 distribution
*   **实际行为**:
    1. TRAE Sandbox Error: hit restricted Not allow operate files: D:\gradle_cache\daemon\8.14.3\daemon-61796.out.log
*   **根因**:
    1. TRAE Conversation 的 Custom Sandbox Configuration 默认未将全局 D:\gradle_cache 加入白名单
    2. 在 Agent 中先杀了 daemon 进程，后续每次编译都需要新建 daemon out log，首次编译时 daemon 已存在所以能过
*   **修复方案**:
    1. 用户手动在 Settings → Conversation → Custom Sandbox Configuration 放行 D:\gradle_cache 完整目录（读+写）
    2. 或：设置环境变量 GRADLE_USER_HOME 指向项目内路径(如 d:\AI\xiaoyou-core\clients\frontend\aveline-android\.gradle_home) 并把 D:\gradle_cache 下的 daemon/wrapper/caches 做 Junction/复制（复制约 1~3GB）
    3. 或：不再先 Stop-Process 杀 java daemon；编译成功一次后保持 daemon 运行，复用存活 daemon 不会新建 out.log
*   **验证**:
    1. `执行 gradlew :app:compileDebugKotlin 不再报 sandbox restricted`

### AC-082 module 日志文件集体停止写入（QueueListener 重启后 handler 丢失） (2026-08-10)
*   **问题描述**: 08-10 早上 active_care_schedule.log、active_care_messages.log、peer_chat.log 等 9 个 module 日志在 05:21:37-49 集体停止写入，但主日志 xiaoyou_main.log 持续到 07:29
*   **复现步骤**:
    1. 观察 logs/2026/8/9 目录：9 个 module 日志 LastWriteTime 均为 2026/8/10 5:21，无轮转备份文件
    2. xiaoyou_main.log 持续写入至 07:29，说明日志系统整体未挂
    3. 所有停止的都是 get_module_logger 创建的 module 日志，main handler 正常
*   **预期行为**:
    1. module 日志持续写入，与主日志同步
*   **实际行为**:
    1. 9 个 module 日志在 05:21 集体停止，主日志继续
*   **根因**:
    1. QueueListener 在 05:21 被 monitor 判定卡住而重启(_restart_queue_listener)
    2. _setup_handlers 重建时只挂载 main handler，get_module_logger 动态 append 的 module fh 全部丢失
    3. _module_file_handlers 缓存命中，get_module_logger 不再重新 append，module 日志永久丢失
*   **修复方案**:
    1. _setup_handlers 创建 QueueListener 时收集 _module_file_handlers 全部 fh 一并挂载
*   **验证**:
    1. `重启后 module 日志持续写入`

### QR-20260813-IMPORT-DEADLOCK 启动卡死无输出 + 工具注册失败 + 日志黑白（core.utils 分组重构遗留 import 死锁） (2026-08-13)
*   **问题描述**: 解耦 chat_handlers.py 后启动 launcher 一直卡在 Starting 界面无任何输出；随后又出现 TOOL_REGISTRY 工具 import 失败；控制台日志失去红绿黄颜色。
*   **复现步骤**:
    1. 运行 start.bat / python main.py，进程在 import 阶段永久挂起（无 traceback、不退出）
    2. 工具注册阶段报 cannot import name 'singleton' from 'singleton' (unknown location)
    3. 控制台日志从彩色变为黑白
*   **预期行为**:
    1. 正常启动、工具正常注册、控制台日志保持红绿黄彩色
*   **实际行为**:
    1. 启动卡死无输出；工具注册失败；日志变黑白
*   **根因**:
    1. core/utils/logger.py 的 _loggers_lock 用普通 threading.Lock()，初始化期同一线程递归 get_logger()（logger->config->core.utils.common->get_logger）死锁，进程挂起无输出
    2. core/utils/logger.py 末尾用空代理模块替换 sys.modules[__name__] 且未复制原模块属性，from core.utils.logger import get_logger 报 (unknown location)
    3. core/utils/concurrency/__init__ 把同名函数 singleton 导入包命名空间，core/utils/__init__.py 用 import core.utils.concurrency.singleton as _m 属性访问拿到函数而非模块，sys.modules['core.utils.singleton'] 被污染，工具注册 from core.utils.singleton import singleton 失败
    4. core/utils 分组重构后，resource_lock.py / error_collector.py / memory_watchdog.py 仍用旧路径 import（core.utils.async_locks / time_utils），在包初始化早期触发时崩
    5. 日志分组重构删除了 colorama / COLORS / 带 ANSI 转义的 ColoredFormatter 格式串，控制台日志变黑白
*   **修复方案**:
    1. core/utils/logger.py: _loggers_lock 改 threading.RLock()；模块替换改为复制原模块 __dict__ 到代理实例，sys 引用改 _sys
    2. core/utils/__init__.py: 改用 importlib.import_module 按完整模块名强制导入子模块，避免被包命名空间同名函数遮蔽；删除 core.utils 顶层多余的 singleton/SingletonFactory 函数别名
    3. core/utils/concurrency/resource_lock.py、errors/error_collector.py、memory_watchdog.py: 旧路径 import 改为新路径（concurrency.* / time.*）
    4. core/utils/logging/formatters.py + registry.py + logger.py: 恢复 colorama.init(autoreset=True) 于 logger.py 顶层；ColoredFormatter 沿用 HEAD 行为（不整行染色，颜色由格式串 colorama 转义控制：时间青、模块名品红）；registry.py 格式串还原为 HEAD 原版
*   **验证**:
    1. `python -m py_compile + compileall 通过`
    2. `faulthandler.dump_traceback_later 定位 import 卡点（logger 死锁），修复后 import main 在 60s 内正常完成`
    3. `from core.utils.singleton import singleton, SingletonFactory 成功，工具注册无 TOOL_REGISTRY import 失败 WARNING`
    4. `日志 INFO/WARNING/ERROR 正常输出，颜色由 ColoredFormatter 格式串恢复`

### 20260816-01 auto_commit_push.py 每日自动提交脚本卡死且无输出 (2026-08-16)
*   **问题描述**: 运行 scripts/git/auto_commit_push.py 时进程长时间挂起，控制台看不到任何输出，多次运行均卡死；期间进程 CPU 持续累加，存在多对残留进程。
*   **复现步骤**:
    1. 在 PowerShell 中运行 venv_core\Scripts\python.exe scripts\git\auto_commit_push.py
    2. 观察输出（无任何行打印）与进程状态（python + git 进程持续存活）
    3. 查看 git status / git log 确认无新提交产生
*   **预期行为**:
    1. 脚本逐步打印进度并最终完成提交与推送，退出码 0
    2. 若发现敏感信息则以退出码 2 结束并打印告警
*   **实际行为**:
    1. 进程永久挂起无输出，退出码永远不返回
    2. git ls-files --others 返回 25909 个未跟踪文件（.gradle-home/ 构建缓存未忽略），导致变更文件数 26043
    3. git log 无新提交（所有卡死实例均未走到 commit）
*   **根因**:
    1. Windows 下 subprocess.run 超时只杀主进程，git 孙进程占用管道导致 communicate() 永不返回
    2. .gradle-home/ 构建缓存目录（2.6 万文件）未加入 .gitignore
    3. stdout 全缓冲导致挂起时看不到任何输出
*   **修复方案**:
    1. run_cmd 超时后用 taskkill /T 递归清理进程树
    2. git 网络命令加 GIT_TERMINAL_PROMPT=0 / GCM_INTERACTIVE=never
    3. .gitignore 增加 .gradle-home/ 规则
    4. stdout 改行缓冲，QQ 号正则排除浮点时间戳
*   **验证**:
    1. `脚本完整跑通并推送成功，退出码 0`
    2. `变更文件数从 26043 降至 190`

### ANDROID-BUILD-ASM-SNAPSHOT-001 Android ASM 转换输出快照偶发缺少 META-INF (2026-08-17)
*   **问题描述**: Gradle 任务 transformDebugClassesWithAsm 完成后读取 classesOutputDir 时报告 META-INF 不存在，构建失败。
*   **复现步骤**:
    1. 存在残留或并发 Gradle 构建时执行 Android Debug 构建
    2. 任务进入 transformDebugClassesWithAsm 输出快照阶段
*   **预期行为**:
    1. ASM 输出目录保持稳定并完成 Gradle 增量快照
*   **实际行为**:
    1. Gradle 报 NoSuchFileException，缺失路径为 transformDebugClassesWithAsm/dirs/META-INF
*   **根因**:
    1. 可再生的 ASM 中间输出处于不一致状态，或有并发 Gradle 进程同时修改同一 app/build 目录
*   **修复方案**:
    1. 停止残留 Gradle 守护进程
    2. 仅删除已校验位于 app/build/intermediates/classes/debug 下的 transformDebugClassesWithAsm 中间目录
    3. 以单进程重新执行失败任务
*   **验证**:
    1. `gradlew.bat :app:transformDebugClassesWithAsm --no-daemon --stacktrace：BUILD SUCCESSFUL`

### ANDROID-CI-002 Android CI 启动 Wrapper 后在 10 秒网络超时 (2026-08-17)
*   **问题描述**: GitHub Actions 已成功检出包含 gradle-wrapper.jar 的仓库并启动 Gradle 命令，但单元测试步骤约 10 秒后退出，后续构建被跳过。
*   **复现步骤**:
    1. GitHub Actions 在全新 Ubuntu runner 检出 Android 工程
    2. 执行 ./gradlew :app:testDebugUnitTest
    3. Wrapper 尝试从腾讯镜像下载 Gradle 8.14.3 完整发行包
*   **预期行为**:
    1. GitHub runner 成功下载并校验 Gradle 发行包，然后进入 Android 单元测试
*   **实际行为**:
    1. Gradle 命令在与 networkTimeout=10000 对应的约 10 秒后退出
*   **根因**:
    1. 海外 GitHub runner 访问面向中国大陆本地环境选择的腾讯镜像不稳定
    2. 10 秒网络超时不足以覆盖全新 runner 首次下载 Gradle 完整发行包
*   **修复方案**:
    1. 在 CI 工作流中临时将下载源切换为 services.gradle.org/distributions
    2. 在 CI 工作流中临时把 networkTimeout 调整为 60000 毫秒
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_frontend\verify_android_ci_integrity.py`

### ANDROID-GRADLE-CODEX-LOCK-001 Codex Gradle 构建阻塞 Android Studio Configuration Cache (2026-08-18)
*   **问题描述**: Codex 启动 Android Gradle 编译后长时间占用项目 Configuration Cache，Android Studio 构建等待锁并超时。
*   **复现步骤**:
    1. 在 Codex 中启动 gradlew Android 编译任务
    2. 任务仍运行时在 Android Studio 中执行构建
    3. Android Studio 等待 configuration-cache.lock 并超时
*   **预期行为**:
    1. Codex 不与 Android Studio 并行争用项目 Gradle 缓存
    2. Android 编译默认由 Android Studio 完成
*   **实际行为**:
    1. Codex Gradle PID 37480 持有 Configuration Cache 锁
    2. Android Studio 构建进程无法取得锁
*   **根因**:
    1. 缺少禁止 Codex 默认执行 Android Gradle 构建的项目级规则
    2. 任务中断后 Gradle 子进程仍继续运行
*   **修复方案**:
    1. 结束 Codex 启动的 Gradle 持锁进程及关联客户端进程
    2. 在 AGENTS.md 与 .trae/rules/project_rules.md 增加 Android Gradle 构建约束
*   **验证**:
    1. `确认 PID 37480 已结束`
    2. `确认关联 PID 2536 已结束`

### QT-2026-0824-001 Android CI 单元测试因硬编码 JDK 路径失败 (2026-08-24)
*   **问题描述**: 上传到 GitHub 后 android-ci.yml 的 testDebugUnitTest 一直失败，报 'Value C:\Program Files\Java\jdk-17 given for org.gradle.java.home gradle property is invalid'
*   **复现步骤**:
    1. 修改 aveline-android 相关文件并 push 到 GitHub
    2. 触发 .github/workflows/android-ci.yml 的 test-and-build job
    3. setup-java 安装 JDK 17 后执行 ./gradlew :app:testDebugUnitTest
*   **预期行为**:
    1. Gradle 使用 setup-java 提供的 JDK 17 正常执行单元测试
*   **实际行为**:
    1. Gradle 启动即失败，报 Java home supplied is invalid
*   **根因**:
    1. aveline-android/android/gradle.properties 硬编码 org.gradle.java.home 指向 Windows 本地 JDK 路径
    2. 该配置在 Linux CI runner 上不存在，且优先级高于 JAVA_HOME
*   **修复方案**:
    1. 删除 gradle.properties 中 org.gradle.java.home 硬编码行，改为依赖 JAVA_HOME 自动探测
*   **验证**:
    1. `本地 JAVA_HOME 与 CI setup-java 均提供 JDK 17，跨平台行为一致`

### QR-20260824-CUDA-BUILD-PATH-CASE Codex 环境 PATH 大小写重复导致 MSBuild 工具启动失败 (2026-08-24)
*   **问题描述**: CUDA CMake 工程配置成功后，MSBuild 在并行构建或启动 link.exe 时出现映射盘工程路径不可见，或因环境中同时存在 Path 与 PATH 抛出 MSB6001。
*   **复现步骤**:
    1. 在 Codex PowerShell 环境运行 scripts/cpp_scheduler/build_cuda.ps1
    2. CMake 通过 Z: subst 完成配置
    3. MSBuild 并行节点读取 Z: 工程或创建 link.exe 子进程
*   **预期行为**:
    1. 构建脚本在配置完成后正常编译 CUDA scheduler_py
*   **实际行为**:
    1. 并行构建曾报 scheduler_py.vcxproj 或依赖 vcxproj 路径不存在
    2. 直接 MSBuild 曾因环境字典同时包含 Path 与 PATH 抛出 MSB6001
*   **根因**:
    1. Codex 进程环境同时带有大小写不同的 Path/PATH，旧版 .NET Framework ProcessStartInfo 使用大小写不敏感字典时冲突
    2. subst 映射在并行 MSBuild 子节点中表现不稳定
*   **修复方案**:
    1. 本次验证使用单节点 MSBuild，并在 ProcessStartInfo 中重建大小写去重后的环境块
    2. 不清理构建目录，复用 CMake 已生成工程完成增量构建
*   **验证**:
    1. `scheduler_py Release 最终构建为 0 warnings, 0 errors`

### QR-20260825-QQ-CPU-ENV QQ Adapter 与主程序使用不同虚拟环境导致 Transformers 误报缺少 PyTorch (2026-08-25)
*   **问题描述**: 主程序使用 venv_cpu 启动时，QQ 表情包语义检索终端仍打印 Transformers 未发现 PyTorch，造成 CPU 环境缺少 Torch 的误判。
*   **复现步骤**:
    1. 通过根目录 start.bat 启动主程序
    2. 通过 QQ 启动脚本启动独立 Adapter
    3. 触发表情包语义检索并观察 meme_search 后的 Transformers 告警
*   **预期行为**:
    1. QQ Adapter 与主程序优先使用同一个 venv_cpu
    2. Transformers 能识别 venv_cpu 中的 CPU 版 Torch
*   **实际行为**:
    1. QQ Adapter 启动入口硬编码 venv_core
    2. venv_core 虽能导入 Torch 2.11.0+cu128，但 Torch dist-info 元数据异常，Transformers 将其判定为不可用
*   **根因**:
    1. QQ 启动脚本没有复用主程序的默认环境优先级
    2. venv_core 遗留多个异常 Torch 元数据目录，pip show torch 无法识别安装
*   **修复方案**:
    1. 全部 QQ 启动入口统一为 venv_cpu 优先、venv_core 回退
    2. 增加静态验证脚本防止后续启动环境再次分叉
*   **验证**:
    1. `四个 QQ 启动入口的环境优先级检查通过`
    2. `venv_cpu 中 Torch、Transformers、WebSocket 与 ONNX Runtime 实际导入通过`

### QR-20260825-ENV-DEPS venv_core Torch 元数据损坏与双环境依赖锁漂移 (2026-08-25)
*   **问题描述**: venv_core 的 Torch 代码可运行但合法 dist-info 缺失，导致 Transformers 判定 PyTorch 不可用；venv_cpu 与 venv_core 同时存在重复元数据和 protobuf 依赖冲突。
*   **复现步骤**:
    1. 分别运行两套环境的 pip check
    2. 检查 site-packages 中以波浪号开头及同名重复的 dist-info
    3. 在 venv_core 中对比 torch.__version__ 与 importlib.metadata.version('torch')
    4. 用 venv_cpu 导入 clients.bots.qq.meme_search 并检查 transformers.is_torch_available()
*   **预期行为**:
    1. 两套环境 pip check 均通过
    2. 每个发行版仅有一份合法元数据
    3. CPU/GPU Torch 三件套分别与锁文件一致
    4. QQ 表情检索链能够识别 PyTorch
*   **实际行为**:
    1. venv_core 存在 ~orch 2.11/2.12 残留且元数据查询不到 torch
    2. 两套环境存在 protobuf 3.20.2 与 OpenTelemetry 1.42 的冲突
    3. Qwen-TTS 声明的 Gradio 未安装
*   **根因**:
    1. venv_core 曾被不完整升级或卸载，留下以波浪号开头的临时元数据
    2. requirements 未锁定 PaddleNLP 所需 protobuf 对应的旧版 OpenTelemetry 依赖族
    3. CPU/GPU Torch 锁与实际验证过的组合不同步
*   **修复方案**:
    1. 可回滚迁移异常元数据并恢复 Torch 2.11 合法元数据名
    2. 锁定兼容的 protobuf、Google protos、OpenTelemetry、Gradio 与 OpenCV 组合
    3. 增加 requirements 布局说明和运行时自动验证
*   **验证**:
    1. `venv_cpu\Scripts\python.exe tests\scripts\environment\verify_runtime_dependencies.py --environment cpu`
    2. `venv_core\Scripts\python.exe tests\scripts\environment\verify_runtime_dependencies.py --environment gpu`
