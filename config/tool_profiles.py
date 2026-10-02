"""角色工具配置读取；按文件版本缓存，修改配置后下一轮生效。"""

from functools import lru_cache
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("tool_profiles.json")


@lru_cache(maxsize=1)
def _read_profiles(path: str, mtime_ns: int, size: int) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("tool_profiles.json 必须使用version=1的对象格式")
    if not isinstance(data.get("defaults"), dict):
        raise ValueError("工具配置缺少defaults")
    for group in ("roles", "modes"):
        if not isinstance(data.get(group, {}), dict):
            raise ValueError(f"{group}必须为对象")
    for entry in [data["defaults"], *data.get("roles", {}).values(), *data.get("modes", {}).values()]:
        if not isinstance(entry, dict):
            raise ValueError("每个角色/模式工具配置必须为对象")
        for key in ("resident", "on_demand", "disabled"):
            if key in entry and (not isinstance(entry[key], list) or any(not isinstance(item, str) or not item.strip() for item in entry[key])):
                raise ValueError(f"{key}必须为非空字符串列表")
    if not isinstance(data.get("routes"), list):
        raise ValueError("routes必须为列表")
    for route in data["routes"]:
        if not isinstance(route, dict) or any(not isinstance(route.get(key), list) or not route[key] or any(not isinstance(item, str) or not item for item in route[key]) for key in ("keywords", "tools")):
            raise ValueError("每条路由必须包含非空keywords和tools列表")
    return data


def get_tool_profiles() -> dict:
    """配置损坏时明确报错，不静默退回全量工具。调用方不得修改返回值。"""
    stat = CONFIG_PATH.stat()
    return _read_profiles(str(CONFIG_PATH), stat.st_mtime_ns, stat.st_size)
