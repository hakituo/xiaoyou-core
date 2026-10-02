"""主题配置、颜色工具与字体加载。

从 status_renderer.py 拆分而来，集中管理视觉主题与颜色/字体相关工具。
"""

import platform

from PIL import ImageFont

# --- 配置与主题 ---
THEME = {
    "bg_color": (5, 6, 10),       # #05060a
    "bg_color_2": (10, 12, 18),
    "glass_bg": (20, 20, 30, 200),  # 半透明（加深以保证可读性）
    "glass_border": (255, 255, 255, 30),
    "text_main": (226, 232, 240),  # #e2e8f0
    "text_dim": (100, 116, 139),   # Slate-500
    "primary": (14, 165, 233),     # Sky-500 #0ea5e9
    "accent": (16, 185, 129),      # Emerald-500 #10b981
    "danger": (244, 63, 94),       # Rose-500
    "warning": (234, 179, 8),      # Amber-500
    "glow_strength": 15,
    "shadow": (0, 0, 0, 90),
    "panel_bg": (18, 20, 28, 210),
    "panel_border": (255, 255, 255, 26),
    "panel_border_strong": (255, 255, 255, 46),
    "divider": (255, 255, 255, 16),
    "chip_bg": (255, 255, 255, 14),
}


def _hex_to_rgb(hex_color: str):
    """将十六进制颜色字符串转换为 (R, G, B) 三元组，失败时返回白色。"""
    s = str(hex_color or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    if len(s) != 6:
        return (255, 255, 255)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return (255, 255, 255)


def _emotion_palette(emotion: str | None, emotion_mix: dict | None = None):
    """根据情绪或情绪混合权重返回调色板字典。

    支持单一情绪或按权重混合多种情绪，返回包含 key/primary/glow/ambient/base 的字典。
    """
    palettes = {
        "neutral": ("#6B7280", "#A5ADC1", "#1C1F24", "#4B5563"),
        "happy": ("#F2CE77", "#FFE8B2", "#3A2E13", "#D3A74F"),
        "shy": ("#F3B8C8", "#FFD8E3", "#3F1B29", "#E58AA7"),
        "angry": ("#E86A73", "#FFC1C4", "#3D0E14", "#C1444E"),
        "jealous": ("#A58AF8", "#D3C6FF", "#2C2453", "#7E6AD9"),
        "wronged": ("#8CB2FF", "#CDE0FF", "#1B2A4C", "#5B8AE0"),
        "lost": ("#A3A3AD", "#D8D8E2", "#18181B", "#6E6E78"),
        "excited": ("#5EE3C0", "#C6FFF0", "#0D2E25", "#2FB395"),
        "coquetry": ("#F6A4C6", "#FFD6EC", "#381C2C", "#CF6D9A"),
    }

    def _mix_colors(mix: dict):
        # mix: {emotion_name: weight}
        total_weight = sum(mix.values())
        if total_weight <= 0:
            return palettes["neutral"]

        # 初始化 4 个颜色通道
        channels = [[0.0, 0.0, 0.0] for _ in range(4)]

        for emo, weight in mix.items():
            emo_key = str(emo).lower().strip()
            if emo_key == "sad":
                emo_key = "lost"
            if emo_key in {"upset", "wronged"}:
                emo_key = "wronged"
            if emo_key in {"coquette", "tsundere"}:
                emo_key = "coquetry"

            if emo_key in palettes:
                hex_colors = palettes[emo_key]
                for i in range(4):
                    rgb = _hex_to_rgb(hex_colors[i])
                    channels[i][0] += rgb[0] * weight
                    channels[i][1] += rgb[1] * weight
                    channels[i][2] += rgb[2] * weight

        result = []
        for i in range(4):
            r = int(channels[i][0] / total_weight)
            g = int(channels[i][1] / total_weight)
            b = int(channels[i][2] / total_weight)
            result.append((r, g, b))
        return result

    if emotion_mix and isinstance(emotion_mix, dict) and len(emotion_mix) > 0:
        colors = _mix_colors(emotion_mix)
        # colors 现在是 (r,g,b) 元组列表
        return {
            "key": "mixed",
            "primary": colors[0],
            "glow": colors[1],
            "ambient": colors[2],
            "base": colors[3],
        }

    k = str(emotion or "neutral").strip().lower()
    if k == "sad":
        k = "lost"
    if k in palettes:
        colors = palettes[k]
        return {
            "key": k,
            "primary": _hex_to_rgb(colors[0]),
            "glow": _hex_to_rgb(colors[1]),
            "ambient": _hex_to_rgb(colors[2]),
            "base": _hex_to_rgb(colors[3]),
        }

    # 默认兜底
    colors = palettes["neutral"]
    return {
        "key": "neutral",
        "primary": _hex_to_rgb(colors[0]),
        "glow": _hex_to_rgb(colors[1]),
        "ambient": _hex_to_rgb(colors[2]),
        "base": _hex_to_rgb(colors[3]),
    }


def _status_color(status: str):
    """根据状态字符串返回对应的主题颜色。"""
    s = str(status or "").lower().strip()
    if s in {"healthy", "ok", "good"}:
        return THEME["accent"]
    if s in {"degraded", "warning"}:
        return THEME["warning"]
    if s in {"unhealthy", "error", "failed", "down"}:
        return THEME["danger"]
    return THEME["text_dim"]


def get_font(size, variant="regular"):
    """尝试加载符合 'Inter' / 科幻风格的系统字体。"""
    system = platform.system()
    fonts = []

    if system == "Windows":
        if variant == "mono":
            fonts = ["consola.ttf", "cour.ttf", "msyh.ttc", "msyh.ttf", "arial.ttf"]
        else:
            fonts = ["msyh.ttc", "msyh.ttf", "seguiemj.ttf", "segoeui.ttf", "arial.ttf"]
    elif system == "Linux":
        if variant == "mono":
            fonts = ["DejaVuSansMono.ttf", "NotoSansMono-Regular.ttf"]
        else:
            fonts = ["DejaVuSans.ttf", "NotoSansCJK-Regular.ttc", "FreeSans.ttf"]

    for font_name in fonts:
        try:
            return ImageFont.truetype(font_name, size)
        except IOError:
            continue

    # Windows 路径兜底
    if system == "Windows":
        try:
            return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
        except Exception:
            pass

    return ImageFont.load_default()
