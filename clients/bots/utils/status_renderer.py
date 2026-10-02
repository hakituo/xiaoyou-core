"""状态图渲染器（薄壳门面）。

本模块原为单文件实现（约 1270 行），已按职责拆分为多个子模块以符合
单文件不超过 500 行的项目约定。此处仅做 re-export，保持外部导入路径
`from clients.bots.utils.status_renderer import ...` 完全兼容。

拆分结构：
- _theme.py              : 主题配置、颜色工具、字体加载
- _renderer.py           : SciFiRenderer 渲染器类
- _text_utils.py         : 文本/名称处理纯函数
- _generators_basic.py   : 状态/模型/人设/语音/帮助 图生成函数
- _generators_dashboard.py : 仪表盘概览/详情 图生成函数
"""

# 主题与工具
from ._theme import (
    THEME,
    _hex_to_rgb,
    _emotion_palette,
    _status_color,
    get_font,
)

# 渲染器类
from ._renderer import SciFiRenderer

# 文本工具
from ._text_utils import (
    _safe_text,
    _fmt_optional,
    _to_active_tokens,
    _display_name_only,
)

# 基础图生成函数
from ._generators_basic import (
    generate_status_image,
    generate_model_list_image,
    generate_persona_list_image,
    generate_voice_list_image,
    generate_help_image,
)

# 仪表盘图生成函数
from ._generators_dashboard import (
    generate_dashboard_overview_image,
    generate_dashboard_detail_image,
)

__all__ = [
    # 主题与工具
    "THEME",
    "_hex_to_rgb",
    "_emotion_palette",
    "_status_color",
    "get_font",
    # 渲染器
    "SciFiRenderer",
    # 文本工具
    "_safe_text",
    "_fmt_optional",
    "_to_active_tokens",
    "_display_name_only",
    # 基础图生成
    "generate_status_image",
    "generate_model_list_image",
    "generate_persona_list_image",
    "generate_voice_list_image",
    "generate_help_image",
    # 仪表盘图生成
    "generate_dashboard_overview_image",
    "generate_dashboard_detail_image",
]
