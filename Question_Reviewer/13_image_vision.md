# 图片生成与视觉

本分类共 15 条记录。按时间倒序（最新在前）排列。

---

### 10.80 图片生成误触发：过去时态"画了个画"等描述性语句错误触发图片生成 (2026-05-05)

*   **问题描述**: 用户发送"但是他并不会忘，我最开始给他画了个画，他都还记得"，系统误判为图片生成请求，提取"了个画，他都还记得..."作为 prompt 触发图片生成
*   **复现步骤**:
    1. 用户在聊天中提到过去画画的经历（如"画了个画"、"画过一幅画"等）
    2. 系统的 `extract_image_request_prompt()` 匹配到单独的 `'画'` 关键词
    3. 提取关键词后的所有文本作为图片 prompt
    4. 触发图片生成流程
*   **预期行为**: 过去时态的描述性语句不应触发图片生成
*   **实际行为**: "画了个画"被误判为图片生成请求
*   **根因**:
    1. `extract_image_request_prompt()` 中单独的 `'画'` 关键词过于宽泛，匹配任何包含"画"字的文本
    2. 负面模式不覆盖过去时态（画了、画过、画完等）
    3. BERT 路径的 `classify_intent()` 缺少 IMAGE_GEN 安全守卫
*   **修复**: 移除单独 `'画'` 关键词，补充具体关键词和负面模式，添加 BERT 安全守卫

### 10.61 NapCat无法识别本地路径的CQ码图片 (2026-04-30)

*   **问题描述**: 发送表情包时NapCat报错`ENOENT: no such file or directory`，文件路径中的下划线被去掉，导致路径不存在
*   **复现步骤**:
    1. AI触发自动表情包，生成CQ码`[CQ:image,file=D:/AI/.../astrbot_plugin_meme_manager-main/...]`
    2. `send_to_napcat`中`_strip_markdown_for_qq`将`_plugin_meme_`匹配为Markdown斜体`_xxx_`
    3. 路径变成`astrbotpluginmeme_manager-main`（下划线被去掉）
    4. NapCat尝试访问不存在的路径，报错`ENOENT`
*   **预期行为**: 表情包正常发送，路径中的下划线不被修改
*   **实际行为**: 路径中下划线被Markdown清理函数去掉，文件找不到
*   **根因**: `_strip_markdown_for_qq`的`_(.+?)_`正则把路径中的下划线当作Markdown斜体标记去掉了。CQ码中的文件路径不应该被Markdown清理
*   **修复**: `send_to_napcat`中，如果消息包含`[CQ:`标签，跳过`_strip_markdown_for_qq`和`_strip_trailing_periods_for_qq`处理

### 10.57 Vision描述误触发本地意图匹配 (2026-04-30)

*   **问题描述**: 用户发送图片时，Vision模型对图片的描述文本被错误匹配到SHOW_STATUS本地意图，导致图片消息被误判为"查看状态"指令
*   **复现步骤**:
    1. 用户发送一张包含系统/状态相关内容的图片（如系统监控截图）
    2. Vision模型描述图片内容，生成如"【你看到了一张图片：这是一个系统监控面板，显示CPU占用80%...】"
    3. 描述文本被前置拼接到`display_msg`中
    4. `clean_msg`从`display_msg`派生，包含Vision描述
    5. Fast Path正则`(查看|看看|看下|显示).*(状态|系统|负载|占用)`匹配到描述中的关键词
    6. SHOW_STATUS意图被错误触发（confidence=1.0）
*   **预期行为**: 图片消息应正常进入AI对话流程，Vision描述仅作为上下文提供给AI，不应参与意图匹配
*   **实际行为**: Vision描述中的关键词触发了SHOW_STATUS意图，消息被错误路由到状态汇报流程
*   **根因**: `_run_message_pipeline`中，Vision描述被前置到`display_msg`，而`clean_msg`直接从`display_msg`派生用于意图匹配，没有剥离Vision描述前缀。Slow Path有`_has_explicit_command_tone()`保护，但Fast Path无任何保护
*   **修复**: 在意图匹配前，从`clean_msg`中剥离Vision描述前缀（`【你看到了...】`），生成`clean_intent_msg`用于Fast Path和Slow Path意图匹配，而`clean_msg`（含Vision描述）仍用于Stage 4的AI对话

### 10.15 ComfyUI 工作流 KSampler `latent=None` 排障记录 (2026-01-19)

*   **问题描述**: ComfyUI 后端日志出现 `ImpactSwitch: invalid select index (ignored)`，随后在 `KSampler` 报错 `TypeError: 'NoneType' object is not subscriptable`（`latent["samples"]` 处）。
*   **复现步骤**:
    *   打开 `01_基础漫画角色固定模版.json`（或同结构的 03/04 工作流），直接执行。
    *   观察到 Switch 节点输出为 `None`，KSampler 收到空 latent 并崩溃。
*   **原因分析**:
    *   `ComfyUI-Impact-Pack` 内部将 `LatentSwitch` 注册为通用的 `GeneralSwitch`（输入槽名为 `input1/input2/...`）。
    *   工作流 JSON 中保存的输入槽名为 `latent1/latent2`，导致执行期 `kwargs` 中找不到被选择的输入，Switch 返回 `None`。
*   **解决方案**:
    *   将工作流中的 Switch 节点调整为 `ImpactSwitch` 语义（本质仍是 `GeneralSwitch`），并把输入槽名改为 `input1/input2`。
    *   补齐 Switch 的 `widgets_values` 为 `[1, false]`（默认选 `input1`，并使用 `select_on_execution`）。
    *   约定：默认 `select=1` 走 txt2img（空 latent），需要 img2img 时改为 `select=2` 且在 `LoadImage` 里选图。
    *   如果仍出现 `invalid select index`，可在 ImpactPack 的 `GeneralSwitch` 中启用“选中缺失则回退 input1”的兜底逻辑，避免将 `None` 传播到 KSampler。

### 10.14.3 生图结束后 LLM 回迁失败但缺少原因：补齐失败细节与自动重试 (2026-01-08)

*   **问题描述**:
    *   生图结束后日志只出现 `LLM 引擎回迁至 GPU 失败`，缺少具体失败原因（超时/异常/后端/最后一次加载错误），排障困难。
    *   部分机器在 Forge 卸载完成后的数秒内仍会出现显存回收/碎片化抖动，导致第一次恢复失败，但稍后重试可以成功。
*   **复现步骤**:
    *   触发一次 Forge 生图；
    *   生图结束后立刻发送对话（触发 LLM 恢复或自动回迁）；
    *   观察后台仅出现“回迁失败”而看不到具体原因，且 LLM 长时间停留在 CPU。
*   **预期行为**:
    *   回迁失败要输出可行动的原因信息；
    *   在短时回收抖动场景下自动重试恢复，避免用户手工触发。
*   **实际行为**:
    *   回迁失败被吞掉细节，仅输出一句 WARNING；
    *   第一次恢复失败后不再重试，LLM 长时间停留在 CPU。
*   **解决方案 (已实施)**:
    *   `ResourceManager` 回迁调用补齐失败细节：区分超时/异常，并输出后端类型与最后一次加载错误；
    *   `ImageManager._end_image_gen` 在首次恢复失败时按 1.5s/3s/6s 自动重试，并在每次重试前触发一次 `optimize_resources()`；
    *   `ResourceManager._auto_recover_gpu_models` 改为后台任务调度回迁，避免回迁过程阻塞 1s 监控循环。
*   **相关文件**:
    *   `core/resource_manager.py`
    *   `core/image/image_manager.py`
    *   `core/services/scheduler/cpp_scheduler_engine.py`

### 10.14.2 生图结束后 LLM 恢复到 GPU 仍偶发 OOM：恢复时序 + 清理钩子 (2026-01-07)

*   **问题描述**: 生图完成后立即触发 `restore_llm_to_gpu()`，在部分环境（Forge 仍持有模型/显存未完全回收、或 keepalive 配置非 0）会出现 LLM 恢复阶段的显存不足（CUDA OOM / llama.cpp 分配失败），导致后续对话失败。
*   **复现步骤**:
    *   触发一次 Forge 生图并等待生成完成；
    *   在 Forge 端或配置中开启“模型驻留”/延迟卸载（或卸载回收变慢）；
    *   观察生图结束后 LLM 恢复 GPU 期间报错或卡住。
*   **预期行为**:
    *   生图结束后先确保 Forge 卸载/回收完成，再恢复 LLM 到 GPU；
    *   生图收尾阶段应触发一次资源清理，降低碎片与二次失败概率。
*   **实际行为**:
    *   恢复 GPU 与 Forge 卸载并行时会放大显存竞争，导致恢复失败。
*   **解决方案 (已实施)**:
    *   `ImageManager._end_image_gen` 调整为“先等待 Forge 卸载任务完成（如存在）→ 再调用 `ResourceManager.optimize_resources()` → 最后执行 `restore_llm_to_gpu()`”；
    *   `CPPSchedulerEngine.release_llm_vram_for_image_gen` 在释放显存后增加“短等待 + 不取消的后台加载”策略，提升生图期间 CPU 续聊的稳定性，并同步 `llm_engine` 的资源矩阵状态。
*   **相关文件**:
    *   `core/image/image_manager.py`
    *   `core/services/scheduler/cpp_scheduler_engine.py`

### 10.14.1 WebSocket 生图无回复与二次 OOM：排队闸门 + LLM 可卸载注册 (2026-01-07)

*   **问题描述**: 生图任务进行中，用户继续聊天时表现为“长时间无回复/消息卡住”；并且连续触发第二次生图时更容易出现 OOM 或 CUDA 相关错误。
*   **复现步骤**:
    *   通过 WebSocket 触发一次生图（或在聊天中触发 `image_trigger`）；
    *   生图尚未结束时继续发送聊天消息，观察到回复明显延迟或卡住；
    *   在显存紧张机器上（8GB 更易复现）紧接着触发第二次生图，出现 OOM/CUDA 错误概率升高。
*   **预期行为**:
    *   生图在后台执行时，聊天仍能正常排队并及时回复；
    *   生图任务在 GPU 繁忙时应有明确排队提示；
    *   OOM/CUDA 失败后应触发清理与资源回收，降低二次失败概率。
*   **实际行为**:
    *   生图与聊天同时争抢 GPU/显存，导致模型互斥策略未能生效时出现长时间等待；
    *   多个生图任务并发时显存更容易被击穿，导致后续请求频繁失败。
*   **原因分析**:
    *   `ResourceManager.prepare_for_heavy_task("image_gen")` 只有在目标模型已注册且具备 `unload_func` 时才能真正卸载冲突模型；
    *   本地 LLM 的加载/卸载状态未与 `ResourceManager` 的 `llm_engine` 资源绑定，导致生图阶段无法可靠触发 LLM 卸载；
    *   WebSocket 侧缺少“单通道生图闸门”，并发生图会放大显存竞争与消息发送拥塞。
*   **解决方案**:
    *   在本地 LLM 加载/卸载时同步 `mark_model_loaded("llm_engine", True/False)`，让资源矩阵与互斥卸载逻辑具备真实依据；
    *   在 `get_llm_module()` 初始化阶段为 `llm_engine` 补齐 `ResourceManager.register_model(...)`（仅在非 C++ LLM 调度路径下启用），确保 `prepare_for_heavy_task` 能卸载本地 LLM；
    *   在 FastAPI WebSocket 侧为生图引入互斥闸门（Semaphore=1）与排队提示（position），避免多任务并发击穿显存；
    *   识别 OOM/CUDA 类失败后触发 `ResourceManager.optimize_resources()`，作为失败自愈的兜底清理。
*   **相关文件**:
    *   `core/interfaces/websocket/fastapi_websocket_adapter.py`
    *   `core/modules/llm/module.py`
    *   `core/llm/__init__.py`

### 10.59 MVP Core 清理重复实验脚本与依赖收敛（2025-12-20）

*   **问题描述**:
    *   `legacy/mvp_core/experiments` 下存在重复/过时脚本，容易造成“入口不唯一”、结果文件命名混乱与维护成本上升。
    *   `legacy/mvp_core/requirements.txt` 中存在未使用依赖，同时缺少部分实际使用依赖，导致新环境安装不稳定。
*   **解决方案**:
    *   删除重复/过时脚本：`update_charts.py`、`run_full_benchmark.py`、`verify_all_models.py`。
    *   统一入口与职责边界：以 `comprehensive_experiment.py` 为实验主入口，以 `run_final_experiments.py` 为批量运行封装，以 `generate_real_charts.py` 为图表生成入口。
    *   更新 `requirements.txt`：移除未使用依赖并补齐实际使用依赖（如 `numpy`、`pillow`），并收紧关键依赖最低版本（如 `fastapi`、`uvicorn`、`pydantic`）。
*   **验证**:
    *   仓库内检索上述脚本文件名无引用；`legacy/mvp_core/experiments/README.md` 已以 `comprehensive_experiment.py` 作为主入口说明。

### 10.51 MVP Core：真实负载主线程卡顿指标误判与修复记录（2025-12-19）

*   **问题描述**:
    *   在真实模型压测中，原本预期“串行基准”会因为同步重计算导致事件循环被长时间阻塞（卡顿秒级），但实验记录的主线程最大卡顿仍处于毫秒级，容易被误判为监控失效。
*   **复现步骤**:
    *   运行 `legacy/mvp_core/experiments/comprehensive_experiment.py` 的真实负载模式（包含 SD/视觉/LLM/TTS），并观察 `exp2` 的 `max_lag`/`avg_lag` 统计。
*   **预期行为**:
    *   若重计算在主事件循环内同步执行，`max_lag` 应接近单次 SD/视觉/LLM 的执行时长（秒级）。
*   **实际行为**:
    *   `max_lag` 仍为毫秒级（例如 10-30ms），且偶发 `min_ms` 为负值。
*   **原因分析**:
    *   真实适配器（例如 SD）通过 `asyncio.to_thread(...)` 将重计算卸载到线程池执行，即便“串行基准”按顺序 `await`，事件循环仍能被调度与唤醒，因此不会产生秒级卡顿；
    *   `min_ms` 负值来自采样时间与 `asyncio.sleep` 定时误差的组合（不是“倒流时间”，而是“期望唤醒时间”与“实际唤醒时间”的相对误差）。
*   **解决方案**:
    *   在报告与图表中统一将该指标表述为“事件循环卡顿（Event-loop lag）”而非“同步阻塞时间”，并明确其受线程卸载策略影响；
    *   图表与报告的数据源改为直接读取真实实验 JSON 结果，避免硬编码导致的数字漂移（`legacy/mvp_core/experiments/generate_real_charts.py`、`legacy/mvp_core/System_Architecture_and_Performance_Report.tex`）。

### 10.50 MVP Core：断连后图片任务仍执行导致资源浪费（2025-12-19）

*   **问题描述**:
    *   图片生成使用后台队列异步执行；如果客户端断开连接，队列里已入队的图片任务仍会继续执行（生成/落盘），但由于 WebSocket 已关闭，结果无法返回给前端，造成 GPU/CPU 资源浪费。
    *   同一请求在流式链路中可能重复触发相同 `image_trigger`，导致重复入队。
*   **复现步骤**:
    *   触发图片生成后立刻关闭 WebSocket 连接；或在同一连接中重复触发相同 prompt 的 `image_trigger`；
    *   观察后端仍持续执行图片任务或重复排队。
*   **预期行为**:
    *   断连后应尽可能丢弃该连接相关的队列任务；同连接同请求同 prompt 不应重复入队。
*   **实际行为**:
    *   断连后任务仍执行；重复触发会重复入队。
*   **修复方案**:
    *   为图片任务引入去重键（连接 + request_id + prompt），避免重复入队；
    *   在 `WebSocketDisconnect` 时标记该连接为取消状态，worker 出队后跳过执行并释放槽位（`legacy/mvp_core/presentation/websocket/handler.py`）。

### 10.49 MVP Core：配置导入歧义导致背压参数不生效（2025-12-19）

*   **问题描述**:
    *   `legacy/mvp_core` 作为包被引入运行时，`from config import get_settings` 可能误引用仓库根目录的 `config` 包，而不是 `mvp_core/config.py`，导致 `scheduler.image_queue_capacity` / `scheduler.image_max_concurrent_tasks` 等新参数读取不到，背压行为与预期不一致。
    *   同时，图片生成在 DI 容器解析 `ImageGenInterface` 失败时，会发送 `image_error` 但缺少 `image_status=finished`，前端可能卡在“生成中”。
*   **复现步骤**:
    *   以包方式运行/导入 `mvp_core`（而非在 `legacy/mvp_core` 目录下直接执行），并在 `mvp_core/config.json` 设置 `image_queue_capacity` / `image_max_concurrent_tasks`；
    *   触发 `image_trigger`，观察背压阈值未按配置生效；或在 DI 未注册 `ImageGenInterface` 时触发图片生成，观察前端状态不结束。
*   **预期行为**:
    *   背压参数应始终来自 `mvp_core.config.get_settings()`；图片生成无论成功/失败均应以 `image_status=finished` 收尾。
*   **实际行为**:
    *   存在导入歧义时读取到错误的配置源；DI 失败路径缺少结束状态。
*   **修复方案**:
    *   统一 `legacy/mvp_core` 内部 `get_settings` 导入为“优先 `mvp_core.config`，失败再回退到 `config`”（`legacy/mvp_core/presentation/websocket/handler.py`、`legacy/mvp_core/main.py`、`legacy/mvp_core/data/adapters/local_llm_adapter.py`）；
    *   DI 失败时补齐 `image_status=finished`（`legacy/mvp_core/presentation/websocket/handler.py`）。

### 10.48 MVP Core：WebSocket 图片任务背压（并发与在途上限）（2025-12-19）

*   **问题描述**:
    *   图片触发频繁时，后端会为每个 `image_trigger` 立即创建后台任务，缺少“并发/队列/在途”上限，可能导致任务无限堆积。
*   **预期行为**:
    *   图像生成应有明确的并发与总在途容量；当系统繁忙时应快速拒绝并返回可重试错误，而不是无限堆积导致雪崩。
*   **解决方案**:
    *   为图片生成引入固定容量的“在途槽位”（`max_concurrent + queue_capacity`），在槽位耗尽时直接返回 `image_error`（`retryable=true`），并发送 `image_status=finished` 结束状态；
    *   对成功入队的任务先发送 `image_status=queued`，由后台 worker 取出后再发送 `image_status=started`/`image_result`/`image_status=finished`。
*   **落点文件**:
    *   `legacy/mvp_core/presentation/websocket/handler.py`
    *   `legacy/mvp_core/config.py`

### 10.47 MVP Core：WebSocket 错误模型统一与图片状态机补齐（2025-12-19）

*   **目标**:
    *   对同一类失败在不同路径下保持一致的可机读错误结构，便于前端状态机与实验统计。
*   **实现要点**:
    *   WebSocket 统一错误字段：`error_type`（`timeout`/`cancelled`/`backend_unavailable`/`runtime_error`）与 `retryable`；
    *   图片生成补齐 `image_status`（`started`/`finished`），避免前端无法区分“未触发/生成中/已结束”。
*   **落点文件**:
    *   `legacy/mvp_core/presentation/websocket/handler.py`

### 10.43 边画图边聊天：图片生成异步触发与实时反馈（2025-12-18）

*   **目标**:
    *   对话流式输出不中断：图片生成不应阻塞 token 流。
    *   前端自动触发图片生成：识别到 `[GEN_IMG: ...]` 相关信号即可开始生成并展示结果。
    *   保持兼容：继续支持既有 `[GEN_IMG: ...]` 标签解析与图片 Provider 抽象（Forge/SiliconFlow）。
*   **实现要点**:
    *   **流式侧触发信号**: 在流式输出过程中检测到 `[GEN_IMG: ...]`，立即产出 `image_trigger` chunk，作为“开始生成图片”的事件信号（`core/agents/chat_agent_components/streaming.py`）。
    *   **WebSocket 透传 + 后台生成**: WebSocket 适配层透传 `image_trigger`，并用后台任务调用 `ImageManager.generate_image(...)`，随后推送 `image_status`/`image_result` 回前端（`core/interfaces/websocket/fastapi_websocket_adapter.py`）。
    *   **前端自动展示**: 前端收到 `image_trigger`/`image_status`/`image_result` 后更新消息状态与图片字段，并在气泡中展示结果（`clients/frontend/Aveline_UI/src/Aveline.tsx`、`clients/frontend/Aveline_UI/src/components/MessageBubble.tsx`、`clients/frontend/Aveline_UI/src/types/index.ts`）。
*   **协议约定（与现有消息体系一致）**:
    *   WebSocket 事件：`{"type":"image_trigger","data":"<prompt>","timestamp":...,"message_id":...}`
    *   图片展示字段：`imageUrl` 或 `imageBase64`（前端消息结构扩展字段，保持可选）。
*   **问题记录：图片生成阻塞对话流式输出**:
    *   **问题描述**: 用户触发画图后，对话 token 流出现停顿，直到图片生成完成才继续输出。
    *   **复现步骤**:
        1. 发送一条包含“画一张/生成图片”的请求；
        2. 模型输出中包含 `[GEN_IMG: ...]`；
        3. 观察前端：对话输出会等待图片生成完成后才继续刷新。
    *   **预期行为**: 对话应持续流式输出；图片生成应并行进行，生成状态/结果通过事件回传。
    *   **实际行为**: 图片生成链路同步等待导致对话流被阻塞。
    *   **修复方案**: 将“开始生成图片”的动作从对话流式路径中剥离为事件信号（`image_trigger`），由前端或后台任务异步触发生成，不阻塞对话输出。
*   **问题记录：前端未处理图片事件导致看不到生成状态/结果**:
    *   **问题描述**: 后端已推送图片相关事件，但前端缺少 `image_trigger/image_status/image_result` 分支，导致用户看不到“生成中/已生成”的 UI 更新。
    *   **复现步骤**:
        1. 通过 WebSocket 观察后端已发送 `type=image_trigger` 与后续 `image_result`；
        2. 前端消息分发中缺少对应分支；
        3. UI 不显示生成中/图片结果。
    *   **预期行为**: 前端收到 `image_trigger` 后自动调用生成接口，并展示“生成中/已生成”结果。
    *   **实际行为**: 事件被忽略，UI 不更新。
*   **修复方案**: 在前端 WebSocket 消息分发中补齐 `image_trigger/image_status/image_result` 分支，将状态与结果写回消息并渲染。

### 10.10 视觉模型 (Vision Module) 修复与优化 (2025-12-15)

*   **问题描述**: 本地 Vision API 响应为空或返回幻觉内容，`test_vision_local.py` 测试显示模型输出了 input tokens 或无意义文本。
*   **原因分析**:
    *   **Prompt 格式错误**: Qwen2-VL 模型对 Prompt 格式有严格要求，缺少 Instruct 模式的 `<|im_start|>` 等特殊标记。
    *   **输出处理不当**: `module.py` 中的 `generate` 输出包含了 Input Tokens，且未正确处理 Stop Tokens，导致返回重复 Prompt 或后续生成的 System/User 对话幻觉。
*   **解决方案**:
    *   **Prompt 修正**: 实现了符合 Qwen2-VL Instruct 规范的 Prompt 模板 (`<|im_start|>system...`).
    *   **输出切片**: 在 `module.py` 中增加了对 `output` 的切片逻辑，移除 Input Tokens。
    *   **后处理优化**: 增加了对 `<|im_end|>` 等 Stop Tokens 的截断处理。
*   **验证结果**: `test_vision_local.py` 测试通过，能正确识别图像内容（如红色圆形、蓝色正方形）并生成准确描述。

### QR-2026-08-01-01 QQ 端视觉识别返回空 + Aveline 误用 deepseek-v4-pro (2026-08-01)
*   **问题描述**: QQ 端调用 /api/v1/vision/describe 返回 description_len=0、耗时 41 秒；同时 Aveline 主对话日志显示 model_path=cloud:deepseek:deepseek-v4-pro，但期望走 flash 并使用 aveline 专用 API key。
*   **复现步骤**:
    1. QQ 端发送一张图片
    2. 后端日志显示 Vision describe result: status=success, description_len=0, response_len=0
    3. 慢请求警告: /api/v1/vision/describe 耗时 41.16秒
    4. QQ 端发送文本消息
    5. 日志显示 HybridLLMModule.stream_chat: model_path=cloud:deepseek:deepseek-v4-pro
    6. PromptData 日志又显示 Model=cloud:deepseek:deepseek-v4-flash，两条日志不一致
*   **预期行为**:
    1. 视觉识别返回非空 description
    2. Aveline 主对话 model_path=cloud:deepseek:aveline:deepseek-v4-flash
    3. Ling 主对话 model_path=cloud:deepseek:ling:deepseek-v4-flash
    4. 分别使用 DEEPSEEK_API_KEY_Aveline 和 DEEPSEEK_API_KEY_Ling
*   **实际行为**:
    1. 视觉识别 description_len=0，耗时 41 秒
    2. Aveline 主对话 model_path=cloud:deepseek:deepseek-v4-pro（3段、默认key、pro）
    3. PromptData 的 flash 日志是主动消息/问候流程，与主对话非同一条调用
*   **根因**:
    1. config/yaml/sections/modeling.yaml 硬编码 zhipu/glm-4.6v，该模型对此图返回空
    2. clients/bots/dual_qq_config.json 第13行 aveline.default_model_name 硬写 deepseek-v4-pro
    3. QQ adapter 双QQ模式优先用 adapter 自身配置，不会从后端同步覆盖
    4. make_cloud_model_hint 之前没传 key_alias，只能拼出 3段路径走默认 key
*   **修复方案**:
    1. vision 配置改为 siliconflow/Qwen3-VL-32B-Instruct
    2. dual_qq_config.json 两个角色 default_model_name 改为 4段完整 cloud 路径（带 aveline/ling key alias）
    3. 复用 handlers/config.py:41-42 既有 cloud: 前缀直返逻辑，无需改代码
*   **验证**:
    1. `重启后视觉识别返回非空 description`
    2. `重启后 Aveline/Ling 主对话日志 model_path 为 4段 flash 路径`

### FOCUS-345 专注番茄钟低频视觉复核的隐私护栏与触发控制 (2026-08-18)
*   **问题描述**: 严格模式想对持续分心做更强复核，但视觉模型调用昂贵（约41s），且任何图像都不应进入会话存储或 AI 工具返回。
*   **复现步骤**:
    1. strict 模式开启摄像头监控并长时间未分心
    2. 用户分心超过 strict_distraction_sec，且距上次复核超过冷却间隔
    3. 前端调起 vision-review 端点上传帧
*   **预期行为**:
    1. 仅在满足全部条件时才触发复核
    2. 帧 base64 只在请求内临时送模型，绝不落盘
    3. 会话与工具返回体不含任何图像字段
*   **实际行为**:
    1. 策略输出 vision_review 建议，request_vision_review 仅记录结构化结论文本
    2. 冷却期 / 无监控 / 非 strict 均被拦截
    3. verify_focus_phases_345.py 断言序列化与工具返回均不含 image/base64/frame 字段，通过
*   **验证**:
    1. `v`
    2. `e`
    3. `r`
    4. `i`
    5. `f`
    6. `y`
    7. `_`
    8. `f`
    9. `o`
    10. `c`
    11. `u`
    12. `s`
    13. `_`
    14. `p`
    15. `h`
    16. `a`
    17. `s`
    18. `e`
    19. `s`
    20. `_`
    21. `3`
    22. `4`
    23. `5`
    24. `.`
    25. `p`
    26. `y`
    27. `：`
    28. `满`
    29. `足`
    30. `全`
    31. `部`
    32. `条`
    33. `件`
    34. `才`
    35. `建`
    36. `议`
    37. `复`
    38. `核`
    39. `、`
    40. `冷`
    41. `却`
    42. `期`
    43. `内`
    44. `拦`
    45. `截`
    46. `、`
    47. `无`
    48. `监`
    49. `控`
    50. `不`
    51. `触`
    52. `发`
    53. `、`
    54. `会`
    55. `话`
    56. `序`
    57. `列`
    58. `化`
    59. `与`
    60. `工`
    61. `具`
    62. `返`
    63. `回`
    64. `均`
    65. `不`
    66. `含`
    67. `i`
    68. `m`
    69. `a`
    70. `g`
    71. `e`
    72. `/`
    73. `b`
    74. `a`
    75. `s`
    76. `e`
    77. `6`
    78. `4`
    79. `/`
    80. `f`
    81. `r`
    82. `a`
    83. `m`
    84. `e`
    85. `等`
    86. `字`
    87. `段`
    88. `。`
