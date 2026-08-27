"""工具发现元数据。

现有 ``BaseTool.category`` 继续承担人设权限控制；本模块只负责工具发现，
避免把权限边界、业务领域和 prompt 加载策略混在同一个字段里。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class ToolDiscoveryMetadata:
    """供工具检索和按需加载使用的稳定元数据。"""

    name: str
    domain: str
    tags: Tuple[str, ...]
    risk_level: str
    load_policy: str
    short_description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "tags": list(self.tags),
            "risk_level": self.risk_level,
            "load_policy": self.load_policy,
            "short_description": self.short_description,
        }


# 每个工具只归入一个发现领域；这里不改变工具原有 category，也不影响人设权限。
_DOMAIN_GROUPS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "core": {
        "tags": ("基础", "时间", "计算", "语音", "core"),
        "tools": ("get_current_time", "calculator", "text_to_speech"),
    },
    "information": {
        "tags": ("查询", "搜索", "互联网", "天气", "information"),
        "tools": ("web_search", "get_weather"),
    },
    "daily_record": {
        "tags": ("日常", "生活记录", "睡眠", "活动", "daily"),
        "tools": ("record_daily_activity", "get_daily_summary", "update_sleep_record"),
    },
    "journal": {
        "tags": ("日记", "总结", "月度", "journal"),
        "tools": ("write_diary", "read_diary", "read_daily_summary", "read_monthly_summary"),
    },
    "plan": {
        "tags": ("计划", "待办", "安排", "任务", "todo", "plan"),
        "tools": (
            "generate_tomorrow_plan", "generate_today_plan", "get_plan",
            "add_plan_item", "update_plan_item", "remove_plan_item",
            "mark_plan_item_status", "get_character_daily_plan",
        ),
    },
    "file": {
        "tags": ("文件", "数据", "创建", "导出", "学习资料", "file"),
        "tools": ("aveline_daily_data", "study_data_management", "create_file"),
    },
    "food": {
        "tags": ("食物", "吃饭", "投喂", "库存", "想吃", "food"),
        "tools": (
            "buy_food", "feed_food", "list_food", "show_inventory",
            "crave_food", "list_food_cravings", "get_aveline_meals",
        ),
    },
    "shop": {
        "tags": ("商城", "商品", "礼物", "购买", "库存", "shop"),
        "tools": ("browse_shop", "buy_shop_item", "show_gift_inventory", "use_gift_item"),
    },
    "study": {
        "tags": ("学习", "知识库", "单词", "专注", "学习模式", "study"),
        "tools": (
            "get_study_profile", "search_knowledge_base", "update_word_progress",
            "word_quiz", "get_current_focus_session", "get_focus_session_summary",
            "enter_study_mode", "exit_study_mode",
        ),
    },
    "reminder": {
        "tags": ("提醒", "闹钟", "定时", "reminder"),
        "tools": ("set_reminder",),
    },
    "user_status": {
        "tags": ("用户", "状态", "身体指标", "体重", "生病", "status"),
        "tools": ("record_body_metrics", "add_user_status", "remove_user_status", "get_user_status"),
    },
    "health": {
        "tags": ("健康", "手表", "心率", "步数", "睡眠", "health"),
        "tools": ("query_health_data",),
    },
    "memory_search": {
        "tags": ("记忆", "聊天历史", "人物档案", "回忆", "memory", "search"),
        "tools": ("search_memory", "search_chat_history", "query_person_profile"),
    },
    "memory_write": {
        "tags": ("记住", "偏好", "经验", "任务", "摘要", "memory", "record"),
        "tools": (
            "record_preference", "record_experience", "record_active_task",
            "complete_active_task", "record_summary",
        ),
    },
    "companion": {
        "tags": ("角色", "同伴", "仿生体", "状态", "companion"),
        "tools": ("check_peer_status", "get_bionic_state"),
    },
    "communication": {
        "tags": ("消息", "通知", "主人", "角色", "communication"),
        "tools": ("notify_master", "message_peer"),
    },
    "active_care": {
        "tags": ("主动关怀", "频率", "暂停", "定时消息", "active care"),
        "tools": (
            "adjust_active_care_frequency", "pause_active_care",
            "schedule_active_care_message", "toggle_active_care",
            "get_active_care_status",
        ),
    },
    "device_observe": {
        "tags": ("设备查看", "手机查询", "只读", "device observe"),
        "tools": (
            "check_running_processes", "look_at_screen", "capture_phone_screen",
            "get_device_location", "get_app_usage_time", "list_installed_apps",
            "list_paired_bluetooth_devices", "scan_bluetooth_devices",
        ),
    },
    "device_control": {
        "tags": ("设备控制", "手机控制", "device control"),
        "tools": (
            "force_stop_app", "start_app", "pair_bluetooth_device",
            "unpair_bluetooth_device", "set_wallpaper", "set_app_limit",
        ),
    },
    "playset": {
        "tags": ("玩法", "模式", "启用", "停用", "playset"),
        "tools": ("list_playsets", "enable_playset", "disable_playset"),
    },
    "tool_discovery": {
        "tags": ("工具", "能力", "查找工具", "搜索工具", "tool discovery"),
        "tools": ("search_tools",),
    },
}


_SHORT_DESCRIPTION_OVERRIDES = {
    "record_body_metrics": "记录用户体重、体脂等身体指标",
    "buy_food": "购买食物并加入食物库存",
    "feed_food": "从库存取出食物投喂角色",
    "list_food": "查看可购买的食物列表",
    "show_inventory": "查看当前食物库存",
    "crave_food": "记录角色当前想吃的食物",
    "list_food_cravings": "查看角色近期的食物渴望",
    "study_data_management": "读取或维护学习数据文件",
    "create_file": "创建并导出文档、表格或其他文件",
    "text_to_speech": "把文本转换成语音",
    "search_knowledge_base": "搜索本地学习知识库",
    "update_word_progress": "更新单词学习进度",
    "word_quiz": "发起或处理单词测验",
    "add_user_status": "新增一条持续性的用户状态",
    "remove_user_status": "移除一条用户状态",
    "get_user_status": "查看当前用户状态",
    "query_person_profile": "查询人物档案和关系信息",
}

# 领域标签负责粗召回；这里补充动作级别别名，避免同领域工具互相挤占排名。
_TOOL_TAG_OVERRIDES: Dict[str, Tuple[str, ...]] = {
    "get_current_time": ("现在几点", "日期", "时间"),
    "calculator": ("算一下", "数学计算", "表达式"),
    "text_to_speech": ("朗读", "语音合成", "念出来"),
    "web_search": ("联网搜索", "最新信息", "网上查"),
    "get_weather": ("天气预报", "气温", "下雨"),
    "record_daily_activity": ("记录活动", "吃饭记录", "起床记录"),
    "get_daily_summary": ("今天做了什么", "生活总结", "每日概览"),
    "update_sleep_record": ("修改睡眠", "起床时间", "睡觉时间"),
    "write_diary": ("写日记", "记录日记"),
    "read_diary": ("看日记", "读取日记"),
    "read_daily_summary": ("读取每日总结", "今日总结"),
    "read_monthly_summary": ("读取月度总结", "月总结"),
    "generate_today_plan": ("生成今日计划", "今天安排"),
    "generate_tomorrow_plan": ("生成明日计划", "明天安排"),
    "get_plan": ("查看计划", "待办列表"),
    "add_plan_item": ("新增待办", "添加计划"),
    "update_plan_item": ("修改待办", "更新计划"),
    "remove_plan_item": ("删除待办", "移除计划"),
    "mark_plan_item_status": ("完成待办", "任务完成", "跳过任务"),
    "get_character_daily_plan": ("角色今天做什么", "角色计划"),
    "aveline_daily_data": ("角色数据文件", "companion data"),
    "study_data_management": ("学习文件", "学习笔记", "学习数据"),
    "create_file": ("生成文件", "导出文档", "表格", "PDF"),
    "buy_food": ("买吃的", "购买食物"),
    "feed_food": ("投喂", "喂角色", "给她吃"),
    "list_food": ("食物菜单", "可买食物"),
    "show_inventory": ("食物库存", "还有什么吃的"),
    "crave_food": ("想吃", "嘴馋", "食物渴望"),
    "list_food_cravings": ("想吃什么", "食物愿望"),
    "get_aveline_meals": ("角色吃了什么", "用餐记录"),
    "browse_shop": ("逛商城", "商品列表"),
    "buy_shop_item": ("买礼物", "购买商品"),
    "show_gift_inventory": ("礼物库存", "有哪些礼物"),
    "use_gift_item": ("使用礼物", "送礼物"),
    "get_study_profile": ("学习画像", "掌握情况", "薄弱点"),
    "search_knowledge_base": ("查知识库", "知识点", "公式"),
    "update_word_progress": ("单词进度", "背单词", "词汇复习"),
    "word_quiz": ("单词测验", "词汇测试"),
    "get_current_focus_session": ("当前专注", "番茄钟状态"),
    "get_focus_session_summary": ("专注总结", "分心率"),
    "enter_study_mode": ("开始学习", "进入学习模式"),
    "exit_study_mode": ("结束学习", "退出学习模式"),
    "set_reminder": ("提醒我", "闹钟", "稍后叫我"),
    "record_body_metrics": ("记录体重", "体脂", "身体指标"),
    "add_user_status": ("新增状态", "生病", "忙碌"),
    "remove_user_status": ("状态恢复", "病好了", "删除状态"),
    "get_user_status": ("查看用户状态", "现在状态"),
    "query_health_data": ("心率", "步数", "手表健康", "睡眠数据"),
    "search_memory": ("回忆", "记得我", "以前的记忆"),
    "search_chat_history": ("聊天记录", "以前聊过", "之前说过", "对话历史"),
    "query_person_profile": ("人物档案", "他是谁", "她是谁"),
    "record_preference": ("记住偏好", "记住我以后", "我喜欢", "我不喜欢"),
    "record_experience": ("记录经验", "最佳实践"),
    "record_active_task": ("搁置任务", "以后继续"),
    "complete_active_task": ("长期任务完成", "结束活跃任务"),
    "record_summary": ("记录摘要", "重要节点"),
    "check_peer_status": ("另一个角色状态", "同伴在干嘛"),
    "get_bionic_state": ("角色饿不饿", "角色累不累", "仿生体状态"),
    "notify_master": ("通知主人", "给主人消息"),
    "message_peer": ("给另一个角色发消息", "角色互发消息"),
    "adjust_active_care_frequency": ("调整关怀频率", "少发消息", "多发消息"),
    "pause_active_care": ("暂停关怀", "稍后恢复关怀"),
    "schedule_active_care_message": ("定时关怀消息", "晚点发消息"),
    "toggle_active_care": ("开启关怀", "关闭关怀"),
    "get_active_care_status": ("查看关怀状态", "关怀配置"),
    "check_running_processes": ("电脑进程", "运行程序", "电脑在干嘛"),
    "look_at_screen": ("查看电脑屏幕", "电脑截图"),
    "capture_phone_screen": ("手机截图", "查看手机屏幕"),
    "get_device_location": ("手机定位", "当前位置", "经纬度"),
    "get_app_usage_time": ("应用使用时长", "屏幕时间"),
    "list_installed_apps": ("已安装应用", "手机应用列表"),
    "list_paired_bluetooth_devices": ("已配对蓝牙", "蓝牙设备列表"),
    "scan_bluetooth_devices": ("扫描蓝牙", "附近蓝牙"),
    "force_stop_app": ("强制停止应用", "关闭手机应用"),
    "start_app": ("打开手机应用", "启动应用"),
    "pair_bluetooth_device": ("配对蓝牙", "连接蓝牙"),
    "unpair_bluetooth_device": ("取消蓝牙配对", "断开蓝牙"),
    "set_wallpaper": ("更换壁纸", "设置桌面壁纸"),
    "set_app_limit": ("应用限额", "限制使用时长"),
    "list_playsets": ("玩法列表", "查看玩法"),
    "enable_playset": ("启用玩法", "开始玩法"),
    "disable_playset": ("停用玩法", "结束玩法"),
    "search_tools": ("查找工具", "发现能力", "缺少工具"),
}

_BASE_LOAD_TOOLS = {
    "search_tools", "get_current_time", "calculator", "text_to_speech", "web_search",
}
_HIDDEN_LOAD_TOOLS = {"list_playsets", "enable_playset", "disable_playset"}

_DEVICE_READ_TOOLS = set(_DOMAIN_GROUPS["device_observe"]["tools"])
_DEVICE_CONTROL_TOOLS = set(_DOMAIN_GROUPS["device_control"]["tools"])
_EXTERNAL_WRITE_TOOLS = {
    "notify_master", "message_peer", "set_reminder", "schedule_active_care_message",
}
_WRITE_TOOLS = {
    "record_daily_activity", "update_sleep_record", "write_diary",
    "generate_tomorrow_plan", "generate_today_plan", "add_plan_item",
    "update_plan_item", "remove_plan_item", "mark_plan_item_status",
    "aveline_daily_data", "study_data_management", "create_file",
    "buy_food", "feed_food", "crave_food", "buy_shop_item", "use_gift_item",
    "update_word_progress", "word_quiz", "enter_study_mode", "exit_study_mode",
    "record_body_metrics", "add_user_status", "remove_user_status",
    "record_preference", "record_experience", "record_active_task",
    "complete_active_task", "record_summary", "adjust_active_care_frequency",
    "pause_active_care", "toggle_active_care", "enable_playset", "disable_playset",
}


def _build_domain_index() -> Dict[str, Tuple[str, Tuple[str, ...]]]:
    index: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
    for domain, spec in _DOMAIN_GROUPS.items():
        for tool_name in spec["tools"]:
            if tool_name in index:
                raise ValueError(f"工具发现元数据重复归类: {tool_name}")
            index[tool_name] = (domain, spec["tags"])
    return index


_DOMAIN_INDEX = _build_domain_index()


def get_catalog_tool_names() -> Tuple[str, ...]:
    """返回元数据目录中全部工具名，供完整性验证使用。"""
    return tuple(_DOMAIN_INDEX)


def _resolve_risk_level(tool_name: str) -> str:
    if tool_name in _DEVICE_CONTROL_TOOLS:
        return "device_control"
    if tool_name in _DEVICE_READ_TOOLS:
        return "device_read"
    if tool_name in _EXTERNAL_WRITE_TOOLS:
        return "external_write"
    if tool_name in _WRITE_TOOLS:
        return "write"
    if tool_name in _HIDDEN_LOAD_TOOLS:
        return "sensitive"
    return "read"


def _resolve_load_policy(tool_name: str) -> str:
    if tool_name in _HIDDEN_LOAD_TOOLS:
        return "hidden"
    if tool_name in _BASE_LOAD_TOOLS:
        return "base"
    return "on_demand"


def _compact_description(tool: Any) -> str:
    raw = str(
        _SHORT_DESCRIPTION_OVERRIDES.get(tool.name)
        or getattr(tool, "short_description", "")
        or getattr(tool, "description", "")
        or tool.name
    ).strip()
    first_line = raw.splitlines()[0].strip()
    summary = re.split(r"[。.!?！？]", first_line, maxsplit=1)[0].strip()
    if len(summary) > 60:
        return summary[:57] + "..."
    return summary


def build_tool_metadata(tool: Any) -> Optional[ToolDiscoveryMetadata]:
    """把已注册工具转换为发现元数据；未入目录时返回 ``None``。"""
    entry = _DOMAIN_INDEX.get(str(tool.name))
    if entry is None:
        return None
    domain, domain_tags = entry
    tags = tuple(dict.fromkeys((*domain_tags, *_TOOL_TAG_OVERRIDES.get(str(tool.name), ()))))
    return ToolDiscoveryMetadata(
        name=str(tool.name),
        domain=domain,
        tags=tags,
        risk_level=_resolve_risk_level(str(tool.name)),
        load_policy=_resolve_load_policy(str(tool.name)),
        short_description=_compact_description(tool),
    )


def search_tool_metadata(
    metadata_items: Iterable[ToolDiscoveryMetadata],
    query: str,
    *,
    limit: int = 5,
) -> List[ToolDiscoveryMetadata]:
    """使用显式领域和标签做轻量检索，结果顺序稳定。"""
    normalized = str(query or "").strip().lower()
    if not normalized:
        return []
    english_terms = re.findall(r"[a-z0-9_]+", normalized)
    query_cjk_bigrams = {
        chunk[index:index + 2]
        for chunk in re.findall(r"[\u4e00-\u9fff]+", normalized)
        for index in range(max(0, len(chunk) - 1))
    }
    scored: List[Tuple[int, int, ToolDiscoveryMetadata]] = []
    for index, item in enumerate(metadata_items):
        if item.name == "search_tools":
            continue
        score = 0
        name = item.name.lower()
        description = item.short_description.lower()
        if normalized == name:
            score += 300
        if normalized in name or name in normalized:
            score += 120
        if normalized in description or description in normalized:
            score += 100
        for tag in item.tags:
            normalized_tag = tag.lower()
            if normalized_tag and normalized_tag in normalized:
                score += 45
        if item.domain.lower() in normalized:
            score += 55
        candidate_text = " ".join((description, *item.tags))
        candidate_cjk_bigrams = {
            chunk[index:index + 2]
            for chunk in re.findall(r"[\u4e00-\u9fff]+", candidate_text)
            for index in range(max(0, len(chunk) - 1))
        }
        score += 12 * len(query_cjk_bigrams & candidate_cjk_bigrams)
        for term in english_terms:
            if len(term) < 2:
                continue
            if term in name:
                score += 25
            if term in description:
                score += 15
            if any(term in tag.lower() for tag in item.tags):
                score += 10
        if score > 0:
            scored.append((score, -index, item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    bounded_limit = max(1, min(int(limit or 5), 8))
    return [row[2] for row in scored[:bounded_limit]]
