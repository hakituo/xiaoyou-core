"""SciFiRenderer 科幻风格图像渲染器。

从 status_renderer.py 拆分而来，集中管理画布、面板、进度条、核心图形等绘制逻辑。
"""

import os
import time
import random

from PIL import Image, ImageDraw

from ._theme import THEME, _emotion_palette, get_font


class SciFiRenderer:
    """科幻风格状态图渲染器，封装画布、面板与各种可视化组件的绘制。"""

    def __init__(self, width=1000, height=600):
        self.width = width
        self.height = height
        self.image = Image.new("RGB", (width, height), THEME["bg_color"])
        self.draw = ImageDraw.Draw(self.image, "RGBA")

        # 字体
        self.font_title = get_font(32)
        self.font_header = get_font(20)  # 加粗风格
        self.font_text = get_font(16)
        self.font_mono = get_font(14, variant="mono")
        self.font_small = get_font(12)

    def _draw_radial_glow(self, cx, cy, radius, color_rgb, alpha=90, steps=8):
        """绘制径向辉光（通过多层透明椭圆叠加模拟）。"""
        r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
        max_a = int(alpha)
        for i in range(int(steps)):
            t = i / max(1, steps - 1)
            a = int(max_a * (1.0 - t) * (1.0 - t))
            rr = float(radius) * (0.35 + 0.65 * t)
            self.draw.ellipse((int(cx - rr), int(cy - rr), int(cx + rr), int(cy + rr)), fill=(r, g, b, a))

    def draw_ambient_bg(self, palette: dict | None = None):
        """绘制带情绪色调的氛围背景。"""
        p = palette if isinstance(palette, dict) else _emotion_palette("neutral")

        # 基础背景叠加情绪基色的轻微色调
        base_color = p.get("ambient") or THEME["bg_color"]
        # 与黑色混合保持暗色基调
        bg_fill = (
            int(base_color[0] * 0.2 + THEME["bg_color"][0] * 0.8),
            int(base_color[1] * 0.2 + THEME["bg_color"][1] * 0.8),
            int(base_color[2] * 0.2 + THEME["bg_color"][2] * 0.8),
            255,
        )

        self.draw.rectangle((0, 0, self.width, self.height), fill=bg_fill)

        self._draw_radial_glow(int(self.width * 0.18), int(self.height * 0.12), int(min(self.width, self.height) * 0.55), p["glow"], alpha=90, steps=10)
        self._draw_radial_glow(int(self.width * 0.86), int(self.height * 0.82), int(min(self.width, self.height) * 0.62), p["primary"], alpha=80, steps=10)
        self._draw_radial_glow(int(self.width * 0.52), int(self.height * 0.58), int(min(self.width, self.height) * 0.42), p["base"], alpha=55, steps=9)

        self.draw.rectangle((0, 0, self.width, self.height), fill=(0, 0, 0, 70))

    def draw_grid_bg(self):
        """绘制淡色科技网格背景。"""
        step = 40
        for x in range(0, self.width, step):
            self.draw.line((x, 0, x, self.height), fill=(30, 40, 50, 26), width=1)
        for y in range(0, self.height, step):
            self.draw.line((0, y, self.width, y), fill=(30, 40, 50, 26), width=1)

        # 随机"激活"网格单元
        for _ in range(10):
            gx = random.randrange(0, self.width, step)
            gy = random.randrange(0, self.height, step)
            self.draw.rectangle(
                (gx, gy, gx + step, gy + step),
                fill=(14, 165, 233, 10),
                outline=None,
            )

    def draw_glass_panel(self, x, y, w, h, title=None, color=None):
        """绘制带标题的玻璃拟态面板。"""
        border_color = color if color else THEME["panel_border"]

        self.draw.rounded_rectangle(
            (x + 2, y + 4, x + w + 2, y + h + 4),
            radius=16,
            fill=THEME["shadow"],
            outline=None,
        )

        # 背景
        self.draw.rounded_rectangle(
            (x, y, x + w, y + h),
            radius=16,
            fill=THEME["panel_bg"],
            outline=border_color,
            width=1,
        )

        if title:
            # 标题头
            self.draw.text(
                (x + 20, y + 20),
                title.upper(),
                font=self.font_header,
                fill=(255, 255, 255, 120),
            )

            self.draw.line((x + 20, y + 48, x + w - 20, y + 48), fill=THEME["divider"], width=1)

    def draw_pill(self, x, y, text, color=None, padding=(10, 6)):
        """绘制胶囊状标签，返回 (宽, 高)。"""
        t = str(text or "")
        bbox = self.draw.textbbox((0, 0), t, font=self.font_mono)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        px, py = int(padding[0]), int(padding[1])
        w = tw + px * 2
        h = th + py * 2
        fill = (*THEME["chip_bg"][:3], THEME["chip_bg"][3]) if isinstance(THEME.get("chip_bg"), tuple) else (255, 255, 255, 14)
        self.draw.rounded_rectangle((x, y, x + w, y + h), radius=int(h / 2), fill=fill, outline=THEME["panel_border"], width=1)
        if color:
            self.draw.ellipse((x + 8, y + h / 2 - 3, x + 14, y + h / 2 + 3), fill=(*color, 220))
            tx = x + 18
        else:
            tx = x + px
        self.draw.text((tx, y + py - 1), t, font=self.font_mono, fill=THEME["text_main"])
        return (w, h)

    def draw_progress_bar(self, x, y, w, h, percent, color, label, value_text):
        """绘制带辉光效果的进度条。"""
        # 标签
        self.draw.text((x, y), label, font=self.font_mono, fill=THEME["text_dim"])

        # 数值文本（右对齐）
        bbox = self.draw.textbbox((0, 0), value_text, font=self.font_mono)
        text_w = bbox[2] - bbox[0]
        self.draw.text((x + w - text_w, y), value_text, font=self.font_mono, fill=THEME["text_main"])

        bar_y = y + 25
        bar_h = 8
        self.draw.rounded_rectangle((x, bar_y, x + w, bar_y + bar_h), radius=bar_h / 2, fill=(255, 255, 255, 14), outline=None)

        # 激活条
        fill_w = int(w * (min(max(percent, 0), 100) / 100))
        if fill_w > 0:
            self.draw.rounded_rectangle((x, bar_y, x + fill_w, bar_y + bar_h), radius=bar_h / 2, fill=(*color, 235))

            # 辉光效果（通过多层半透明圆角矩形模拟，避免全图模糊的高开销）
            self.draw.rounded_rectangle((x, bar_y - 2, x + fill_w, bar_y + bar_h + 2), radius=bar_h / 2, fill=(color[0], color[1], color[2], 70))
            self.draw.rounded_rectangle((x, bar_y - 4, x + fill_w, bar_y + bar_h + 4), radius=bar_h / 2, fill=(color[0], color[1], color[2], 35))

    def draw_core_visual(self, cx, cy, size, color):
        """绘制中心八面体/菱形核心图形。"""
        # 外层辉光（通过分层渐变模拟）

        # 绘制菱形（八面体的 2D 投影）
        half = size / 2
        points = [
            (cx, cy - size),
            (cx + half, cy),
            (cx, cy + size),
            (cx - half, cy),
        ]

        # 外层线框
        self.draw.polygon(points, outline=color, fill=(color[0], color[1], color[2], 20))

        # 内核
        inner_size = size * 0.4
        inner_points = [
            (cx, cy - inner_size),
            (cx + inner_size * 0.8, cy),
            (cx, cy + inner_size),
            (cx - inner_size * 0.8, cy),
        ]
        self.draw.polygon(inner_points, fill=color)

        # 连接线（顶点到中心）
        self.draw.line((cx, cy - size, cx, cy - inner_size), fill=color, width=1)
        self.draw.line((cx, cy + size, cx, cy + inner_size), fill=color, width=1)
        self.draw.line((cx + half, cy, cx + inner_size * 0.8, cy), fill=color, width=1)
        self.draw.line((cx - half, cy, cx - inner_size * 0.8, cy), fill=color, width=1)

        # 周围"环"
        bbox = (cx - size * 0.8, cy - size * 0.2, cx + size * 0.8, cy + size * 0.2)
        self.draw.ellipse(bbox, outline=(255, 255, 255, 50), width=1)

    def draw_dynamic_core_visual(self, cx, cy, base_size, color, metrics: dict | None = None):
        """根据指标动态绘制核心图形，返回各维度归一化指标。"""
        m = metrics if isinstance(metrics, dict) else {}

        def _clamp01(v):
            try:
                f = float(v)
            except Exception:
                return 0.0
            if f < 0.0:
                return 0.0
            if f > 1.0:
                return 1.0
            return f

        energy = _clamp01((m.get("energy") or 0.0) / 100.0)
        mood_score = _clamp01((m.get("mood_score") or 0.0) / 100.0)
        immune_health = _clamp01((m.get("immune_health") or 100.0) / 100.0)
        bionic_health = _clamp01((m.get("bionic_health") or 100.0) / 100.0)

        cpu_u = _clamp01((m.get("cpu_usage") or 0.0) / 100.0)
        mem_u = _clamp01((m.get("memory_usage") or 0.0) / 100.0)
        gpu_v = m.get("gpu_usage")
        gpu_u = _clamp01((gpu_v or 0.0) / 100.0) if isinstance(gpu_v, (int, float)) else None
        load = (cpu_u + mem_u + (gpu_u if gpu_u is not None else 0.0)) / (3.0 if gpu_u is not None else 2.0)

        # 形状逻辑：
        # 上：能量（向上的活力）
        # 下：系统负载（向下的压力）
        # 右：免疫健康（物理外壳）
        # 左：仿生健康（内部系统）

        top_r = base_size * (0.50 + 0.70 * energy)
        bottom_r = base_size * (0.50 + 0.70 * load)
        right_r = base_size * (0.50 + 0.70 * immune_health)
        left_r = base_size * (0.50 + 0.70 * bionic_health)

        half = base_size / 2
        points = [
            (cx, cy - top_r),                                # 上
            (cx + half * (right_r / base_size), cy),         # 右
            (cx, cy + bottom_r),                             # 下
            (cx - half * (left_r / base_size), cy),          # 左
        ]

        self.draw.polygon(points, outline=color, fill=(color[0], color[1], color[2], 22))

        # 内核脉动效果模拟
        inner_scale = 0.38
        inner_points = [
            (cx, cy - top_r * inner_scale),
            (cx + half * (right_r / base_size) * inner_scale * 1.2, cy),
            (cx, cy + bottom_r * inner_scale),
            (cx - half * (left_r / base_size) * inner_scale * 1.2, cy),
        ]
        self.draw.polygon(inner_points, fill=color)

        # 连接线
        for i in range(4):
            self.draw.line((points[i][0], points[i][1], inner_points[i][0], inner_points[i][1]), fill=color, width=1)

        # 大气环
        ring_w = base_size * (0.95 + 0.35 * mood_score)
        ring_h = base_size * (0.22 + 0.15 * (1.0 - immune_health))
        bbox = (cx - ring_w * 0.8, cy - ring_h, cx + ring_w * 0.8, cy + ring_h)
        self.draw.ellipse(bbox, outline=(255, 255, 255, 45), width=1)

        return {
            "points": points,
            "energy": energy,
            "mood_score": mood_score,
            "load": load,
            "immune_health": immune_health,
            "bionic_health": bionic_health,
        }

    def draw_memory_heatmap(self, x, y, w, h):
        """绘制模拟记忆激活的网格热力图。"""
        cols = 6
        rows = 6
        cell_w = (w - (cols - 1) * 4) / cols
        cell_h = cell_w  # 正方形

        for r in range(rows):
            for c in range(cols):
                cx = x + c * (cell_w + 4)
                cy = y + r * (cell_h + 4)

                # 随机激活
                val = random.random()
                if val > 0.8:
                    color = THEME["accent"]  # 激活
                elif val > 0.6:
                    color = THEME["primary"]  # 空闲
                else:
                    color = (255, 255, 255, 20)  # 未激活

                self.draw.rectangle((cx, cy, cx + cell_w, cy + cell_h), fill=color)

    def draw_planning_stack(self, x, y, w):
        """绘制模拟任务队列列表。"""
        tasks = [
            ("SLOT_01: GOAL_PARSING", "ACTIVE", THEME["accent"]),
            ("SLOT_02: CONTEXT_RETRIEVAL", "WAITING", THEME["text_dim"]),
            ("SLOT_03: RESPONSE_GEN", "IDLE", (255, 255, 255, 50)),
        ]

        curr_y = y
        for label, status, color in tasks:
            # 框
            self.draw.rectangle((x, curr_y, x + w, curr_y + 30), fill=(255, 255, 255, 10), outline=(255, 255, 255, 20))

            # 文本
            self.draw.text((x + 10, curr_y + 8), label, font=self.font_small, fill=color)

            # 状态
            bbox = self.draw.textbbox((0, 0), status, font=self.font_small)
            sw = bbox[2] - bbox[0]
            self.draw.text((x + w - sw - 10, curr_y + 8), status, font=self.font_small, fill=color)

            curr_y += 38

    def save(self, prefix="status"):
        """保存图像到 temp_images 目录，返回文件路径。"""
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_images")
        os.makedirs(temp_dir, exist_ok=True)
        filename = f"{prefix}_{int(time.time())}_{random.randint(1000, 9999)}.png"
        filepath = os.path.join(temp_dir, filename)
        self.image.save(filepath)
        return filepath

    def draw_list_item(self, x, y, w, h, index, title, subtitle, is_active=False, is_highlight=False):
        """绘制模型/语音列表中使用的列表项。"""
        bg_color = (30, 40, 50, 105)
        border_color = THEME["panel_border"]

        if is_active:
            bg_color = (16, 185, 129, 50)  # 绿色调
            border_color = THEME["accent"]
        elif is_highlight:
            bg_color = (14, 165, 233, 50)  # 蓝色调
            border_color = THEME["primary"]

        self.draw.rounded_rectangle(
            (x + 2, y + 4, x + w + 2, y + h + 4),
            radius=10,
            fill=THEME["shadow"],
            outline=None,
        )

        self.draw.rounded_rectangle(
            (x, y, x + w, y + h),
            radius=8,
            fill=bg_color,
            outline=border_color,
            width=2 if is_active else 1,
        )

        # 索引胶囊
        idx_bg = THEME["accent"] if is_active else (255, 255, 255, 20)
        self.draw.rounded_rectangle((x + 10, y + 10, x + 40, y + h - 10), radius=4, fill=idx_bg)

        idx_text = str(index)
        bbox = self.draw.textbbox((0, 0), idx_text, font=self.font_header)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        self.draw.text((x + 25 - tw / 2, y + h / 2 - th / 2 - 2), idx_text, font=self.font_header, fill=(255, 255, 255))

        # 标题
        title_color = THEME["text_main"] if is_active else (200, 200, 200)
        self.draw.text((x + 55, y + 8), title, font=self.font_text, fill=title_color)

        # 副标题
        self.draw.text((x + 55, y + 32), subtitle, font=self.font_small, fill=THEME["text_dim"])

        if is_active:
            self.draw.text((x + w - 80, y + h / 2 - 10), "ACTIVE", font=self.font_mono, fill=THEME["accent"])

    def draw_status_list_item(
        self,
        x,
        y,
        w,
        h,
        index,
        title,
        subtitle,
        status_text=None,
        status_color=None,
        is_highlight=False,
    ):
        """绘制带状态标签的列表项（用于仪表盘详情）。"""
        bg_color = (30, 40, 50, 105)
        border_color = THEME["panel_border"]

        if is_highlight:
            bg_color = (14, 165, 233, 50)
            border_color = THEME["primary"]

        self.draw.rounded_rectangle(
            (x + 2, y + 4, x + w + 2, y + h + 4),
            radius=10,
            fill=THEME["shadow"],
            outline=None,
        )

        self.draw.rounded_rectangle(
            (x, y, x + w, y + h),
            radius=8,
            fill=bg_color,
            outline=border_color,
            width=2 if is_highlight else 1,
        )

        idx_bg = (255, 255, 255, 20)
        self.draw.rounded_rectangle((x + 10, y + 10, x + 40, y + h - 10), radius=4, fill=idx_bg)

        idx_text = str(index)
        bbox = self.draw.textbbox((0, 0), idx_text, font=self.font_header)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        self.draw.text(
            (x + 25 - tw / 2, y + h / 2 - th / 2 - 2),
            idx_text,
            font=self.font_header,
            fill=(255, 255, 255),
        )

        self.draw.text((x + 55, y + 8), str(title or ""), font=self.font_text, fill=THEME["text_main"])
        self.draw.text((x + 55, y + 32), str(subtitle or ""), font=self.font_small, fill=THEME["text_dim"])

        if status_text:
            status_text = str(status_text)
            sc = status_color if status_color else THEME["text_main"]
            bbox = self.draw.textbbox((0, 0), status_text, font=self.font_mono)
            sw = bbox[2] - bbox[0]
            pill_w = sw + 26
            pill_h = 22
            px = x + w - pill_w - 12
            py = y + h / 2 - pill_h / 2
            self.draw.rounded_rectangle(
                (px, py, px + pill_w, py + pill_h),
                radius=pill_h / 2,
                fill=(255, 255, 255, 14),
                outline=THEME["panel_border"],
                width=1,
            )
            if sc:
                self.draw.ellipse((px + 7, py + pill_h / 2 - 3, px + 13, py + pill_h / 2 + 3), fill=(*sc, 220))
            self.draw.text((px + 16, py + 4), status_text, font=self.font_mono, fill=THEME["text_main"])
