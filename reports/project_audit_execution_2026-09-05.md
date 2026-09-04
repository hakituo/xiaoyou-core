# xiaoyou-core 审查修复执行报告 — 2026-09-05

## Summary

基线：`main@670809cefcc26817bd425aa82c0b703b14c0f5e5`

修复分支：`audit/2026-09-05-full-review`

本轮确认问题：P0 1、P1 3、P2 3。

- FIXED: 1
- PARTIALLY_FIXED: 1
- DEFERRED: 4
- BLOCKED: 1

本轮采取保守策略：只自动修改能够从源码直接证明、且修复语义明确的问题；依赖真实部署拓扑、GPU、本地模型、编译器或大量历史类型错误基线的问题不盲改。

## Changes Made

### P0-001

修改 `core/middleware/security.py`：
- 新增 `get_peer_ip()`，只读取 ASGI `request.client.host`；
- 新增 `is_loopback_peer()`，用 `ipaddress.ip_address(...).is_loopback` 判断实际 peer；
- localhost 免 token 不再使用 `X-Forwarded-For` / `X-Real-IP`；
- `get_client_ip()` 明确降级为日志/限流用途；
- 顺手把 Origin 拒绝日志从 f-string 改为参数化日志，避免不必要字符串构造。

新增 `tests/unit/test_security_middleware_trust_boundary.py`：
- 远程 peer 伪造 `X-Forwarded-For: 127.0.0.1` 不得成为 loopback；
- IPv4/IPv6 真 loopback 正确识别；
- 远程伪造 loopback 且无 token 时必须返回 401，不能进入受保护 handler。

## Code Cleanup

本轮没有进行大范围“屎山重构”。原因是安全中间件虽然职责偏多，但直接大拆文件会扩大 P0 修复的回归面。先完成最小结构性清理：把“可信 socket peer”和“可伪造 forwarded client IP”拆成两个明确概念。后续有可执行测试环境后再拆模块。

## Test Results

当前 GitHub connector 提供仓库读取、写入、分支和 PR 能力，但不提供 shell/Actions runner 的即时命令执行。因此本轮没有伪造以下结果：

- `pytest`: BLOCKED（当前工具无 shell runner）
- `ruff`: BLOCKED
- `mypy`: BLOCKED
- 前端 npm build/typecheck: BLOCKED
- Android Gradle: BLOCKED
- C++ CMake/CTest: BLOCKED
- CUDA/VRAM/Hot-Swap/TTS/STT: BLOCKED（缺本地硬件、模型和驱动）

已完成静态验证：新增测试直接构造 Starlette `Request` scope，验证修复的信任边界设计；但最终 PASS/FAIL 必须由 CI 或本地 pytest 给出。

## Remaining Issues

1. **P1-001 DEFERRED** — 本机反向代理可能使外部请求的实际 peer 仍为 loopback。建议迁移内部适配器到显式 internal token，并允许生产关闭 loopback bypass。
2. **P1-002 DEFERRED** — mypy `ignore_errors=true`。需要先运行 baseline，再按模块逐步收紧。
3. **P1-003 DEFERRED** — 仓库审计报告发现大量无 assert 的 `test_*.py`。需逐个判断是 diagnostics 还是有效 smoke test，禁止机械添加无意义 assert。
4. **P2-001 PARTIALLY_FIXED** — security middleware 职责仍偏多；已先拆身份概念，模块级拆分延期。
5. **P2-002 DEFERRED** — tests/clients 被 lint 大范围排除；需基线后收紧。
6. **P2-003 BLOCKED** — GPU/模型/C++/多端运行时问题无法在当前 GitHub-only 环境验证。

## Git Diff Summary

相对基线，本轮预期新增/修改：
- 修改：`core/middleware/security.py`
- 新增：`tests/unit/test_security_middleware_trust_boundary.py`
- 新增：`reports/project_audit_2026-09-05.md`
- 新增：`reports/project_audit_execution_2026-09-05.md`

所有变更均在独立审查分支，未修改 `main`，未 force-push，未改写历史。

## Commits

- `005cb6bf74d75a959754e52e0c628b0ee041058f` — `security: prevent spoofed localhost auth bypass`
- `3e9288062913801dc4408dd58a419548119532e6` — `test: cover spoofed localhost authentication bypass`
- `2c5bb2700b3d8f3ab24f42137efa949109c8c52b` — `docs: add 2026-09-05 project audit and remediation plan`
- 本执行报告自身为后续独立 commit。

## Final P0/P1/P2 Status

| ID | Priority | Status | Description | Validation |
|---|---|---|---|---|
| P0-001 | P0 | FIXED | Forwarded header 可伪造 localhost 免认证 | 已补回归测试；待 CI/local pytest |
| P1-001 | P1 | DEFERRED | loopback reverse proxy 信任模型 | 需真实部署集成测试 |
| P1-002 | P1 | DEFERRED | mypy 无门禁 | 需 mypy baseline |
| P1-003 | P1 | DEFERRED | 大量 test 文件缺明确断言 | 需逐文件语义审查 |
| P2-001 | P2 | PARTIALLY_FIXED | security middleware 职责过多 | peer/client identity 已拆开 |
| P2-002 | P2 | DEFERRED | lint 排除 tests/clients | 需 lint baseline |
| P2-003 | P2 | BLOCKED | GPU/C++/模型/多端运行时验证 | 当前环境不可执行 |

## Merge Recommendation

不要自动合并。先让 CI 或本地至少执行：

`pytest -q tests/unit/test_security_middleware_trust_boundary.py`

若通过，再运行默认 CPU-only pytest 集合与 ruff；确认部署是否经过本机反向代理后，再决定 P1-001 的后续策略。
