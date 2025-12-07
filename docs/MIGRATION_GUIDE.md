# 迁移指南与回滚策略

- 保持 `main.py` 入口与路由兼容；新增 `app/bootstrap.py` 供统一装配。
- 模型：新增 `models/manifest.json` 与 `core/model_manifest.py`，不影响现有加载流程；目录变化自动刷新清单。
- 接口契约：新增 `core/api/contract.py`；逐步在路由中采用统一成功/错误响应结构。
- 前端：新增 `frontend/packages/api-client` 并在 `Aveline_UI` 暴露 `ApiClient`，现有调用保持不变。
- 依赖：引入分组 requirements；按需安装核心/语音/模型（CPU 或 GPU）与开发依赖。
- 回滚：保留 `backup/` 快照；如需回退，移除新增目录并还原根 `requirements.txt` 与 `ARCHITECTURE.md`。
