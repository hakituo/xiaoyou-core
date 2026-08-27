"""
自我改进系统 — Prompt 组件

为聊天代理提供自我改进相关的 prompt 指令：
- 纠正检测指令（6种信号）
- 学习记录触发指令
- NOT-to-save 列表
- 记忆漂移验证指令
- 核心记忆注入
"""

from __future__ import annotations


from core.utils.logger import get_logger

logger = get_logger("SelfImprovementPrompts")


# ── 纠正检测指令 ──────────────────────────────────────

CORRECTION_DETECTION_INSTRUCTION = """\
【纠正检测】
当用户表达以下信号时，识别为纠正并记录：
1. 直接否定："不对"、"错了"、"不是这样的"
2. 给出不同答案："应该是"、"其实是"、"实际上是"
3. 温和引导："不过呢"、"换个角度"
4. 质疑："你确定？"、"真的吗？"
5. 示范正确做法（不说你错，直接展示正确做法）
6. 放弃让你做："算了我来" ← 强烈失败信号

纠正后流程（同一轮内完成）：
1. 承认 — 简洁承认，不找借口
2. 理解 — 确保理解正确做法
3. 记录 — 系统会自动记录到纠正日志
"""

# ── 学习记录触发指令 ──────────────────────────────────

LEARNING_LOG_INSTRUCTION = """\
【学习记录触发】
以下情况自动记录学习（不需要用户说"记住"）：
- 用户纠正了你 → 记录为 correction
- ≥3轮才搞清一个概念 → 记录为 insight
- 用户做了决策/选方案 → 记录到对话摘要
- 完成复杂任务（≥5步）→ 记录到对话摘要
- 发现数据口径/技巧 → 记录为 best_practice
- 用户表达偏好 → 记录到用户偏好
- 任务被搁置/等待 → 记录到活跃任务
"""

# ── NOT-to-save 列表 ──────────────────────────────────

NOT_TO_SAVE_INSTRUCTION = """\
【不存入核心记忆的内容】
以下内容即使用户说"记住"也不存入 MEMORY.md：
- 代码模式/架构/文件结构 — grep/find 可查
- Git 历史/谁改了什么 — git log/blame 权威
- 调试方案/修复步骤 — fix 在代码里
- 已有文档中的内容 — 不重复
- 临时任务状态/当前对话细节 — 完成后无价值
- 活动日志/PR列表汇总 — 记意外发现，不记列表
"""

# ── 记忆漂移验证指令 ──────────────────────────────────

DRIFT_PREVENTION_INSTRUCTION = """\
【记忆漂移防护】
基于记忆行动前，验证记忆准确性：
- 文件路径 → 检查文件是否存在
- 函数/API 名 → 确认仍存在
- 配置值 → 读取当前值
- 记忆 vs 当前状态矛盾 → 信当前状态，不信旧记忆
"""


# 夜间偏好语义合并：规则固定放 system，条目放 user，以便模型缓存稳定前缀。
PREFERENCE_MERGE_SYSTEM_PROMPT = """你是记忆库整理助手。请找出用户偏好条目中语义重复的内容，并给出合并方案。

要求：
1. 只合并确实在说同一件事的条目
2. 不同主题的条目不要合并
3. 合并后的文本要保留所有信息，用最完整的表述
4. 没有重复的条目不要放进合并组
5. 只输出严格 JSON，不要输出 markdown 代码块或解释文字

输出格式：
{
  "merge_groups": [
    {
      "indices": [1, 3, 5],
      "merged_text": "合并后的完整表述"
    }
  ]
}

如果没有任何重复条目，输出：{"merge_groups": []}
"""

PREFERENCE_MERGE_USER_PROMPT_TEMPLATE = """偏好条目列表（每条带编号）：
{items_text}
"""

# ── 完整自我改进 Prompt ───────────────────────────────

SELF_IMPROVEMENT_SYSTEM_PROMPT = """\
【自我改进系统指令】

你拥有自我改进能力，可以持续学习和纠正错误。

""" + CORRECTION_DETECTION_INSTRUCTION + "\n" + \
LEARNING_LOG_INSTRUCTION + "\n" + \
NOT_TO_SAVE_INSTRUCTION + "\n" + \
DRIFT_PREVENTION_INSTRUCTION


def build_self_improvement_prompt(
    *,
    include_correction: bool = True,
    include_learning: bool = True,
    include_not_to_save: bool = True,
    include_drift: bool = True,
    core_memory_text: str = "",
) -> str:
    """
    构建自我改进 prompt 组件。

    Args:
        include_correction: 包含纠正检测指令
        include_learning: 包含学习记录触发指令
        include_not_to_save: 包含 NOT-to-save 列表
        include_drift: 包含记忆漂移验证指令
        core_memory_text: 核心记忆注入文本（来自 MEMORY.md）

    Returns:
        完整的自我改进 prompt 文本
    """
    parts = []

    if include_correction:
        parts.append(CORRECTION_DETECTION_INSTRUCTION)
    if include_learning:
        parts.append(LEARNING_LOG_INSTRUCTION)
    if include_not_to_save:
        parts.append(NOT_TO_SAVE_INSTRUCTION)
    if include_drift:
        parts.append(DRIFT_PREVENTION_INSTRUCTION)

    if core_memory_text:
        parts.append(f"【核心记忆】\n{core_memory_text}")

    if not parts:
        return ""

    return "【自我改进系统指令】\n\n" + "\n\n".join(parts)
