# LLM (大语言模型模块)

本目录提供 LLM 的路由与多 Provider 接入（本地/云端/混合）。

## 模块文件结构

`core/llm/__init__.py` 仅做 re-export，保持对外 API 向后兼容。实际实现按职责拆分：

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `base.py` | ~60 | `LLMConfig` dataclass + `LLMModule` ABC 抽象基类 |
| `local_adapter.py` | ~290 | `LocalLLMAdapter`：封装本地 GGUF 模型，对接 C++ 调度器与资源管理器 |
| `cloud_router.py` | ~230 | `CloudRouterLLMModule`：云端多 provider 路由（含多 API key、延迟创建） |
| `hybrid_module.py` | ~370 | `HybridLLMModule`：本地+云端混合路由 + `fallback_local` 降级 |
| `factory.py` | ~380 | `get_llm_module()` 工厂 + `create_instance/get_instance/list_instances` 实例管理 |
| `__init__.py` | ~35 | 纯 re-export，对外暴露统一 API |

依赖关系：`base` ← `local_adapter` / `cloud_router` / `hybrid_module` ← `factory` ← `__init__`。

其他子模块（独立文件，未参与本次拆分）：
- `siliconflow_client.py` / `dashscope_client.py` / `infer_service_client.py`：具体 provider 客户端
- `openai_compat/`：OpenAI 兼容协议客户端集合（DeepSeek / Aveline / Ark / MiniMax / ZhiPu / OpenAI）
- `llm_logger.py`：LLM 调用日志统计

## 统一状态输出（避免漂移）

LLM 各实现的 `get_status()` 会保留历史字段（如 `status` / `type`），同时补充统一契约字段：

- `init_state`: 来自 `core/contracts/states.py::ModuleInitState`
  - `not_initialized` / `initialized` / `error` / ...
- `module_type`: 来自 `core/contracts/states.py::LLMModuleType`
  - `local` / `cloud_router` / `hybrid`

示例（Hybrid）：

```json
{
  "type": "hybrid",
  "module_type": "hybrid",
  "init_state": "initialized",
  "default_provider": "local",
  "local": { "module_type": "local", "init_state": "initialized" },
  "cloud": { "module_type": "cloud_router", "init_state": "initialized" }
}
```

> 注意：模块初始化态（`ModuleInitState`）与模型运行态（`ModelRuntimeState`）是不同概念。

