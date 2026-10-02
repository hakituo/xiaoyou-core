# 11 - 表现层：导航、主题与情绪色彩

## 导航系统 — NavGraph

### Routes（11条路由）

```
CHAT     = "chat"        — 聊天（主页）
CIRCLE   = "circle"      — 社交圈子
STATUS   = "status"      — AI 生命状态
DAILY    = "daily"       — 每日健康数据
MEMORY   = "memory"      — 记忆管理
STUDY    = "study"       — 学习模块
PERSONA  = "persona"     — 人格管理
SHOP     = "shop"        — 商店
PLUGINS  = "plugins"     — 插件/模型设置
TOOLS    = "tools"       — 工具集
SETTINGS = "settings"    — 应用设置
```

### Chat 路由特殊设计

```
route = "chat?text={text}"  — 可选参数，支持 deep link 预填文字
deepLinks: aveline://chat 和 aveline://chat?text={text}
```

### 动画配置

所有路由切换使用 **fadeIn/fadeOut**，300ms 过渡。

### 导航扩展函数

```
NavHostController.navigateTo(route)     — launchSingleTop + restoreState
NavHostController.navigateToChatWithText(text) — 编码后导航到 chat
```

## 主题系统 — Theme / Color / Typography

### AvelineTheme

- 动态配色（Material3）
- 透明 Surface 适配呼吸背景

### 色彩常量

```
TextPrimary: Color(0xFFF5F5F2)
TextSecondary: Color(0xFFA2A2A8)
Background: Color(0xFF020617)
CardBackground: Color(0xFF0F172A)
```

## EmotionColorMapping — 情绪色彩映射

### 9种情绪状态

| EmotionState | 主色 | 色彩方案（4色） |
|-------------|------|----------------|
| NEUTRAL | Grey | #6B7280 / #A5ADC1 / #1C1F24 / #4B5563 |
| HAPPY | Gold | #F2CE77 / #FFE8B2 / #3A2E13 / #D3A74F |
| SHY | Pink | #F3B8C8 / #FFD8E3 / #3F1B29 / #E58AA7 |
| ANGRY | Red | #E86A73 / #FFC1C4 / #3D0E14 / #C1444E |
| JEALOUS | Purple | #A58AF8 / #D3C6FF / #2C2453 / #7E6AD9 |
| WRONGED | Blue | #8CB2FF / #CDE0FF / #1B2A4C / #5B8AE0 |
| COQUETRY | Pink | #F6A4C6 / #FFD6EC / #381C2C / #CF6D9A |
| LOST | Muted Grey | #A3A3AD / #D8D8E2 / #18181B / #6E6E78 |
| EXCITED | Teal | #5EE3C0 / #C6FFF0 / #0D2E25 / #2FB395 |

### 设计原则

- 每种情绪**严格4色**，与 Web 前端完全一致（HEX 精确匹配）
- `EmotionState.fromString()` 使用 lowercase 匹配，未知情绪 fallback → NEUTRAL
- 颜色方案包含明亮色（光斑中心）+ 暗色（背景融合）+ 过渡色

### EmotionResolver（工具类）

`presentation/utils/EmotionResolver.kt` — 辅助解析情绪字符串到 EmotionState 和对应颜色。
