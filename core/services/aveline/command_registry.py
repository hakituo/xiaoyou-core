"""Aveline 服务端命令注册中心

P1-7: 单一真相源。/help 从此处动态生成，QQ 端通过 HTTP API 同步，
后端命令变更后前端展示自动更新，无需手动维护两份清单。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CommandSpec:
    """单条命令的元数据声明。

    name:        主命令名（不含 /），如 "clear"
    description: 简短描述（中文，用于 /help 一行展示）
    aliases:     别名列表（不含 /），如 ["study"]
    usage:       用法示例，如 "/studylog 主题|内容"
    master_only: 是否仅 Master 可用（服务端命令一般为 False）
    category:    分类标签，如 "记忆" / "学习" / "系统"
    """

    name: str
    description: str
    aliases: tuple[str, ...] = ()
    usage: str = ""
    master_only: bool = False
    category: str = "通用"


# ============================================================
# 命令注册表（单一真相源）
# 新增/修改命令只需在此处添加一行，/help 和 QQ 端自动同步。
# ============================================================
COMMAND_REGISTRY: List[CommandSpec] = [
    CommandSpec(
        name="clear",
        description="清除当前对话全部记忆",
        usage="/clear",
        category="记忆",
    ),
    CommandSpec(
        name="save",
        description="保存当前对话记录与偏好配置",
        usage="/save",
        category="系统",
    ),
    CommandSpec(
        name="mode",
        description="切换系统模式（normal/privacy/study/entertainment）",
        aliases=(),
        usage="/mode [normal|privacy|study|entertainment]",
        category="系统",
    ),
    CommandSpec(
        name="care",
        description="开关主动关怀",
        usage="/care [on|off]",
        category="系统",
    ),
    CommandSpec(
        name="forget",
        description="仅清除短期记忆（保留长期记忆）",
        usage="/forget",
        category="记忆",
    ),
    CommandSpec(
        name="memory",
        description="查看对话轮数、消息总数、系统内存占用",
        usage="/memory",
        category="记忆",
    ),
    CommandSpec(
        name="latency",
        description="开关仿生认知延迟（首 token 优化）",
        usage="/latency [on|off]",
        category="系统",
    ),
    CommandSpec(
        name="studylog",
        description="记录学习内容",
        aliases=("study",),
        usage="/studylog 主题|内容  或  /studylog 内容",
        category="学习",
    ),
    CommandSpec(
        name="studydone",
        description="记录学习收尾并切回 normal 模式",
        aliases=("studyfinish",),
        usage="/studydone [总结]",
        category="学习",
    ),
    CommandSpec(
        name="studypanel",
        description="查看学习面板聚合数据",
        aliases=("panelstudy",),
        usage="/studypanel",
        category="学习",
    ),
    CommandSpec(
        name="statistics",
        description="查看综合统计（对话/记忆/学习/提醒/系统）",
        aliases=("stats",),
        usage="/statistics",
        category="系统",
    ),
    CommandSpec(
        name="export",
        description="导出数据到文件（chat/diary/memory/all）",
        usage="/export [chat|diary|memory|all]",
        category="系统",
    ),
    CommandSpec(
        name="backup",
        description="备份全部用户数据为 zip 压缩包",
        usage="/backup",
        category="系统",
    ),
    CommandSpec(
        name="help",
        description="显示此帮助",
        usage="/help",
        category="系统",
    ),
]


def get_all_commands() -> List[CommandSpec]:
    """返回全部已注册命令。"""
    return list(COMMAND_REGISTRY)


def find_command(name: str) -> Optional[CommandSpec]:
    """按主名或别名查找命令。"""
    name = name.lower()
    for spec in COMMAND_REGISTRY:
        if spec.name == name or name in spec.aliases:
            return spec
    return None


def format_help_text() -> str:
    """动态生成 /help 文本，确保与注册表一致。"""
    # 按 category 分组
    groups: Dict[str, List[CommandSpec]] = {}
    for spec in COMMAND_REGISTRY:
        groups.setdefault(spec.category, []).append(spec)

    lines = ["可用指令："]
    for category, specs in groups.items():
        lines.append(f"\n【{category}】")
        for spec in specs:
            desc = spec.description
            if spec.usage:
                desc = f"{desc}（{spec.usage}）"
            lines.append(f"/{spec.name} - {desc}")

    return "\n".join(lines)


def get_command_list_for_api() -> List[Dict[str, object]]:
    """供 HTTP API 返回的结构化命令清单。

    QQ 端通过 /api/v1/commands 获取此清单，与本端 Bot 命令合并后渲染 /help。
    """
    result: List[Dict[str, object]] = []
    for spec in COMMAND_REGISTRY:
        result.append(
            {
                "command": f"/{spec.name}",
                "description": spec.description,
                "usage": spec.usage,
                "aliases": [f"/{a}" for a in spec.aliases],
                "master_only": spec.master_only,
                "category": spec.category,
                "source": "aveline_backend",
            }
        )
    return result
