# 其他

本分类共 1 条记录。按时间倒序（最新在前）排列。

---

### 10.9 故障排查与修复日志 (2025-12-15)

*   **TTS 语音合成问题**:
    *   **问题描述**: 前端显示 `[System: TTS Generation Failed - No Audio Data]`，后端日志显示生成了音频但返回长度为 0。
    *   **原因分析**: `api_router.py` 使用错误的 `mgr.clone` 方法（应为 `mgr.synthesize`）；后端音频解码兼容性问题。
    *   **解决方案**: 修改 `api_router.py` 为调用 `mgr.synthesize`；在 `tts_engine.py` 增加 `soundfile` 解码健壮性处理及采样率自动获取逻辑。
*   **桌面宠交互问题**:
    *   **问题描述**: 桌宠模式最小化后无法在任务栏找到，且无法通过托盘控制。
    *   **原因分析**: `electron/main.js` 中 `createPetWindow` 配置了 `skipTaskbar: true`。
    *   **解决方案**: 将 `skipTaskbar` 改为 `false`，确保桌宠窗口最小化后仍驻留在任务栏。
*   **前端组件重构**:
    *   **问题描述**: `DesktopPet.tsx` 代码过于庞大，难以维护。
    *   **解决方案**: 解耦为 `src/components/pet/` 下的 9 个独立文件（组件+Hooks）。
*   **界面显示修复**:
    *   **仿生学状态**: 修复 `PetStatsPanel.tsx` 语法错误及数据映射，正确显示神经递质状态。

### QJ-2026-0805-01 学习生活计划生成空 items 但 source 标记为 ai_generated (2026-08-05)
*   **问题描述**: 今日 plan.json 的 items=[]，source=ai_generated，notes=null。Aveline 告诉用户今天计划表是空的，active care priority 也因此只有画像兜底一条候选，无法基于计划项做推送。
*   **复现步骤**:
    1. 查看 companion_data/user_data/daily/2026/08/05/plan.json，确认 items=[] 且 source=ai_generated
    2. 查看 companion_data/aveline_data/daily/2026/08/05/events/active_care_daily_push_priority_ranked.json，确认只有 portrait:activity 一条 fallback 候选
    3. 追踪 generate_tomorrow_plan 代码路径，发现成功分支 items 为空时仍保存 plan.json，notes 走 LLM 返回值被 None 覆盖
*   **预期行为**:
    1. LLM 返回空 items 时应算失败，不保存 plan.json，下次夜间任务可重试
    2. 失败时 notes 应保留诊断信息，不被 None 吞掉
    3. AI 能主动为今天生成计划，而不只能生成明日计划
*   **实际行为**:
    1. LLM 返回空 items 时仍走成功分支保存 plan.json，下次夜间任务因 existing 跳过
    2. notes 被 None 覆盖，plan.json 里看不到失败原因
    3. 只有 generate_tomorrow_plan 工具，没有 generate_today_plan
*   **根因**:
    1. generate_tomorrow_plan 成功分支没有空 items 检测，直接用 LLM 返回的 notes
    2. 夜间任务 task_runner 在 existing_plan 存在时跳过生成，空 items 计划也被跳过
    3. 缺少 generate_today_plan 工具
*   **修复方案**:
    1. 抽出 _call_llm_and_build_plan，空返回/解析失败/非 dict/空 items 时返回 None
    2. _generate_plan_for_date 首次失败重试 1 次，仍失败返回带诊断 notes 的空计划且不保存
    3. 新增 GenerateTodayPlanTool 工具并注册到 registry
*   **验证**:
    1. `D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -c "from core.tools.plan_tool import GenerateTodayPlanTool; print(GenerateTodayPlanTool.name)"`
