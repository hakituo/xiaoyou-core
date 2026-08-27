# -*- coding: utf-8 -*-
"""天气查询工具（和风天气 QWeather）

P1-4: 新增天气查询工具，使用和风天气 API。
- 认证方式：Ed25519 JWT（私钥本地保管，公钥上传到控制台凭据）
- 免费订阅：1000 次/天，含实时+7天预报+空气质量+预警
- 文档：https://dev.qweather.com/docs/

工具列表：
- GetWeatherTool: 查询实时天气 + 可选预报（统一入口）
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type

import aiohttp
import jwt
from pydantic import BaseModel, Field

from config.settings_adapters import get_weather_settings
from core.tools.base import BaseTool
from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger("WEATHER_TOOL")


# ============================================================
# JWT 生成与缓存
# ============================================================

_jwt_cache: Dict[str, Any] = {"token": "", "exp": 0.0}
_jwt_lock = asyncio.Lock()


def _load_private_key_pem(private_key_path: str) -> bytes:
    """加载 Ed25519 私钥 PEM 文件。

    支持相对路径（基于项目根目录）和绝对路径。
    """
    p = Path(private_key_path)
    if not p.is_absolute():
        p = Path(get_project_root()) / p
    if not p.exists():
        raise FileNotFoundError(
            f"和风天气私钥文件不存在: {p}。"
            f"请检查 QWEATHER_PRIVATE_KEY_PATH 配置或 .env 中的 QWEATHER_PRIVATE_KEY_PATH。"
        )
    return p.read_bytes()


def _generate_jwt(token_ttl_minutes: int) -> Tuple[str, float]:
    """生成 Ed25519 签名的 JWT。

    返回 (token, exp_timestamp)。
    参考：https://dev.qweather.com/docs/configuration/authentication/
    - Header:  alg=EdDSA, kid=凭据ID
    - Payload: sub=项目ID, iat=签发时间, exp=过期时间
    """
    settings = get_weather_settings()
    if not settings.credential_id:
        raise ValueError(
            "QWEATHER_CREDENTIAL_ID 未配置，请在 .env 中设置凭据 ID"
        )
    if not settings.project_id:
        raise ValueError(
            "QWEATHER_PROJECT_ID 未配置，请在 .env 中设置项目 ID"
        )

    private_key_pem = _load_private_key_pem(settings.private_key_path)

    # iat 略提前 30 秒，避免客户端/服务端时钟偏差导致"未生效"
    now = int(time.time())
    iat = now - 30
    exp = now + token_ttl_minutes * 60
    payload = {
        "sub": settings.project_id,  # 项目 ID
        "iat": iat,
        "exp": exp,
    }
    # 和风天气要求 header 带 kid（凭据ID），用于服务端定位公钥
    headers = {"kid": settings.credential_id}
    # 和风天气 JWT 使用 EdDSA 算法（Ed25519）
    token = jwt.encode(
        payload, private_key_pem, algorithm="EdDSA", headers=headers
    )
    return token, float(exp)


async def _get_valid_jwt() -> str:
    """获取有效的 JWT，带缓存（提前 60 秒续期避免边界过期）。"""
    global _jwt_cache
    async with _jwt_lock:
        now = time.time()
        # 提前 60 秒续期
        if _jwt_cache["token"] and _jwt_cache["exp"] - now > 60:
            return _jwt_cache["token"]

        settings = get_weather_settings()
        token, exp = await asyncio.to_thread(
            _generate_jwt, settings.jwt_ttl_minutes
        )
        _jwt_cache["token"] = token
        _jwt_cache["exp"] = exp
        logger.debug(
            "[Weather] JWT 已生成，有效期至 %s",
            time.strftime("%H:%M:%S", time.localtime(exp)),
        )
        return token


# ============================================================
# 城市 ID 缓存（避免重复调用 GeoAPI 消耗额度）
# ============================================================

_location_id_cache: Dict[str, str] = {}
_location_id_lock = asyncio.Lock()


async def _lookup_location_id(location_query: str) -> Tuple[str, str]:
    """查询城市，返回 (location_id, display_name)。

    - 如果输入已经是 LocationID（纯数字）或坐标（含逗号），直接返回。
    - 否则调用 GeoAPI 城市搜索，带缓存。
    """
    query = location_query.strip()
    if not query:
        raise ValueError("城市名不能为空")

    # 已经是坐标（如 "116.41,39.92"）：直接使用
    if "," in query and all(
        part.strip().replace(".", "").replace("-", "").isdigit()
        for part in query.split(",", 1)
    ):
        return query.strip(), query.strip()

    # 已经是 LocationID（纯数字，如 "101010100"）：直接使用
    if query.isdigit() and len(query) >= 6:
        return query, query

    # 走城市搜索缓存
    async with _location_id_lock:
        if query in _location_id_cache:
            return _location_id_cache[query], query

    # 调用 GeoAPI
    settings = get_weather_settings()
    if not settings.api_host:
        raise ValueError("QWEATHER_API_HOST 未配置")

    token = await _get_valid_jwt()
    url = f"https://{settings.api_host}/geo/v2/city/lookup"
    params = {"location": query, "range": "cn", "number": 1, "lang": "zh"}
    headers = {"Authorization": f"Bearer {token}"}

    try:
        timeout = aiohttp.ClientTimeout(total=settings.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                data = await resp.json()
                if str(data.get("code", "")) != "200":
                    raise ValueError(
                        f"城市搜索失败: code={data.get('code')}, "
                        f"msg={data.get('msg', '')}"
                    )
                locations = data.get("location", []) or []
                if not locations:
                    raise ValueError(f"未找到城市: {query}")
                loc = locations[0]
                location_id = loc.get("id", "")
                # 拼接显示名（如 "北京, 北京市, 中国"）
                display = " ".join(
                    filter(
                        None,
                        [
                            loc.get("name", ""),
                            loc.get("adm2", ""),
                            loc.get("adm1", ""),
                            loc.get("country", ""),
                        ],
                    )
                )
                if not location_id:
                    raise ValueError(f"城市搜索返回空 ID: {query}")

                async with _location_id_lock:
                    _location_id_cache[query] = location_id
                logger.info(
                    "[Weather] 城市搜索: query=%s -> id=%s (%s)",
                    query,
                    location_id,
                    display,
                )
                return location_id, display or query
    except asyncio.TimeoutError:
        raise ValueError(f"城市搜索超时: {query}")
    except aiohttp.ClientError as e:
        raise ValueError(f"城市搜索网络错误: {e}")


# ============================================================
# HTTP 请求封装
# ============================================================


async def _qweather_get(path: str, params: Dict[str, str]) -> Dict[str, Any]:
    """统一的和风天气 GET 请求。

    path 形如 "/v7/weather/now" 或 "/v7/weather/3d"。
    """
    settings = get_weather_settings()
    if not settings.api_host:
        raise ValueError("QWEATHER_API_HOST 未配置")

    token = await _get_valid_jwt()
    url = f"https://{settings.api_host}{path}"
    params = {**params, "lang": "zh"}
    headers = {"Authorization": f"Bearer {token}"}

    timeout = aiohttp.ClientTimeout(total=settings.timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params, headers=headers) as resp:
            data = await resp.json()
            code = str(data.get("code", ""))
            if code != "200":
                raise ValueError(
                    f"和风天气 API 错误: path={path}, code={code}, "
                    f"msg={data.get('msg', '')}"
                )
            return data


# ============================================================
# 工具实现
# ============================================================


class GetWeatherInput(BaseModel):
    location: str = Field(
        description=(
            "查询城市。支持：城市名（如 '北京'、'上海'、'深圳'）、"
            "LocationID（如 '101010100'）、坐标（如 '116.41,39.92'）。"
        )
    )
    forecast_days: int = Field(
        default=0,
        description=(
            "预报天数。0=仅实时天气（默认），3=未来3天预报，7=未来7天预报。"
            "其他值会被自动规整为 0/3/7。"
        ),
    )


def _normalize_forecast_days(days: int) -> int:
    """规整预报天数到合法值 0/3/7。"""
    if days <= 0:
        return 0
    if days <= 3:
        return 3
    return 7


def _format_now(now: Dict[str, Any]) -> str:
    """格式化实时天气数据。"""
    parts = [
        f"实况（观测时间 {now.get('obsTime', '未知')}）",
        f"天气：{now.get('text', '未知')}",
        f"温度：{now.get('temp', '未知')}℃",
        f"体感：{now.get('feelsLike', '未知')}℃",
        f"风向风力：{now.get('windDir', '未知')} {now.get('windScale', '未知')}级"
        f"（{now.get('windSpeed', '未知')}km/h）",
        f"湿度：{now.get('humidity', '未知')}%",
        f"降水量：{now.get('precip', '未知')}mm",
        f"气压：{now.get('pressure', '未知')}hPa",
        f"能见度：{now.get('vis', '未知')}km",
        f"云量：{now.get('cloud', '未知')}%",
    ]
    return "\n".join(parts)


def _format_daily(daily: Dict[str, Any]) -> str:
    """格式化单日预报数据。"""
    return (
        f"{daily.get('fxDate', '未知')}: "
        f"白天 {daily.get('textDay', '未知')}，夜间 {daily.get('textNight', '未知')}，"
        f"{daily.get('tempMin', '未知')}~{daily.get('tempMax', '未知')}℃，"
        f"{daily.get('windDirDay', '未知')} {daily.get('windScaleDay', '未知')}级，"
        f"湿度 {daily.get('humidity', '未知')}%，降水 {daily.get('precip', '未知')}mm，"
        f"日出 {daily.get('sunrise', '未知')}，日落 {daily.get('sunset', '未知')}"
    )


class GetWeatherTool(BaseTool):
    name = "get_weather"
    description = (
        "查询指定城市的天气情况，支持实时天气和未来3/7天预报。"
        "数据源：和风天气 QWeather。"
        "示例：'北京'、'上海 3天预报'、'深圳 7天'。"
    )
    short_description = "查询城市天气（实时+预报）"
    category = "utility"
    args_schema: Type[BaseModel] = GetWeatherInput

    async def _run(self, location: str, forecast_days: int = 0) -> str:
        settings = get_weather_settings()
        # 兜底：如果用户没传 location，使用配置的默认城市
        if not location and settings.default_location:
            location = settings.default_location
        if not location:
            return (
                "Error: 请提供城市名。"
                "支持城市名（如 '北京'）、LocationID 或坐标（如 '116.41,39.92'）。"
            )

        days = _normalize_forecast_days(forecast_days)

        try:
            # 1. 解析城市
            location_id, display_name = await _lookup_location_id(location)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.warning(f"[Weather] 城市解析异常: {e}", exc_info=True)
            return f"Error: 城市解析失败: {e}"

        # 2. 并行拉取实况 + 预报（如果需要）
        try:
            now_data = await _qweather_get(
                "/v7/weather/now", {"location": location_id}
            )
            now_str = _format_now(now_data.get("now", {}))
        except Exception as e:
            logger.warning(f"[Weather] 实况查询失败: {e}", exc_info=True)
            return f"Error: 实况查询失败: {e}"

        result_lines = [f"【{display_name} 天气】", now_str]

        if days > 0:
            try:
                forecast_data = await _qweather_get(
                    f"/v7/weather/{days}d", {"location": location_id}
                )
                daily_list = forecast_data.get("daily", []) or []
                if daily_list:
                    result_lines.append(f"\n【未来{days}天预报】")
                    for d in daily_list:
                        result_lines.append(_format_daily(d))
            except Exception as e:
                logger.warning(f"[Weather] 预报查询失败: {e}", exc_info=True)
                result_lines.append(f"\n（预报查询失败: {e}）")

        return "\n".join(result_lines)
