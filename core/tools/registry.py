import json
from typing import Any, Dict, List, Optional, Set, Tuple

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

from .base import BaseTool
from .tool_metadata import (
    ToolDiscoveryMetadata,
    build_tool_metadata,
    search_tool_metadata,
)

logger = get_logger("TOOL_REGISTRY")


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        # Per-tool runtime enable/disable (overrides enabled_by_default)
        self._disabled: Set[str] = set()
        # OpenAI 工具 schema 缓存：schema 是静态的，注册后构建一次并复用，
        # 既避免每次请求重复构建，也保证 tools 参数内容字节级稳定（参与缓存键匹配）
        self._openai_tools_all_cache: Optional[List[Dict[str, Any]]] = None
        self._openai_tools_by_names_cache: Dict[Tuple[frozenset, frozenset], List[Dict[str, Any]]] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool
        self._invalidate_openai_tools_cache()

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def enable_tool(self, name: str) -> bool:
        """Re-enable a previously disabled tool."""
        if name in self._tools:
            self._disabled.discard(name)
            self._invalidate_openai_tools_cache()
            return True
        return False

    def disable_tool(self, name: str) -> bool:
        """Disable a tool at runtime (won't appear in prompts or be callable)."""
        if name in self._tools:
            self._disabled.add(name)
            self._invalidate_openai_tools_cache()
            return True
        return False

    def _invalidate_openai_tools_cache(self):
        """工具集合变化时清空 schema 缓存，保证与当前启用状态一致"""
        self._openai_tools_all_cache = None
        self._openai_tools_by_names_cache = {}

    def is_enabled(self, name: str) -> bool:
        """Check if a tool is currently enabled."""
        if name not in self._tools:
            return False
        return name not in self._disabled and self._tools[name].enabled_by_default

    def get_active_tools(self) -> List[str]:
        """Return currently enabled tool names."""
        return [name for name in self._tools if self.is_enabled(name)]

    def get_tools_by_category(self, category: str) -> List[BaseTool]:
        """Return enabled tools belonging to a category."""
        return [
            t for name, t in self._tools.items()
            if self.is_enabled(name) and t.category == category
        ]

    def get_tool_metadata(self, name: str) -> Optional[ToolDiscoveryMetadata]:
        """返回工具发现元数据，不改变原有 category 权限语义。"""
        tool = self.get_tool(name)
        return build_tool_metadata(tool) if tool is not None else None

    def list_tool_metadata(
        self,
        include_names: Optional[List[str]] = None,
    ) -> List[ToolDiscoveryMetadata]:
        """按注册顺序列出启用工具的发现元数据。"""
        allowed = set(include_names) if include_names is not None else None
        items: List[ToolDiscoveryMetadata] = []
        for name, tool in self._tools.items():
            if not self.is_enabled(name):
                continue
            if allowed is not None and name not in allowed:
                continue
            metadata = build_tool_metadata(tool)
            if metadata is not None:
                items.append(metadata)
        return items

    def search_tools(
        self,
        query: str,
        *,
        include_names: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[ToolDiscoveryMetadata]:
        """只在指定可见工具集合内检索候选能力。"""
        return search_tool_metadata(
            self.list_tool_metadata(include_names=include_names),
            query,
            limit=limit,
        )

    def get_tools_description(self, include_names: List[str] = None) -> str:
        """
        Returns a formatted string describing available tools.
        If include_names is provided, only tools with those names are included.
        Uses short_description when available to reduce token usage.
        """
        descriptions = []
        for name, tool in self._tools.items():
            if not self.is_enabled(name):
                continue
            if include_names is not None and name not in include_names:
                continue

            desc_text = tool.short_description or tool.description
            args_simple = {}
            if tool.args_schema:
                if hasattr(tool.args_schema, "model_json_schema"):
                    schema = tool.args_schema.model_json_schema()
                else:
                    schema = tool.args_schema.schema()
                props = schema.get("properties", {})
                required = schema.get("required", [])

                for prop_name, prop_info in props.items():
                    desc = prop_info.get("description", "")
                    typ = prop_info.get("type", "any")
                    is_req = "*" if prop_name in required else ""
                    args_simple[f"{prop_name}{is_req}"] = f"{typ} - {desc}"

            args_desc = json.dumps(args_simple, ensure_ascii=False)
            descriptions.append(
                f"- {name}: {desc_text} | Args: {args_desc}"
            )
        return "\n".join(descriptions)

    def get_concise_tool_prompt(self, include_categories: List[str] = None, exclude_categories: List[str] = None, include_names: List[str] = None) -> str:
        """
        Generate a very concise tool list for prompt injection.
        Only includes tool name + short hint, minimal tokens.
        Optionally filter by category or by tool name list.
        """
        lines = []
        for name, tool in self._tools.items():
            if not self.is_enabled(name):
                continue
            if include_names is not None and name not in include_names:
                continue
            if include_categories and tool.category not in include_categories:
                continue
            if exclude_categories and tool.category in exclude_categories:
                continue
            metadata = self.get_tool_metadata(name)
            hint = (
                metadata.short_description
                if metadata is not None
                else tool.short_description or tool.description.split("。")[0].split(".")[0]
            )
            # Truncate hint to ~40 chars
            if len(hint) > 60:
                hint = hint[:57] + "..."
            lines.append(f"- {name}: {hint}")
        if not lines:
            return ""
        return (
            "【可用工具】\n"
            + "\n".join(lines)
            + "\n【工具调用规则】\n"
            + "- 工具由系统原生函数调用机制执行，需要时直接发起调用即可。\n"
            + "- 给用户的回复只包含自然语言，不要把工具相关的任何内容写进回复里。\n"
            + "- 工具执行完成后，再根据结果用自然语言回复用户。"
        )

    def get_openai_tools(self, include_names: List[str] = None, exclude_categories: List[str] = None) -> List[Dict[str, Any]]:
        """
        Convert tools to OpenAI Function Calling format for DeepSeek v4 native tools.
        Returns list of tool definitions for the 'tools' API parameter.

        【缓存优化】schema 构建结果按工具集合缓存复用：
        - 保证 tools 参数内容字节级稳定（tools 参与 API 缓存键匹配，不稳定会整段 miss）
        - 避免每次请求重复构建 pydantic schema
        """
        if include_names is not None:
            # 缓存键同时包含工具集合与排除类目，避免不同 exclude_categories 命中同一份缓存
            key = (frozenset(include_names), frozenset(exclude_categories or ()))
            cached = self._openai_tools_by_names_cache.get(key)
            if cached is not None:
                return list(cached)
            tools = self._build_openai_tools_schema(
                include_names=include_names, exclude_categories=exclude_categories
            )
            self._openai_tools_by_names_cache[key] = tools
            return list(tools)

        if exclude_categories is not None:
            # 排除类目场景调用少，直接构建不缓存
            return self._build_openai_tools_schema(exclude_categories=exclude_categories)

        if self._openai_tools_all_cache is not None:
            return list(self._openai_tools_all_cache)
        tools = self._build_openai_tools_schema()
        self._openai_tools_all_cache = tools
        return list(tools)

    def _build_openai_tools_schema(
        self,
        include_names: List[str] = None,
        exclude_categories: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """构建 OpenAI Function Calling 格式的工具 schema 列表（不缓存，供缓存层调用）"""
        tools = []
        for name, tool in self._tools.items():
            if not self.is_enabled(name):
                continue
            if include_names is not None and name not in include_names:
                continue
            if exclude_categories and tool.category in exclude_categories:
                continue

            # Build function schema from Pydantic model
            parameters = {"type": "object", "properties": {}, "required": []}
            if tool.args_schema:
                if hasattr(tool.args_schema, "model_json_schema"):
                    schema = tool.args_schema.model_json_schema()
                else:
                    schema = tool.args_schema.schema()

                parameters["properties"] = schema.get("properties", {})
                parameters["required"] = schema.get("required", [])
                # OpenAI requires additionalProperties: false for strict mode
                parameters["additionalProperties"] = False

            tool_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": parameters,
                }
            }
            tools.append(tool_def)

        return tools


def register_all_tools(registry: ToolRegistry):
    """注册所有工具到注册表，统一入口"""

    # === 工具发现入口（常驻的小 schema，用于按需加载其余工具）===
    try:
        from core.tools.tool_search_tool import SearchToolsTool
        registry.register(SearchToolsTool())
    except ImportError as e:
        logger.warning("[register] 工具发现入口 import 失败: %s", e)

    # === 基础工具 ===
    try:
        from core.tools.implementations import WebSearchTool, TimeTool, CalculatorTool
        registry.register(WebSearchTool())
        registry.register(TimeTool())
        registry.register(CalculatorTool())
    except ImportError as e:
        logger.warning("[register] 基础工具 import 失败: %s", e)

    # === 天气查询工具（和风天气 QWeather）===
    try:
        from core.tools.weather_tool import GetWeatherTool
        registry.register(GetWeatherTool())
    except ImportError as e:
        logger.warning("[register] 天气工具 import 失败: %s", e)

    # === 日常记录工具 ===
    try:
        from core.tools.daily_tool import (
            RecordActivityTool,
            GetDailySummaryTool,
            UpdateSleepRecordTool,
        )
        registry.register(RecordActivityTool())
        registry.register(GetDailySummaryTool())
        registry.register(UpdateSleepRecordTool())
    except ImportError as e:
        logger.warning("[register] 日常记录工具 import 失败: %s", e)

    # === 日记工具 ===
    try:
        from core.tools.diary_tool import (
            WriteDiaryTool,
            ReadDiaryTool,
            ReadDailySummaryTool,
            ReadMonthlySummaryTool,
        )
        registry.register(WriteDiaryTool())
        registry.register(ReadDiaryTool())
        registry.register(ReadDailySummaryTool())
        registry.register(ReadMonthlySummaryTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 学习生活计划工具 ===
    try:
        from core.tools.plan_tool import (
            GenerateTomorrowPlanTool,
            GenerateTodayPlanTool,
            GetPlanTool,
            AddPlanItemTool,
            UpdatePlanItemTool,
            RemovePlanItemTool,
            MarkPlanItemStatusTool,
        )
        registry.register(GenerateTomorrowPlanTool())
        registry.register(GenerateTodayPlanTool())
        registry.register(GetPlanTool())
        registry.register(AddPlanItemTool())
        registry.register(UpdatePlanItemTool())
        registry.register(RemovePlanItemTool())
        registry.register(MarkPlanItemStatusTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 生理数据工具 ===
    try:
        from core.tools.physiology_tool import RecordBodyMetricsTool
        registry.register(RecordBodyMetricsTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 食物工具 ===
    try:
        from core.tools.food_tool import (
            BuyFoodTool, FeedFoodTool, ListFoodTool,
            ShowInventoryTool, GetAvelineMealsTool,
            CraveFoodTool, ListCravingsTool,
        )
        registry.register(BuyFoodTool())
        registry.register(FeedFoodTool())
        registry.register(ListFoodTool())
        registry.register(ShowInventoryTool())
        registry.register(GetAvelineMealsTool())
        registry.register(CraveFoodTool())
        registry.register(ListCravingsTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 商城工具（礼物/科技/奢侈品等非食物商品） ===
    try:
        from core.tools.shop_tool import (
            BrowseShopTool, BuyShopItemTool,
            ShowGiftInventoryTool, UseGiftItemTool,
        )
        registry.register(BrowseShopTool())
        registry.register(BuyShopItemTool())
        registry.register(ShowGiftInventoryTool())
        registry.register(UseGiftItemTool())
    except ImportError as e:
        logger.warning("[register] 商城工具 import 失败: %s", e)

    # === Aveline 每日数据工具 ===
    try:
        from core.tools.aveline_daily_data_tool import AvelineDailyDataTool
        registry.register(AvelineDailyDataTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 学习数据工具 ===
    try:
        from core.tools.study_data_tool import StudyDataTool
        registry.register(StudyDataTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 学习画像工具 ===
    try:
        from core.tools.study_profile_tool import GetStudyProfileTool
        registry.register(GetStudyProfileTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 学习工具集 ===
    try:
        from core.tools.study_tools import register_study_tools
        register_study_tools(registry)
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 提醒工具 ===
    try:
        from core.tools.reminder_tool import ReminderTool
        registry.register(ReminderTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 状态工具 ===
    try:
        from core.tools.status_tool import AddStatusTool, RemoveStatusTool, GetStatusTool
        registry.register(AddStatusTool())
        registry.register(RemoveStatusTool())
        registry.register(GetStatusTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 主动关怀工具 ===
    try:
        from core.tools.active_care_tool import (
            AdjustActiveCareFrequencyTool, PauseActiveCareTool,
            ScheduleCareMessageTool, ToggleActiveCareTool, GetActiveCareStatusTool,
        )
        registry.register(AdjustActiveCareFrequencyTool())
        registry.register(PauseActiveCareTool())
        registry.register(ScheduleCareMessageTool())
        registry.register(ToggleActiveCareTool())
        registry.register(GetActiveCareStatusTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 记忆搜索工具 ===
    try:
        from core.tools.search_memory_tool import SearchMemoryTool
        registry.register(SearchMemoryTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 聊天历史搜索工具 ===
    try:
        from core.tools.search_chat_history_tool import SearchChatHistoryTool
        registry.register(SearchChatHistoryTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 查看对方角色状态工具 ===
    try:
        from core.tools.check_peer_status_tool import CheckPeerStatusTool
        registry.register(CheckPeerStatusTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 角色日常计划查看工具 ===
    try:
        from core.tools.character_daily_plan_tool import GetCharacterDailyPlanTool
        registry.register(GetCharacterDailyPlanTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 玩法模块管理工具（仅 love 人设可见） ===
    try:
        from core.tools.playset_tool import (
            ListPlaysetsTool, EnablePlaysetTool, DisablePlaysetTool,
        )
        registry.register(ListPlaysetsTool())
        registry.register(EnablePlaysetTool())
        registry.register(DisablePlaysetTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 专注番茄钟只读查询工具（不含任何画面数据）===
    try:
        from core.tools.focus_session_tool import (
            GetCurrentFocusSessionTool,
            GetFocusSessionSummaryTool,
        )
        registry.register(GetCurrentFocusSessionTool())
        registry.register(GetFocusSessionSummaryTool())
    except ImportError as e:
        logger.warning("[register] 专注番茄钟查询工具 import 失败: %s", e)

    # === 学习模式工具 ===
    try:
        from core.tools.study_mode_tool import (
            EnterStudyModeTool, ExitStudyModeTool,
        )
        registry.register(EnterStudyModeTool())
        registry.register(ExitStudyModeTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 系统进程查看工具 ===
    try:
        from core.tools.process_tool import ProcessCheckTool
        registry.register(ProcessCheckTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 屏幕截图分析工具（仅 Master，截图+视觉模型分析）===
    try:
        from core.tools.screen_capture_tool import ScreenCaptureTool
        registry.register(ScreenCaptureTool())
    except ImportError as e:
        logger.warning("[register] 屏幕截图工具 import 失败: %s", e)

    # === 设备控制工具集（仅 Master，指令下发到手机前端执行）===
    try:
        from core.tools.device.force_stop_app import ForceStopAppTool
        from core.tools.device.list_installed_apps import ListInstalledAppsTool
        from core.tools.device.start_app import StartAppTool
        from core.tools.device.get_app_usage_time import GetAppUsageTimeTool
        from core.tools.device.capture_screen import CaptureScreenTool
        from core.tools.device.get_device_location import GetDeviceLocationTool
        from core.tools.device.bluetooth import (
            ListPairedBluetoothDevicesTool,
            ScanBluetoothDevicesTool,
            PairBluetoothDeviceTool,
            UnpairBluetoothDeviceTool,
        )
        from core.tools.device.set_wallpaper import SetWallpaperTool
        from core.tools.device.set_app_limit import SetAppLimitTool
        registry.register(ForceStopAppTool())
        registry.register(ListInstalledAppsTool())
        registry.register(StartAppTool())
        registry.register(GetAppUsageTimeTool())
        registry.register(CaptureScreenTool())
        registry.register(GetDeviceLocationTool())
        registry.register(ListPairedBluetoothDevicesTool())
        registry.register(ScanBluetoothDevicesTool())
        registry.register(PairBluetoothDeviceTool())
        registry.register(UnpairBluetoothDeviceTool())
        registry.register(SetWallpaperTool())
        registry.register(SetAppLimitTool())
    except ImportError as e:
        logger.warning("[register] 设备控制工具 import 失败: %s", e)

    # === 通知主人工具 ===
    try:
        from core.tools.notify_master_tool import NotifyMasterTool
        registry.register(NotifyMasterTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 给对方角色发消息工具 ===
    try:
        from core.tools.message_peer_tool import MessagePeerTool
        registry.register(MessagePeerTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 仿生体状态查询工具 ===
    try:
        from core.tools.bionic_state_tool import BionicStateTool
        registry.register(BionicStateTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 手表健康数据查询工具 ===
    try:
        from core.tools.health_data_tool import HealthDataTool
        registry.register(HealthDataTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 人物档案查询工具 ===
    try:
        from core.tools.person_profile_tool import QueryPersonProfileTool
        registry.register(QueryPersonProfileTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    # === 核心记忆写入工具（MEMORY.md 各分区）===
    try:
        from core.tools.record_memory_tool import (
            RecordPreferenceTool,
            RecordExperienceTool,
            RecordActiveTaskTool,
            CompleteActiveTaskTool,
            RecordSummaryTool,
        )
        registry.register(RecordPreferenceTool())
        registry.register(RecordExperienceTool())
        registry.register(RecordActiveTaskTool())
        registry.register(CompleteActiveTaskTool())
        registry.register(RecordSummaryTool())
    except ImportError as e:
        logger.warning("[register] 工具 import 失败: %s", e)

    if is_debug_enabled("tool_registry"):
        logger.info(
            "[register] 工具注册完成，共 %d 个工具，活跃 %d 个",
            len(registry.list_tools()),
            len(registry.get_active_tools()),
        )
        names = sorted(t.name for t in registry.list_tools())
        logger.debug("[register] 已注册工具清单: %s", ", ".join(names))
