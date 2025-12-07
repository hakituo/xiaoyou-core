# 重构交付记录

- 架构文档：`ARCHITECTURE.md` 更新为重构基线版并含架构图。
- 应用装配：`app/bootstrap.py` 新增统一装配入口。
- 模型清单：`models/manifest.json` 与 `core/model_manifest.py`。
- 适配接口：`core/model/adapter_protocol.py` 与 `ModelAdapter.info/metrics`。
- 依赖分组：`requirements/core.txt`、`requirements/voice.txt`、`requirements/models-*.txt`、`requirements/dev.txt`；根 `requirements.txt` 聚合。
- 前端客户端：`frontend/packages/api-client/src/index.ts` 并在 `Aveline_UI` 暴露 `ApiClient`。
- 测试：`tests/unit/test_model_manifest.py`、`tests/unit/test_contract.py`、`tests/unit/test_perf_middleware.py`。
- 文档：`docs/REQUIREMENTS_GUIDE.md` 与 `docs/MIGRATION_GUIDE.md`。
