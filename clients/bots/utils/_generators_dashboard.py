"""仪表盘概览与详情图生成函数。

从 status_renderer.py 拆分而来，包含综合仪表盘概览图与分区详情图。
"""

import time
import platform

from ._theme import THEME, _emotion_palette, _status_color
from ._renderer import SciFiRenderer
from ._text_utils import _safe_text, _fmt_optional, _display_name_only


def generate_dashboard_overview_image(payload: dict) -> str:
    """生成综合仪表盘概览图。"""
    renderer = SciFiRenderer(width=1100, height=760)

    # 使用 emotion_scores 作为 emotion_mix 进行丰富配色计算
    emotion_mix = payload.get("emotion_scores")
    emotion = payload.get("emotion")

    palette = _emotion_palette(emotion, emotion_mix=emotion_mix)
    renderer.draw_ambient_bg(palette)
    renderer.draw_grid_bg()

    def _to_float(v, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    def _pct_from_01(v, default: int = 0) -> int:
        try:
            f = float(v)
        except Exception:
            return default
        p = int(round(f * 100))
        if p < 0:
            return 0
        if p > 100:
            return 100
        return p

    margin = 40
    gap = 20
    left_w = 470
    right_x = margin + left_w + gap
    right_w = renderer.width - margin - right_x

    title = str(payload.get("title") or "QQ DASHBOARD")
    subtitle = str(payload.get("subtitle") or f"ID: {platform.node()} // {platform.system().upper()}")
    title_color = palette.get("primary") or THEME["primary"]
    renderer.draw.text((margin, 36), title, font=renderer.font_title, fill=title_color)
    renderer.draw.text((margin, 76), subtitle, font=renderer.font_mono, fill=THEME["text_dim"])

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    bbox = renderer.draw.textbbox((0, 0), ts, font=renderer.font_small)
    ts_w = bbox[2] - bbox[0]
    renderer.draw.text((renderer.width - margin - ts_w, 82), ts, font=renderer.font_small, fill=THEME["text_dim"])

    overall_status = str(payload.get("overall_status") or "unknown")
    overall_color = _status_color(overall_status)
    emotion_label = str(payload.get("emotion") or "NEUTRAL").strip().upper()
    access = "ADMIN" if payload.get("is_master") else "GUEST"

    pills_y = 110
    px = margin
    w, _ = renderer.draw_pill(px, pills_y, f"OVERALL {overall_status.upper()}", color=overall_color)
    px += w + 12
    w, _ = renderer.draw_pill(px, pills_y, f"EMO {emotion_label}", color=palette.get("primary") or THEME["primary"])
    px += w + 12
    renderer.draw_pill(px, pills_y, f"ACCESS {access}", color=(255, 200, 0) if payload.get("is_master") else THEME["text_dim"])

    core_color = palette.get("primary") or THEME["primary"]

    # --- 动态核心可视化逻辑 ---
    metrics = payload.get("core_metrics") or {}
    energy_v = _to_float(metrics.get("energy"), 100.0)
    imm_v = _to_float(metrics.get("immune_health"), 100.0)
    bio_v = _to_float(metrics.get("bionic_health"), 100.0)
    load_v = _to_float(metrics.get("load"), 0.0) * 100.0 if "load" in metrics else (_to_float(metrics.get("cpu_usage"), 0.0) + _to_float(metrics.get("memory_usage"), 0.0)) / 2.0

    # 系统健康覆盖（最高优先级）：紧急时强制使用 danger/warning 配色
    if imm_v < 40 or bio_v < 30:
        core_color = THEME["danger"]
    elif load_v > 90 or energy_v < 15:
        core_color = THEME["warning"]

    # 非紧急时，颜色跟随由完整 emotion_mix 计算的 palette["primary"]
    # （呼吸系统风格）

    core_x = margin
    core_y = 140
    core_h = 420  # 增加高度以容纳更多进度条
    renderer.draw_glass_panel(core_x, core_y, left_w, core_h, title="CORE SYSTEM")

    core_cx = int(core_x + left_w / 2)
    core_cy = int(core_y + 160)  # 调整中心
    core_debug = renderer.draw_dynamic_core_visual(core_cx, core_cy, 105, core_color, payload.get("core_metrics"))

    emo_pill = f"{emotion_label}"
    bbox = renderer.draw.textbbox((0, 0), emo_pill, font=renderer.font_mono)
    pill_w = (bbox[2] - bbox[0]) + 20
    renderer.draw_pill(core_x + left_w - 20 - pill_w, core_y + 14, emo_pill, color=core_color)

    energy = mood = load = imm_h = bio_h = 0
    if isinstance(core_debug, dict):
        energy = _pct_from_01(core_debug.get("energy"))
        mood = _pct_from_01(core_debug.get("mood_score"))
        load = _pct_from_01(core_debug.get("load"))
        imm_h = _pct_from_01(core_debug.get("immune_health"))
        bio_h = _pct_from_01(core_debug.get("bionic_health"))

    inner_pad = 20
    metric_gap = 20
    metric_w = int((left_w - inner_pad * 2 - metric_gap) / 2)
    mx1 = core_x + inner_pad
    mx2 = core_x + inner_pad + metric_w + metric_gap

    # 3 行指标
    my1 = core_y + 275
    my2 = core_y + 320
    my3 = core_y + 365

    renderer.draw_progress_bar(mx1, my1, metric_w, 10, energy, THEME["accent"], "ENERGY", f"{energy}%")
    renderer.draw_progress_bar(mx2, my1, metric_w, 10, mood, core_color, "MOOD", f"{mood}%")

    renderer.draw_progress_bar(mx1, my2, metric_w, 10, bio_h, THEME["primary"], "BIONIC HEALTH", f"{bio_h}%")
    renderer.draw_progress_bar(mx2, my2, metric_w, 10, imm_h, (180, 100, 255), "IMMUNE HEALTH", f"{imm_h}%")

    renderer.draw_progress_bar(mx1, my3, left_w - inner_pad * 2, 10, load, THEME["warning"], "SYSTEM LOAD", f"{load}%")

    sess_x = margin
    sess_y = 575  # 调整 Y
    sess_h = 145
    renderer.draw_glass_panel(sess_x, sess_y, left_w, sess_h, title="SESSION")
    renderer.draw.text((sess_x + 20, sess_y + 50), "SESSIONS:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((sess_x + 140, sess_y + 49), _fmt_optional(payload.get("session_total")), font=renderer.font_text, fill=THEME["text_main"])
    renderer.draw.text((sess_x + 20, sess_y + 82), "LATEST:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((sess_x + 140, sess_y + 81), _safe_text(payload.get("session_latest"), 42) or "—", font=renderer.font_text, fill=THEME["text_main"])
    renderer.draw.text((sess_x + 20, sess_y + 114), "MODEL:", font=renderer.font_mono, fill=THEME["text_dim"])
    model_display = payload.get("active_model")
    if not model_display or str(model_display).strip().lower() in {"none", "null", ""}:
        model_display = payload.get("model_name")
    renderer.draw.text((sess_x + 140, sess_y + 113), _safe_text(_display_name_only(model_display), 42) or "—", font=renderer.font_text, fill=THEME["text_main"])

    persona_display = payload.get("persona_name")
    if payload.get("is_master") and persona_display and str(persona_display).strip() and str(persona_display).strip().lower() not in {"none", "null"}:
        persona_pill = f"PERSONA {_safe_text(persona_display, 24)}"
        bbox = renderer.draw.textbbox((0, 0), persona_pill, font=renderer.font_mono)
        pill_w = (bbox[2] - bbox[0]) + 20
        renderer.draw_pill(sess_x + left_w - 20 - pill_w, sess_y + 14, persona_pill, color=THEME["primary"])

    col_gap = 18
    col_w = int((right_w - col_gap) / 2)
    top_y = 140
    mid_y = 370
    bot_y = 570

    cpu = _to_float(payload.get("cpu_usage"), 0.0)
    mem = _to_float(payload.get("memory_usage"), 0.0)
    gpu = payload.get("gpu_usage")

    renderer.draw_glass_panel(right_x, top_y, col_w, 200, title="RESOURCES")
    renderer.draw_progress_bar(right_x + 20, top_y + 50, col_w - 40, 10, cpu, THEME["primary"], "CPU", f"{cpu:.1f}%")
    renderer.draw_progress_bar(right_x + 20, top_y + 102, col_w - 40, 10, mem, THEME["accent"], "MEM", f"{mem:.1f}%")
    if isinstance(gpu, (int, float)):
        g = float(gpu)
        renderer.draw_progress_bar(right_x + 20, top_y + 154, col_w - 40, 10, g, THEME["warning"], "GPU", f"{g:.1f}%")
    else:
        renderer.draw.text((right_x + 20, top_y + 156), "GPU", font=renderer.font_mono, fill=THEME["text_dim"])
        renderer.draw.text((right_x + col_w - 68, top_y + 156), "N/A", font=renderer.font_mono, fill=THEME["text_main"])

    mod_x = right_x + col_w + col_gap
    renderer.draw_glass_panel(mod_x, top_y, col_w, 200, title="MODULES")
    row_y = top_y + 55
    row_step = 30
    renderer.draw.text((mod_x + 20, row_y), "LLM:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((mod_x + 90, row_y), _fmt_optional(payload.get("models_loaded")), font=renderer.font_text, fill=THEME["text_main"])
    renderer.draw.text((mod_x + 130, row_y), "/", font=renderer.font_text, fill=THEME["text_dim"])
    renderer.draw.text((mod_x + 145, row_y), _fmt_optional(payload.get("models_total")), font=renderer.font_text, fill=THEME["text_main"])
    renderer.draw.text((mod_x + 20, row_y + row_step), "IMG:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((mod_x + 90, row_y + row_step), _fmt_optional(payload.get("image_models_total")), font=renderer.font_text, fill=THEME["text_main"])
    renderer.draw.text((mod_x + 20, row_y + row_step * 2), "VOICE:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((mod_x + 90, row_y + row_step * 2), _fmt_optional(payload.get("voices_total")), font=renderer.font_text, fill=THEME["text_main"])
    renderer.draw.text((mod_x + 20, row_y + row_step * 3), "ACTIVE:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((mod_x + 90, row_y + row_step * 3), _safe_text(_display_name_only(payload.get("active_model")), 24) or "—", font=renderer.font_text, fill=THEME["text_main"])

    renderer.draw_glass_panel(right_x, mid_y, col_w, 170, title="SERVICES")
    unhealthy = int(_to_float(payload.get("unhealthy_service_count"), 0.0))
    total_svcs = int(_to_float(payload.get("service_count"), 0.0))
    renderer.draw.text((right_x + 20, mid_y + 58), "TOTAL:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((right_x + 110, mid_y + 57), str(total_svcs), font=renderer.font_text, fill=THEME["text_main"])
    renderer.draw.text((right_x + 20, mid_y + 92), "UNHEALTHY:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((right_x + 140, mid_y + 91), str(unhealthy), font=renderer.font_text, fill=_status_color("unhealthy") if unhealthy else THEME["accent"])
    renderer.draw.text((right_x + 20, mid_y + 126), "ACS:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((right_x + 110, mid_y + 125), _safe_text(payload.get("active_care_status"), 20) or "—", font=renderer.font_text, fill=_status_color(payload.get("active_care_status")))

    mem_x = right_x + col_w + col_gap
    renderer.draw_glass_panel(mem_x, mid_y, col_w, 170, title="MEMORY")
    renderer.draw.text((mem_x + 20, mid_y + 58), "TOTAL:", font=renderer.font_mono, fill=THEME["text_dim"])
    renderer.draw.text((mem_x + 110, mid_y + 57), _fmt_optional(payload.get("memory_total")), font=renderer.font_text, fill=THEME["text_main"])
    top_cats = payload.get("memory_top_categories")
    if isinstance(top_cats, list) and top_cats:
        y0 = mid_y + 92
        for i, row in enumerate(top_cats[:2]):
            if not isinstance(row, dict):
                continue
            cat = _safe_text(row.get("category"), 14)
            cnt = row.get("count")
            pct = row.get("pct")
            line = f"{cat}: {cnt}" if pct is None else f"{cat}: {cnt} ({pct:.1f}%)"
            renderer.draw.text((mem_x + 20, y0 + i * 30), line, font=renderer.font_mono, fill=THEME["text_main"])

    renderer.draw_glass_panel(right_x, bot_y, right_w, 140, title="EMOTION DETAIL")
    emo_scores = payload.get("emotion_scores")
    rows = []
    if isinstance(emo_scores, dict) and emo_scores:
        for k, v in sorted(emo_scores.items(), key=lambda kv: float(kv[1] or 0.0), reverse=True):
            try:
                vv = float(v or 0.0)
            except Exception:
                continue
            if vv <= 0:
                continue
            rows.append((str(k), max(0.0, min(1.0, vv))))
        rows = rows[:4]
    else:
        rows = [(emotion_label.lower(), 1.0)]

    bar_x = right_x + 120
    bar_w = int(right_w - 160)
    y = bot_y + 58
    row_h = 22
    for i, (k, vv) in enumerate(rows):
        label = _safe_text(str(k).upper(), 12)
        pct = int(round(vv * 100))
        renderer.draw.text((right_x + 20, y), label, font=renderer.font_mono, fill=THEME["text_dim"])
        val_text = f"{pct}%"
        bbox = renderer.draw.textbbox((0, 0), val_text, font=renderer.font_mono)
        vt_w = bbox[2] - bbox[0]
        renderer.draw.text((right_x + right_w - 20 - vt_w, y), val_text, font=renderer.font_mono, fill=THEME["text_main"])

        by = y + 12
        bh = 6
        renderer.draw.rounded_rectangle((bar_x, by, bar_x + bar_w, by + bh), radius=bh / 2, fill=(255, 255, 255, 14), outline=None)
        fw = int(bar_w * (pct / 100.0))
        if fw > 0:
            c = core_color if i == 0 else THEME["primary"]
            renderer.draw.rounded_rectangle((bar_x, by, bar_x + fw, by + bh), radius=bh / 2, fill=(*c, 235))
            renderer.draw.rounded_rectangle((bar_x, by - 2, bar_x + fw, by + bh + 2), radius=bh / 2, fill=(c[0], c[1], c[2], 45))

        y += row_h

    acc_color = (255, 200, 0) if payload.get("is_master") else THEME["text_dim"]
    renderer.draw.text((margin, renderer.height - 30), f"ACCESS LEVEL: {access}", font=renderer.font_small, fill=acc_color)

    return renderer.save(prefix="dashboard")


def generate_dashboard_detail_image(section_title: str, items: list) -> str:
    """生成仪表盘分区详情图。"""
    items = items if isinstance(items, list) else []
    cols = 2
    card_h = 72
    row_step = card_h + 18
    rows = (len(items) + cols - 1) // cols
    start_y = 320
    grid_h = (rows * row_step - (row_step - card_h)) if rows > 0 else 0
    height = max(800, min(1800, start_y + grid_h + 80))

    renderer = SciFiRenderer(width=1000, height=height)
    renderer.draw_ambient_bg(_emotion_palette("neutral"))
    renderer.draw_grid_bg()
    renderer.draw.text((40, 40), "DASHBOARD DETAIL", font=renderer.font_title, fill=THEME["primary"])
    renderer.draw.text((40, 80), str(section_title or "DETAIL").upper(), font=renderer.font_header, fill=THEME["text_dim"])

    renderer.draw_glass_panel(40, 120, 920, 120, title="SUMMARY")
    renderer.draw.text((60, 175), f"ITEMS: {len(items)}", font=renderer.font_mono, fill=THEME["text_main"])

    col_w = 450
    gap = 20

    for i, it in enumerate(items[:44]):
        if not isinstance(it, dict):
            it = {"title": str(it)}
        title = _safe_text(it.get("title"), 26)
        subtitle = _safe_text(it.get("subtitle"), 60)
        status = it.get("status")
        status_text = None
        status_color = None
        if status is not None:
            status_text = _safe_text(status, 14).upper()
            status_color = _status_color(status)

        cx = 40 + (i % cols) * (col_w + gap)
        cy = start_y + (i // cols) * row_step

        renderer.draw_status_list_item(
            cx,
            cy,
            col_w,
            card_h,
            i + 1,
            title,
            subtitle,
            status_text=status_text,
            status_color=status_color,
            is_highlight=bool(it.get("highlight")),
        )

    return renderer.save(prefix="dashboard_detail")
