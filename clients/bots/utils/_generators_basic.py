"""基础状态图生成函数。

从 status_renderer.py 拆分而来，包含状态面板、模型列表、人设列表、
语音列表与帮助指令列表等基础图像生成入口。
"""

import os
import time
import platform

from ._theme import THEME, _emotion_palette
from ._renderer import SciFiRenderer
from ._text_utils import _safe_text, _to_active_tokens, _display_name_only


def generate_status_image(
    cpu_percent: float,
    memory_percent: float,
    model_name: str,
    persona_name: str,
    is_master: bool = False,
    emotion_data: dict = None,
) -> str:
    """生成高科技仪表盘风格的状态图。"""
    renderer = SciFiRenderer(width=1000, height=600)
    palette = _emotion_palette((max(emotion_data, key=emotion_data.get) if isinstance(emotion_data, dict) and emotion_data else "neutral") if emotion_data else "neutral")
    renderer.draw_ambient_bg(palette)
    renderer.draw_grid_bg()

    # --- 头部 ---
    renderer.draw.text((40, 40), "AVELINE CORE SYSTEM", font=renderer.font_title, fill=THEME["primary"])
    renderer.draw.text((40, 80), f"ID: {platform.node()} // {platform.system().upper()}", font=renderer.font_mono, fill=THEME["text_dim"])

    # --- 左侧：核心可视化 ---
    # 根据情绪决定核心颜色
    core_color = palette.get("primary") or THEME["primary"]
    emotion_label = "NEUTRAL"

    if emotion_data:
        # 例如 {"happy": 0.8}
        if isinstance(emotion_data, dict) and emotion_data:
            top_emo = max(emotion_data, key=emotion_data.get)
            emotion_label = top_emo.upper()
            if top_emo in ["anger", "annoyance", "disgust"]:
                core_color = THEME["danger"]
            elif top_emo in ["joy", "excitement", "love"]:
                core_color = THEME["accent"]

    renderer.draw_core_visual(250, 300, 120, core_color)

    # 核心标签
    renderer.draw.text((250 - 40, 450), "CORE STATUS", font=renderer.font_mono, fill=THEME["text_dim"])
    bbox = renderer.draw.textbbox((0, 0), emotion_label, font=renderer.font_header)
    w = bbox[2] - bbox[0]
    renderer.draw.text((250 - w / 2, 470), emotion_label, font=renderer.font_header, fill=core_color)

    # --- 右侧：面板 ---
    panel_x = 500
    panel_w = 460

    # 1. 系统指标
    renderer.draw_glass_panel(panel_x, 100, panel_w, 180, title="SYSTEM RESOURCES")

    renderer.draw_progress_bar(panel_x + 20, 160, panel_w - 40, 10, cpu_percent, THEME["primary"], "CPU LOAD", f"{cpu_percent}%")
    renderer.draw_progress_bar(panel_x + 20, 220, panel_w - 40, 10, memory_percent, THEME["accent"], "MEMORY USAGE", f"{memory_percent}%")

    # 2. 上下文 / 记忆
    renderer.draw_glass_panel(panel_x, 300, panel_w, 260, title="COGNITIVE STATE")

    # 信息文本
    renderer.draw.text((panel_x + 20, 350), "ACTIVE MODEL:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((panel_x + 150, 350), model_name, font=renderer.font_text, fill=(255, 255, 255))

    renderer.draw.text((panel_x + 20, 380), "PERSONA:", font=renderer.font_mono, fill=THEME["text_dim"])
    display_persona = persona_name if is_master else "ENCRYPTED / PUBLIC"
    renderer.draw.text((panel_x + 150, 380), display_persona, font=renderer.font_text, fill=(255, 255, 255))

    # 记忆热力图
    renderer.draw.text((panel_x + 20, 420), "MEMORY ACTIVATION", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw_memory_heatmap(panel_x + 20, 440, 120, 100)

    # 任务队列
    renderer.draw.text((panel_x + 200, 420), "TASK QUEUE", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw_planning_stack(panel_x + 200, 440, 220)

    # --- 页脚 ---
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    # 修复：使用 renderer.width 和 renderer.height 而非 width/height
    renderer.draw.text((renderer.width - 200, renderer.height - 30), ts, font=renderer.font_small, fill=THEME["text_dim"])

    access = "ADMINISTRATOR" if is_master else "GUEST USER"
    acc_color = (255, 200, 0) if is_master else THEME["text_dim"]
    renderer.draw.text((40, renderer.height - 30), f"ACCESS LEVEL: {access}", font=renderer.font_small, fill=acc_color)

    return renderer.save(prefix="status")


def generate_model_list_image(
    llm_models: list,
    image_models: list,
    current_llm: str,
    current_image_model: str,
    filter_type: str = "all",  # "all", "llm", "image"
) -> str:
    """生成科幻风格的模型列表图。"""
    current_llm_tokens = _to_active_tokens(current_llm)
    current_image_tokens = _to_active_tokens(current_image_model)

    # 过滤模型
    display_llm = llm_models if filter_type in ["all", "llm"] else []
    display_img = image_models if filter_type in ["all", "image"] else []

    # 每项 80px + 分区标题 + 边距
    content_h = 160  # 头部 + 边距
    if display_llm:
        content_h += 60 + len(display_llm) * 80
    if display_img:
        content_h += 60 + len(display_img) * 80

    height = max(760, content_h + 100)
    renderer = SciFiRenderer(width=1000, height=height)
    renderer.draw_ambient_bg(_emotion_palette("neutral"))
    renderer.draw_grid_bg()

    title = "MODEL REGISTRY"
    if filter_type == "llm":
        title = "LLM REGISTRY"
    elif filter_type == "image":
        title = "IMAGE MODEL REGISTRY"

    renderer.draw.text((40, 40), title, font=renderer.font_title, fill=THEME["primary"])
    renderer.draw.text((40, 82), "CORE SYSTEM INFRASTRUCTURE", font=renderer.font_mono, fill=THEME["text_dim"])

    y_offset = 140
    col_w = 920

    # --- LLM 分区 ---
    if display_llm:
        renderer.draw.text((40, y_offset), "LARGE LANGUAGE MODELS", font=renderer.font_header, fill=(255, 255, 255, 120))
        renderer.draw.line((40, y_offset + 35, 40 + col_w, y_offset + 35), fill=THEME["divider"], width=1)
        y_offset += 55

        for i, model in enumerate(display_llm):
            raw_name = model.get("name") or model.get("id") or "Unknown"
            name = _display_name_only(raw_name)
            provider = str(model.get("provider", "local")).upper()
            path = model.get("path") or model.get("model") or ""

            is_active = bool(
                {str(raw_name or "").strip(), str(model.get("id") or "").strip(), str(path or "").strip()}
                & current_llm_tokens
            )

            renderer.draw_list_item(
                40, y_offset, col_w, 68,
                i + 1,
                name,
                f"PROVIDER: {provider} // PATH: {path}",
                is_active,
            )
            y_offset += 80

    # --- 图像模型分区 ---
    if display_img:
        if display_llm:
            y_offset += 40
        renderer.draw.text((40, y_offset), "IMAGE GENERATION MODELS", font=renderer.font_header, fill=(255, 255, 255, 120))
        renderer.draw.line((40, y_offset + 35, 40 + col_w, y_offset + 35), fill=THEME["divider"], width=1)
        y_offset += 55

        for i, model in enumerate(display_img):
            raw_name = model.get("name") or model.get("id") or "Unknown"
            name = _display_name_only(raw_name)
            path = model.get("path") or ""

            is_active = bool(
                {str(raw_name or "").strip(), str(model.get("id") or "").strip(), str(path or "").strip()}
                & current_image_tokens
            )

            renderer.draw_list_item(
                40, y_offset, col_w, 68,
                (len(display_llm) if filter_type == "all" else 0) + i + 1,
                name,
                f"TYPE: DIFFUSION // PATH: {path}",
                is_active,
            )
            y_offset += 80

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    renderer.draw.text((renderer.width - 240, renderer.height - 30), ts, font=renderer.font_small, fill=THEME["text_dim"])

    return renderer.save(prefix="models")


def generate_persona_list_image(personas: list, current_persona_filename: str) -> str:
    """生成科幻风格的人设列表图。"""
    total_items = len(personas)
    content_height = 220 + total_items * 80
    height = max(760, content_height)

    renderer = SciFiRenderer(width=1000, height=height)
    renderer.draw_ambient_bg(_emotion_palette("neutral"))
    renderer.draw_grid_bg()

    renderer.draw.text((40, 40), "PERSONA REGISTRY", font=renderer.font_title, fill=THEME["primary"])
    renderer.draw.text((40, 82), "ACTIVE ROLE PROFILE MATRIX", font=renderer.font_mono, fill=THEME["text_dim"])

    active_name = "UNKNOWN"
    current_filename = str(current_persona_filename or "").strip()
    for persona in personas:
        if not isinstance(persona, dict):
            continue
        filename = str(persona.get("filename") or "").strip()
        if filename and filename == current_filename:
            active_name = str(persona.get("name") or "").strip() or os.path.basename(filename)
            break

    renderer.draw_glass_panel(40, 118, 920, 92, title="ACTIVE PERSONA")
    renderer.draw.text((60, 162), _safe_text(active_name, 48) or "UNKNOWN", font=renderer.font_header, fill=THEME["text_main"])
    renderer.draw.text((60, 188), _safe_text(current_filename, 96) or "未读取到当前人设文件", font=renderer.font_mono, fill=THEME["text_dim"])

    y_offset = 240
    for i, persona in enumerate(personas, start=1):
        if not isinstance(persona, dict):
            continue
        filename = str(persona.get("filename") or "").strip()
        name = str(persona.get("name") or "").strip() or os.path.basename(filename) or f"persona_{i}"
        category = str(persona.get("category") or "").strip() or "general"
        version = str(persona.get("version") or "").strip()
        subtitle = f"CATEGORY: {category.upper()}"
        if version:
            subtitle += f" // VER: {version}"
        if filename:
            subtitle += f" // FILE: {filename}"
        renderer.draw_list_item(
            40,
            y_offset,
            920,
            68,
            i,
            _safe_text(name, 42),
            _safe_text(subtitle, 108),
            is_active=bool(filename and current_filename and filename == current_filename),
        )
        y_offset += 80

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    renderer.draw.text((renderer.width - 240, renderer.height - 30), ts, font=renderer.font_small, fill=THEME["text_dim"])
    return renderer.save(prefix="personas")


def generate_voice_list_image(voices: list, current_voice: str) -> str:
    """生成参考音频列表图。"""
    total_items = len(voices)
    content_height = total_items * 70 + 150
    height = max(800, content_height)

    renderer = SciFiRenderer(width=800, height=height)
    renderer.draw_ambient_bg(_emotion_palette("neutral"))
    renderer.draw_grid_bg()

    renderer.draw.text((40, 40), "AUDIO REFERENCE DATABASE", font=renderer.font_title, fill=THEME["primary"])

    y_offset = 100

    if total_items <= 0:
        renderer.draw_glass_panel(40, 120, 720, 180, title="NO AUDIO REFERENCES")
        renderer.draw.text((60, 170), "未找到参考音频文件", font=renderer.font_header, fill=THEME["text_main"])
        renderer.draw.text((60, 210), "请将 .wav/.mp3/.ogg/.flac 放入: ref_audio/female", font=renderer.font_text, fill=THEME["text_dim"])
        renderer.draw.text((60, 245), "然后发送: /参考音频 重新刷新", font=renderer.font_text, fill=THEME["accent"])
        return renderer.save(prefix="voices")

    for i, voice in enumerate(voices):
        name = voice.get("name") or os.path.basename(voice.get("path", ""))
        path = voice.get("path", "")

        is_active = (path == current_voice) or (name == current_voice)

        renderer.draw_list_item(40, y_offset, 720, 60, i + 1, name, path, is_active)
        y_offset += 70

    return renderer.save(prefix="voices")


def generate_help_image(commands: list) -> str:
    """生成指令帮助列表图。"""
    cmds = [c for c in (commands or []) if isinstance(c, dict)]
    total_items = len(cmds)
    cols = 2
    rows = (total_items + cols - 1) // cols
    card_h = 78
    row_gap = 14
    header_h = 240
    height = max(720, header_h + rows * (card_h + row_gap) + 60)

    renderer = SciFiRenderer(width=900, height=height)
    renderer.draw_ambient_bg(_emotion_palette("neutral"))
    renderer.draw_grid_bg()

    renderer.draw.text((40, 40), "COMMANDS", font=renderer.font_title, fill=THEME["primary"])
    renderer.draw.text((40, 82), "QQ BOT INTERFACE", font=renderer.font_mono, fill=THEME["text_dim"])

    renderer.draw_glass_panel(40, 110, 820, 88, title="QUICK START")
    renderer.draw.text((60, 155), "发送 /help 查看全部指令；发送 /状态 获取系统面板（别名 /面板）", font=renderer.font_text, fill=THEME["text_main"])

    grid_x = 40
    grid_y = header_h
    col_gap = 18
    col_w = int((820 - col_gap) / 2)

    for i, cmd in enumerate(cmds):
        name = _safe_text(cmd.get("command"), 24)
        desc = _safe_text(cmd.get("description"), 54)

        cx = grid_x + (i % cols) * (col_w + col_gap)
        cy = grid_y + (i // cols) * (card_h + row_gap)

        renderer.draw.rounded_rectangle(
            (cx, cy, cx + col_w, cy + card_h),
            radius=14,
            fill=(30, 40, 50, 105),
            outline=THEME["panel_border"],
            width=1,
        )

        renderer.draw.text((cx + 18, cy + 16), f"{i + 1:02d}", font=renderer.font_mono, fill=THEME["text_dim"])
        renderer.draw.text((cx + 62, cy + 14), name, font=renderer.font_header, fill=THEME["accent"])
        renderer.draw.text((cx + 62, cy + 44), desc, font=renderer.font_text, fill=THEME["text_main"])

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    renderer.draw.text((renderer.width - 240, renderer.height - 30), ts, font=renderer.font_small, fill=THEME["text_dim"])
    return renderer.save(prefix="help")
