"""
Debug 日志开关配置
集中管理各模块的 debug 级别日志开关，方便按需开启/关闭
所有开关默认关闭（False），需要调试时通过环境变量或 YAML 开启
环境变量前缀: XIAOYOU_DEBUG__
例如: XIAOYOU_DEBUG__AUTO_EAT=true 开启自动进食的 debug 日志
"""

from __future__ import annotations

from config._base import BaseSettings, Field, SettingsConfigDict


class DebugSettings(BaseSettings):
    """Debug 日志开关配置"""

    # ── 生命模拟 ──
    auto_eat: bool = Field(
        default=False,
        description="自动进食模块 debug 日志（进食检查、冷却状态、LLM选食过程）",
    )
    life_simulation: bool = Field(
        default=False,
        description="生命模拟核心 debug 日志（状态保存、情绪影响、每日总结、仪式触发）",
    )
    life_stats: bool = Field(
        default=False,
        description="生命统计数据 debug 日志（CPP调度器加载、皮质醇调整）",
    )

    # ── 主动关怀 ──
    active_care: bool = Field(
        default=False,
        description="主动关怀模块 debug 日志（私聊模式检测、心跳检查、上下文分析、晚安检测）",
    )
    active_care_decision: bool = Field(
        default=False,
        description="主动关怀决策 debug 日志（Bandit探索、JITAI启发式、LLM推荐、分数利用）",
    )
    active_care_executor: bool = Field(
        default=False,
        description="主动关怀执行器 debug 日志（QQ适配器查询、模型配置、睡眠检测、scope同步）",
    )
    active_care_ws: bool = Field(
        default=False,
        description=(
            "WebSocket 聊天处理中『实时晚安/唤醒检测』调试日志：把意图识别结果、"
            "睡眠模式激活/退出过程写入 logs/active_care_debug.log。"
            "该日志不受普通 logger 控制、会持续落盘，生产环境默认关闭；"
            "开启后才写文件，避免长期堆积（当前文件已 7MB+）。"
        ),
    )
    peer_chat: bool = Field(
        default=False,
        description="互聊系统 debug 日志（调度心跳、用户活跃标记、活跃时间戳持久化）",
    )
    peer_script: bool = Field(
        default=False,
        description="互聊剧本 debug 日志（聊天记录获取、剧本延迟、日记写入、社交事件注册）",
    )

    # ── 对话流 ──
    streaming: bool = Field(
        default=False,
        description="流式输出 debug 日志（Web搜索判断、think标签清理、tool call处理）",
    )
    context_budget: bool = Field(
        default=False,
        description="上下文预算 debug 日志（最近学习上下文检查）",
    )
    context_gathering: bool = Field(
        default=False,
        description="上下文收集 debug 日志（最后对话时间获取）",
    )

    # ── 自愈系统 ──
    auto_heal: bool = Field(
        default=False,
        description="自愈服务 debug 日志（配置读取、回调注销、错误处理、补丁通知、历史记录）",
    )

    # ── 元认知 ──
    metacognition: bool = Field(
        default=False,
        description="元认知系统 debug 日志（策略选择、注入记录）",
    )

    # ── 自我改进 ──
    core_memory: bool = Field(
        default=False,
        description="核心记忆 debug 日志（NOT-to-save条目跳过）",
    )

    # ── 数据路径 ──
    data_paths: bool = Field(
        default=False,
        description="数据路径 debug 日志（目录删除、scope解析、JSON解析、路径获取）",
    )

    # ── 搜索工具 ──
    search_history: bool = Field(
        default=False,
        description="聊天历史搜索 debug 日志（scope目录获取、记忆摘要回退搜索）",
    )

    # ── 对话示例 ──
    dialogue_examples: bool = Field(
        default=False,
        description="对话示例 debug 日志（BERT匹配失败）",
    )

    # ── 工具注册 ──
    tool_registry: bool = Field(
        default=False,
        description="工具注册 debug 日志（每个工具 import/注册结果、失败原因）",
    )

    # ── Aveline 流式编排 ──
    aveline_stream: bool = Field(
        default=False,
        description="Aveline流式编排 debug 日志（用户缓存更新）",
    )

    # ── 核心引擎 ──
    model_manager: bool = Field(
        default=False,
        description=(
            "模型管理器 debug 日志（云端模型候选、去重与注册摘要；"
            "不输出 API Key）"
        ),
    )

    # ── 日志调试开关（原 logging 节的调试项，统一迁入） ──
    log_full_prompt: bool = Field(
        default=False,
        description="是否在后端日志中输出完整的注入prompt（调试用，生产环境建议关闭）",
    )
    api_call_log: bool = Field(
        default=False,
        description="是否记录每次 LLM API 调用到 logs/api_calls_simple.log（调试用，生产环境建议关闭）",
    )
    server_debug: bool = Field(
        default=False,
        description=(
            "桌面端（pywebview）server 进程调试日志：开启后把 FastAPI server 启动/"
            "模块导入日志写入 logs/server_debug.log。默认关闭，避免无条件落盘堆积。"
        ),
    )

    # ── WebSocket 握手诊断 ──
    websocket_handshake: bool = Field(
        default=False,
        description=(
            "WebSocket 握手诊断日志：在依赖解析、适配器初始化、host/token 校验等"
            "关键节点输出详细 debug 信息到 logs/ws_handshake_debug.log，"
            "用于定位移动端连接 403/握手失败问题。生产环境默认关闭。"
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_DEBUG__",
        env_nested_delimiter="__",
        extra="allow",
    )


# 全局单例
_debug_settings: DebugSettings | None = None


def get_debug_settings() -> DebugSettings:
    """获取 debug 配置单例（优先从 AppSettings.debug 读取，确保 YAML 覆盖生效）"""
    global _debug_settings
    if _debug_settings is None:
        try:
            from config.integrated_config import get_settings
            app_debug = get_settings().debug
            if isinstance(app_debug, DebugSettings):
                _debug_settings = app_debug
                return _debug_settings
        except Exception:
            pass
        _debug_settings = DebugSettings()
    return _debug_settings


def is_debug_enabled(module: str) -> bool:
    """
    快速查询某模块的 debug 日志是否开启

    Args:
        module: 模块名，对应 DebugSettings 中的字段名

    Returns:
        bool: 是否开启
    """
    settings = get_debug_settings()
    return getattr(settings, module, False)
