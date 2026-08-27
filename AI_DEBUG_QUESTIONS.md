# AI 自愈系统调试记录

本文件由 Auto Heal 自愈系统自动生成，记录 AI 在运行时发现的 bug 及其修复过程。

格式遵循 Question Reviewer 规范：
- 问题描述
- 复现步骤
- 预期行为
- 实际行为
- 根因分析
- 修复方案

---

## [2026-06-10] 已修复 - core/voice/engines/qwen3_tts_engine.py

**修复时间**: 2026-06-10 17:22

**问题描述**: `core/voice/engines/qwen3_tts_engine.py` Qwen3-TTS 引擎初始化失败，报错 `KeyError: 'default'`

**复现步骤**: 自愈服务通过日志异常检测自动发现
- 异常类型: KeyError
- 异常描述: `Qwen3TTSTalkerRotaryEmbedding.__init__` 中 `ROPE_INIT_FUNCTIONS[self.rope_type]` 抛出 `KeyError: 'default'`

**预期行为**: Qwen3-TTS 模型正常加载

**实际行为**: 补丁已手动应用

**根因分析**:
`qwen_tts` v0.1.1 与 `transformers` v5.9.0 不兼容。模型 config.json 中 `rope_scaling.type="default"`，qwen_tts 代码用 `ROPE_INIT_FUNCTIONS["default"]` 查找初始化函数，但 transformers v5.x 已移除 `"default"` 这个 key（只保留 `linear`, `dynamic`, `yarn`, `longrope`, `llama3`, `proportional`）。这导致每次加载模型都失败。用户反复重装 qwen_tts 时可能暂时降级了 transformers，但其他依赖升级后又复现。

**修复方案**:
在 `qwen3_tts_engine.py` 中新增 `_patch_rope_init_functions()` 函数，在加载模型前向 `ROPE_INIT_FUNCTIONS` 注册 `"default"` 类型（原始 RoPE，无缩放），兼容 qwen_tts 的旧 API 调用方式。在 `initialize`、`move_to_cpu`、`move_to_gpu` 三个加载入口都调用了此修补函数。

**置信度**: 1.00

**状态**: ✅ 已手动修复

---

## [2026-06-10] 已修复 - core/services/auto_heal/report_generator.py

**修复时间**: 2026-06-10 16:30

**问题描述**: `core/services/auto_heal/report_generator.py` 自愈补丁生成后不写入 AI_DEBUG_QUESTIONS.md

**复现步骤**: 自愈服务生成补丁后，AI_DEBUG_QUESTIONS.md 始终为空
- 异常类型: 逻辑缺陷
- 异常描述: `_update_ai_debug_questions` 方法只处理 `PATCH_APPLIED` 和 `SUGGESTION_FOR_PROTECTED` 类型，`PATCH_GENERATED` 被跳过

**预期行为**: 补丁生成后即记录到 AI_DEBUG_QUESTIONS.md，方便用户查看和审批

**实际行为**: 补丁已手动应用

**根因分析**:
`_update_ai_debug_questions` 的类型白名单缺少 `PATCH_GENERATED`。所有补丁在审批前都是 `PATCH_GENERATED` 状态，不写入调试文件意味着用户永远看不到补丁内容，无法审批，形成死循环。

**修复方案**:
1. 在类型白名单中增加 `ReportType.PATCH_GENERATED`
2. 新增 `PATCH_GENERATED` 对应的 section 模板，状态标记为 "⏳ 待审批"

**置信度**: 1.00

**状态**: ✅ 已手动修复

---

