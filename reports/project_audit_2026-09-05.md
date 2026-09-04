# xiaoyou-core 项目审查报告 — 2026-09-05

## Executive Summary

审查基线：`main@670809cefcc26817bd425aa82c0b703b14c0f5e5`。本次通过 GitHub 远端源码进行静态审查，重点覆盖应用入口、安全中间件、配置边界、测试结构及仓库级工程配置。由于执行环境只有 GitHub 内容/写入接口，没有项目运行时、CUDA/GPU、本地模型、C++ 编译器或 shell，因此不能诚实声称已经执行 pytest、mypy、ruff、前端构建、C++ 构建或 GPU/模型集成测试；这些项目均列为 BLOCKED，而不是伪造测试结果。

本轮确认 1 个 P0、3 个 P1、3 个 P2。最严重问题是受保护 HTTP API 的 localhost 免认证判断信任了 `X-Forwarded-For` / `X-Real-IP`：远程客户端可以伪造转发头，将自身识别为 `127.0.0.1`，绕过 token 校验。该问题已修复并补回归测试。

## 审查范围

已实际检查：
- 仓库默认分支、HEAD、目录树、主要工程配置；
- `main.py` 的 FastAPI/CORS/中间件装配；
- `core/middleware/security.py` 的认证、Origin、限流和安全响应头；
- `config/integrated_config.py`、`config/settings_server.py` 的服务/安全配置；
- `pyproject.toml` 的依赖、pytest/ruff/mypy 配置；
- `tests/_audit_report.txt` 的测试目录健康扫描结果；
- `core/`、`clients/`、`cpp_modules/`、`memory/`、`multimodal/`、`routers/`、`tests/` 等主要模块的仓库结构。

无法在当前云端 GitHub 接口执行：pytest、ruff、mypy、npm/Gradle、CMake/CTest、CUDA/VRAM、模型 Hot-Swap、MPS、TTS/STT、真实 WebSocket/SSE 压测。因此涉及这些运行时性质的结论不能升级为已验证缺陷。

## Findings

### P0-001 — 可伪造 Forwarded Header 绕过受保护 API 认证

**位置：** `core/middleware/security.py`，`get_client_ip()` / `security_middleware()`。

**证据：** 原实现的 `get_client_ip()` 优先读取 `X-Forwarded-For` 和 `X-Real-IP`；`security_middleware()` 随后用该返回值判断是否为 `127.0.0.1` / `::1` / `localhost`，命中即跳过 token 校验。

**现象：** 外部请求可发送 `X-Forwarded-For: 127.0.0.1`，使认证层把用户可控 header 当成信任边界。

**影响：** 在应用可被远程访问且请求直接到达应用时，攻击者可绕过 `/api/*`、`/v1/*`、`/demo*`、`/health*` 的 Web token 校验。

**触发条件：** 远程访问受保护路径，且请求可以自行控制转发头。

**根因：** 将“用于日志/代理转发的客户端 IP”与“用于认证的 TCP peer 身份”混为一体。

**修复：** 新增 `get_peer_ip()` / `is_loopback_peer()`，认证免 token 仅根据 `request.client.host` 的实际 socket peer 判断；Forwarded Header 只保留给日志/限流。

**验证：** 新增 `tests/unit/test_security_middleware_trust_boundary.py`，覆盖远程 peer + `X-Forwarded-For: 127.0.0.1` 必须返回 401，以及真实 IPv4/IPv6 loopback 被识别。

**状态：FIXED（代码级）；运行测试待 CI/本地执行。**

### P1-001 — 反向代理后的“本地 peer 免认证”仍需要显式信任模型

**位置：** `core/middleware/security.py`。

**证据：** 即使不再信任 XFF，如果生产部署是 `Internet -> 本机 nginx/cloudflared -> 127.0.0.1:app`，应用看到的真实 TCP peer 仍可能是 loopback。

**影响：** 如果反向代理没有在自身层面强制认证，所有经本机代理转发的外部请求都可能享受本地免 token。

**根因：** “本机进程”和“经本机代理转发的外部用户”在 socket peer 层不可区分。

**建议：** 后续增加显式 `allow_loopback_auth_bypass` 配置（生产默认 false），或让内部 QQ/桌面适配器始终使用独立 internal token；反代部署关闭 loopback bypass。

**状态：DEFERRED。** 原有内部适配器依赖免 token，直接关闭可能破坏兼容性，需要在真实部署配置上迁移。

### P1-002 — mypy 全局 `ignore_errors = true` 使类型检查失去门禁能力

**位置：** `pyproject.toml` `[tool.mypy]`。

**证据：** 配置启用了 `check_untyped_defs` 等规则，但同时设置 `ignore_errors = true`。

**影响：** CI/本地即使运行 mypy，也无法把新增类型错误作为失败信号；对于大量异步、状态机、模型生命周期代码，这会显著削弱回归防线。

**建议：** 分阶段收紧：先对 `core/api`、`core/middleware`、`core/contracts`、关键 scheduler 接口启用严格子模块 override，再逐步扩大，不建议一次性全仓开启造成数千历史错误。

**状态：DEFERRED。** 需要实际运行 mypy 建立错误基线后渐进修复。

### P1-003 — 测试目录存在大量“test_*.py 但无 assert”文件

**位置：** `tests/_audit_report.txt` 报告的 63 个测试文件；另有 2 个超大测试文件。

**证据：** 仓库自带健康审计报告列出 65 个潜在问题，其中大量 `test_*.py` 无 assert，包含 active care、scheduler、memory、WebSocket、TTS、视觉等关键路径。

**影响：** 文件名会给人“已有测试覆盖”的错觉，但其中一部分可能只是调试/打印脚本；pytest 通过不等于行为被验证。

**建议：** 区分真正 smoke test（显式断言退出/结果）与手工 diagnostics；后者移动到 `tests/diagnostics` 或 `scripts/` 并避免 pytest 收集，前者补明确断言。

**状态：DEFERRED。** 不能仅凭“无 assert”机械改写，必须逐文件理解预期行为。

### P2-001 — 安全中间件职责过多

**位置：** `core/middleware/security.py`。

**现象：** 单文件同时承担 token 提取、访问控制、客户端 IP、全局/IP 限流、Origin、响应安全头和请求日志。

**影响：** 安全边界修改容易产生交叉回归；本次 P0 正是 IP 观测逻辑和认证逻辑耦合的例子。

**建议：** 后续拆分 `auth.py`、`client_identity.py`、`rate_limit.py`、`headers.py`，保留一个薄的装配层。

**状态：PARTIALLY_FIXED。** 本轮先把“peer identity”和“forwarded client IP”概念拆开，避免为清理而大改。

### P2-002 — 测试与 lint 配置大范围排除 tests/clients

**位置：** `pyproject.toml` flake8/ruff 配置。

**影响：** 测试代码和客户端代码可以积累语法之外的质量问题；测试本身是回归基础，不应永久处于 lint 盲区。

**建议：** 建立较宽松的 tests/clients 专属规则，而不是完全 exclude；先跑基线再逐步收紧。

**状态：DEFERRED。** 需要真实 lint 基线。

### P2-003 — 运行时/GPU/多端验证依赖本地环境，云端 GitHub 审查无法覆盖

**范围：** C++ scheduler、CUDA/VRAM、Hot-Swap、CPU offload、TTS/STT、Android/Gradle、前端构建、真实 SSE/WebSocket。

**影响：** 静态审查不能证明这些路径稳定。

**建议：** 把 CPU-only unit tests 和静态检查放 GitHub Actions；GPU/模型测试保留本地 nightly/手工验收，并上传报告。

**状态：BLOCKED（环境限制）。**

## Execution Plan

| ID | Priority | 修改目标 | 风险 | 验证 |
|---|---|---|---|---|
| P0-001 | P0 | 认证只信任实际 socket peer | 低-中：内部代理部署需注意 | 新增 spoof/loopback 回归测试 |
| P1-001 | P1 | 显式控制 loopback bypass | 中：可能影响 QQ/桌面内部调用 | 本地适配器 + 反代集成测试 |
| P1-002 | P1 | 恢复 mypy 门禁 | 中：历史错误量未知 | mypy baseline + 分模块 CI |
| P1-003 | P1 | 整理伪测试/诊断脚本 | 中：需逐文件判定 | pytest collection + 行为断言 |
| P2-001 | P2 | 拆分安全中间件职责 | 中 | security unit/integration tests |
| P2-002 | P2 | 扩大 lint 覆盖 | 低 | ruff/flake8 baseline |
| P2-003 | P2 | 建立运行时/GPU验证矩阵 | 低 | CI + 本地 GPU 报告 |

## 建议修复顺序

1. P0-001（本轮已执行）。
2. 在真实部署机确认是否存在 cloudflared/nginx loopback 反代，再执行 P1-001。
3. 建立 CI 可执行基线后处理 P1-002 / P1-003。
4. 有安全回归测试保护后再继续 P2-001 的结构拆分。
5. 最后扩大 lint 与 GPU/多端验证矩阵。
