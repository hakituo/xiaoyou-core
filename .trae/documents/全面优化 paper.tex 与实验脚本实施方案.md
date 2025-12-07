## 项目结构审查

* 全量遍历并梳理仓库模块、语言栈与入口：Python后端、TS前端、C++调度、Android壳、QQ机器人与脚本。

* 输出系统架构图（Mermaid）与模块关系图；标注交互边界与数据流。

* 建立入口与关键路径清单：`main.py:52` 生命周期、`routers/api_router.py:289-475` 消息管线、`core/services/aveline_service.py:328-416` 推理调用、`core/model_adapter.py` 统一适配、`core/websocket_manager.py:20-22` Windows事件循环策略。

## 代码功能分析

* 核查异步隔离：协程I/O、CPU任务线程池、GPU任务序列化锁；列出实现与缺口。

* 明确当前CPU隔离使用线程池而非进程池：`core/task_scheduler.py:70,126-146`；提出替换为`ProcessPoolExecutor`的方案与影响面。

* 评估核心模块质量：缓存(`core/async_cache.py:45-56,80-92`)、性能监控(`core/async_monitor.py:71-88,117-179`)、WebSocket适配(`core/fastapi_websocket_adapter.py:106-120,183-200`)；给出优化点（并发、背压、超时与重试、观测性）。

* 识别性能瓶颈：LLM/TTS耗时、CPU线程池下GIL限制、GPU串行区段；提出分层优化策略（模型量化、批处理、流式TTS、异步任务重排）。

## 论文文档专项审查

* 通读并标注`paper/System_Architecture_and_Performance_Report.md`需更新段落：

  * 「2.2 进程级CPU隔离」现文宣称`ProcessPoolExecutor`，代码为线程池，需改写或落地进程池实现；引用位置：`paper/System_Architecture_and_Performance_Report.md:27-31` 与代码`core/task_scheduler.py:70,126-146`。

  * 实验章节需补充数据来源与文件路径：所有图表与数值增加“来源：paper/experiment/experiment\_results/data/\*.json”。

  * 并发20的成功率与延迟占比：与`performance_test`结果一致性校验后修订；当前README存在占位`N/A`。

* 输出修订清单与重写提纲：执行摘要、架构分层、实验方法与结果、结论与展望，统一术语与口径。

## 实验数据验证

* 运行实验脚本生成真实数据（确认后执行）：

  * 并发与延迟：`paper/experiment/scripts/performance_test.py`（并发1/5/10/20；结果写入`experiment_results/data/performance_test_*.json`）。

  * 异步压力与GPU负载：`async_stress_test.py`,`gpu_load_latency_test.py`（生成`stress_test_*.json`,`GPU满载状态延迟测试_*.json`）。

  * 异构编程：`heterogeneous_programming_test.py`（生成`异构编程集成测试_*.json`）。

* 生成图表：执行`paper/experiment/scripts/generate_charts.py`，输出到`experiment_results/charts`；来源标签与文件名纳入报告引用。

* 交叉验证系统架构匹配度：用`tests/integration/test_api_endpoints.py`对HTTP/TTS端到端校验（服务器启动后执行）。

## 报告编写与交付

* 系统功能部分：逐模块功能与协同机制，配图标注调用方向与边界（HTTP/WS、任务调度、模型适配、缓存/监控）。

* 架构优势分析：结合实验数据量化吞吐、延迟与资源占用；与传统同步架构对比（成功率、TTFB、内存峰值）。

* 实验数据引用：挑选并嵌入关键图表（并发QPS、Avg Latency、GPU负载曲线、IPC扩展曲线），在图下注明来源JSON路径与生成日期。

* 交付物：

  * 完整系统架构图与模块关系图（Mermaid与导出PNG/SVG）。

  * 更新后的`System_Architecture_and_Performance_Report.md`（统一术语、补足来源、修正隔离层描述）。

  * `experiment_results/data/*.json`与`experiment_results/charts/*.png`图表集。

## 后续优化建议

* 将CPU密集任务迁移到`ProcessPoolExecutor`或C++后端，通过RPC/IPC减少GIL影响。

* 为TTS实现真正的流式输出与分段并行；增加缓存命中策略（语义相似度）。

* 在`task_scheduler`增加队列背压、指标暴露与熔断降级；为WebSocket添加广播限速与重试抖动。

