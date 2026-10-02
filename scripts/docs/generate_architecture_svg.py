#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Xiaoyou Core 架构图 SVG。

输出路径: static/demo/architecture.svg
"""

from __future__ import annotations

import os

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "static", "demo", "architecture.svg"
)

WIDTH = 1500
HEIGHT = 1180

STYLES = """    <style>
      .title { font: 700 28px Arial, sans-serif; fill: #111827; }
      .subtitle { font: 600 15px Arial, sans-serif; fill: #111827; }
      .text { font: 13px Arial, sans-serif; fill: #111827; }
      .small { font: 11px Arial, sans-serif; fill: #374151; }
      .group-label { font: 700 16px Arial, sans-serif; fill: #111827; }
      .box { fill: #ffffff; stroke: #94a3b8; stroke-width: 1; rx: 8; ry: 8; }
      .arrow { stroke: #64748b; stroke-width: 1.5; fill: none; marker-end: url(#arrowhead); }
    </style>
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#64748b"/>
    </marker>"""


def rect(x: int, y: int, w: int, h: int, fill: str, stroke: str) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="2" rx="14" ry="14"/>'


def box(x: int, y: int, w: int, h: int, label: str, sub: str = "") -> str:
    lines = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" class="box"/>']
    cy = y + h // 2
    if sub:
        lines.append(f'<text x="{x + w // 2}" y="{cy - 4}" text-anchor="middle" class="text">{label}</text>')
        lines.append(f'<text x="{x + w // 2}" y="{cy + 14}" text-anchor="middle" class="small">{sub}</text>')
    else:
        lines.append(f'<text x="{x + w // 2}" y="{cy + 5}" text-anchor="middle" class="text">{label}</text>')
    return "\n".join(lines)


def text(x: int, y: int, label: str, cls: str = "subtitle") -> str:
    return f'<text x="{x}" y="{y}" text-anchor="middle" class="{cls}">{label}</text>'


def arrow(x1: int, y1: int, x2: int, y2: int) -> str:
    return f'<path d="M {x1} {y1} L {x2} {y2}" class="arrow"/>'


def layer_group(x: int, y: int, w: int, h: int, fill: str, stroke: str, label: str) -> str:
    return rect(x, y, w, h, fill, stroke) + "\n" + text(x + w // 2, y + 24, label, "group-label")


def main() -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    parts: list[str] = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<svg width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg">',
        "  <defs>",
        STYLES,
        "  </defs>",
        f'  <rect x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        text(WIDTH // 2, 40, "Xiaoyou Core 系统架构", "title"),
        text(WIDTH // 2, 68, "分层架构：客户端 → 接口层 → 核心层 → 记忆/调度层 → 存储层", "small"),
    ]

    # 客户端层
    parts.append(layer_group(40, 90, 1420, 120, "#e3f2fd", "#1e88e5", "客户端层 Clients"))
    clients = [
        (60, 130, "Web (React + Vite)"),
        (270, 130, "Android (Kotlin)"),
        (480, 130, "iOS (Swift)"),
        (690, 130, "Electron 桌面"),
        (900, 130, "QQ 机器人"),
        (1110, 130, "Telegram 机器人"),
        (1280, 130, "Obsidian"),
    ]
    for x, y, label in clients:
        parts.append(box(x, y, 180, 60, label))

    # 接口层
    parts.append(layer_group(40, 230, 1420, 120, "#e8f5e9", "#43a047", "接口层 Interface / Routers"))
    interfaces = [
        (110, 270, "/api/v1/ 业务路由"),
        (430, 270, "/api/admin/ 运维路由"),
        (750, 270, "/api/v1/ws WebSocket"),
        (1070, 270, "/v1 OpenAI Compatible"),
    ]
    for x, y, label in interfaces:
        parts.append(box(x, y, 260, 60, label))

    # 核心层
    parts.append(layer_group(40, 370, 1420, 520, "#fff8e1", "#fb8c00", "核心层 Core"))

    # 核心引擎
    parts.append(rect(70, 410, 260, 180, "#e1f5fe", "#039be5"))
    parts.append(text(200, 434, "核心引擎 core_engine", "subtitle"))
    ce_items = ["EventBus", "LifecycleManager", "ModelManager", "ConfigManager", "ServiceRegistry"]
    for i, item in enumerate(ce_items):
        parts.append(box(90, 450 + i * 26, 220, 24, item))

    # 服务层
    parts.append(rect(350, 410, 340, 230, "#e8f5e9", "#43a047"))
    parts.append(text(520, 434, "服务层 services / 25+", "subtitle"))
    svc_items = [
        "AvelineService", "ActiveCare", "Workspace", "Scheduler",
        "Immune", "AutoHeal", "LifeSimulation", "Study",
        "Journal", "Daily", "DataOps", "SelfImprovement",
    ]
    for i, item in enumerate(svc_items):
        col = i % 2
        row = i // 2
        parts.append(box(370 + col * 160, 450 + row * 30, 150, 26, item))

    # Agent 层
    parts.append(rect(710, 410, 220, 110, "#f3e5f5", "#8e24aa"))
    parts.append(text(820, 434, "Agent 层 agents", "subtitle"))
    parts.append(box(730, 450, 180, 24, "ChatAgent"))
    parts.append(box(730, 482, 180, 24, "PersonaSystem / Prompt"))

    # 模块层
    parts.append(rect(710, 540, 720, 120, "#fff3e0", "#ef6c00"))
    parts.append(text(1070, 564, "模块层 modules", "subtitle"))
    mod_items = ["LLM", "Vision", "Voice", "Image", "Memory Module"]
    for i, item in enumerate(mod_items):
        parts.append(box(730 + i * 140, 585, 120, 55, item))

    # 工具层
    parts.append(rect(950, 410, 480, 110, "#eceff1", "#546e7a"))
    parts.append(text(1190, 434, "工具层 tools / 24+", "subtitle"))
    tool_items = ["Study", "Daily/Diary", "Reminder", "Status/Food", "Search"]
    for i, item in enumerate(tool_items):
        parts.append(box(970 + i * 92, 450, 82, 24, item))
        parts.append(box(970 + i * 92, 482, 82, 24, "..."))

    # 情绪系统
    parts.append(rect(70, 610, 260, 100, "#fce4ec", "#d81b60"))
    parts.append(text(200, 634, "情绪系统 emotion", "subtitle"))
    parts.append(box(90, 650, 220, 24, "13 种情绪检测/计算/存储"))

    # 人物档案
    parts.append(rect(350, 660, 340, 100, "#e8eaf6", "#3f51b5"))
    parts.append(text(520, 684, "人物档案 people", "subtitle"))
    parts.append(box(370, 700, 300, 44, "Profile Storage / Multi-Version Persona"))

    # 记忆层
    parts.append(layer_group(40, 910, 680, 120, "#f3e5f5", "#8e24aa", "记忆层 Memory"))
    mem_items = ["WeightedMemory", "VectorSearch", "KeywordIndex", "Distillation"]
    for i, item in enumerate(mem_items):
        parts.append(box(80 + i * 160, 950, 150, 60, item))

    # 调度层
    parts.append(layer_group(740, 910, 720, 120, "#ffebee", "#e53935", "调度层 Scheduler"))
    sch_items = ["C++ Scheduler", "Global Task Scheduler", "Bio System"]
    for i, item in enumerate(sch_items):
        parts.append(box(780 + i * 220, 950, 200, 60, item))

    # 存储层
    parts.append(layer_group(40, 1050, 1420, 100, "#f5f5f5", "#757575", "存储层 Storage"))
    sto_items = ["JSON Files", "ChromaDB", "SQLite", "Redis L2 Cache"]
    for i, item in enumerate(sto_items):
        parts.append(box(120 + i * 340, 1085, 300, 45, item))

    # 箭头：Clients -> Interface
    for sx in [150, 360, 570, 780, 990, 1200, 1370]:
        parts.append(arrow(sx, 190, sx, 230))

    # 箭头：Interface -> Core
    for sx in [240, 560, 880, 1200]:
        parts.append(arrow(sx, 350, sx, 370))

    # 箭头：Core -> Memory / Scheduler
    parts.append(arrow(400, 890, 400, 910))
    parts.append(arrow(1100, 890, 1100, 910))

    # 箭头：Memory/Scheduler -> Storage
    parts.append(arrow(400, 1030, 400, 1050))
    parts.append(arrow(1100, 1030, 1100, 1050))

    # 箭头：Core -> Storage (直接)
    parts.append(arrow(750, 850, 750, 1050))

    parts.append("</svg>")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    print(f"已生成架构图: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
