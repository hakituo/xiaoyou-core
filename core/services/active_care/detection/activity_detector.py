"""
用户进程活动检测器
通过扫描前台进程判断用户当前正在做什么，为 Active Care 决策提供活动状态信息。

功能：
1. 检测用户当前活动类型（idle/working/studying/gaming/entertainment/communication）
2. 识别具体应用和窗口标题（Windows 平台）
3. 提供活动忙碌程度评分，用于 Active Care 门控决策

平台支持：
- Windows: 使用 psutil + ctypes 获取前台窗口标题
- Linux: 使用 psutil 扫描进程（无窗口标题）
- macOS: 使用 psutil 扫描进程（无窗口标题）
"""
import time
import platform
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from core.utils.logger import get_module_logger
from core.services.active_care.detection.activity_maps import (
    UserActivityCategory,
    is_system_process,
    classify_by_process_name,
    classify_by_window_title,
    extract_relevant_keyword,
)

logger = get_module_logger("ACTIVE_CARE_ACTIVITY", "active_care_activity.log")


@dataclass
class ActivityDetectionResult:
    """活动检测结果"""
    category: UserActivityCategory = UserActivityCategory.UNKNOWN
    process_name: str = ""
    window_title: str = ""
    display_name: str = ""          # 用户友好的显示名称
    is_busy: bool = False           # 是否处于忙碌状态（不适合打扰）
    busy_level: float = 0.0         # 忙碌程度 (0.0~1.0)，越高越不应该打扰
    confidence: float = 0.0         # 检测置信度 (0.0~1.0)
    timestamp: float = 0.0
    extra_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，方便序列化和日志"""
        return {
            "category": self.category.value if isinstance(self.category, UserActivityCategory) else str(self.category),
            "process_name": self.process_name,
            "window_title": self.window_title[:80] if self.window_title else "",
            "display_name": self.display_name,
            "is_busy": self.is_busy,
            "busy_level": round(self.busy_level, 2),
            "confidence": round(self.confidence, 2),
            "timestamp": self.timestamp,
        }


# 各活动类别的默认忙碌程度
CATEGORY_BUSY_LEVEL: Dict[UserActivityCategory, float] = {
    UserActivityCategory.IDLE: 0.0,
    UserActivityCategory.BROWSING: 0.15,
    UserActivityCategory.ENTERTAINMENT: 0.25,
    UserActivityCategory.COMMUNICATION: 0.35,
    UserActivityCategory.UNKNOWN: 0.30,
    UserActivityCategory.WORKING: 0.75,
    UserActivityCategory.STUDYING: 0.85,
    UserActivityCategory.GAMING: 0.90,
}

# 忙碌阈值：超过此值视为忙碌，Active Care 应该跳过或降低发送频率
DEFAULT_BUSY_THRESHOLD: float = 0.60

# 挂机判定阈值：系统全局无键鼠输入超过此秒数视为挂机（人不在），
# 即使前台是游戏/工作类进程也降级为 idle，避免误判忙碌而漏发主动关怀。
# 与 core/tools/screen_capture_tool.py 的 _IDLE_THRESHOLD_SECONDS 同源。
IDLE_THRESHOLD_SECONDS: float = 300.0


class UserActivityDetector:
    """
    用户活动检测器

    通过扫描系统前台进程/窗口，推断用户当前正在做什么。
    结果用于 Active Care 决策流程中的：
    1. 门控判断：用户是否正在忙碌（应该跳过主动关怀）
    2. 上下文注入：将活动信息提供给 LLM 决策模型

    用法:
        detector = UserActivityDetector()
        result = await detector.detect()
        if result.is_busy:
            # 用户正在忙碌，跳过 Active Care
            pass
        else:
            # 正常执行 Active Care 决策
            pass
    """

    def __init__(
        self,
        busy_threshold: float = DEFAULT_BUSY_THRESHOLD,
        enabled: bool = True,
        cache_ttl_seconds: float = 30.0,
    ):
        """
        初始化检测器

        Args:
            busy_threshold: 忙碌判定阈值 (0.0~1.0)
            enabled: 是否启用检测（可由配置开关控制）
            cache_ttl_seconds: 缓存有效期（秒），避免频繁扫描进程
        """
        self.busy_threshold = busy_threshold
        self.enabled = enabled
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_result: Optional[ActivityDetectionResult] = None
        self._cache_timestamp: float = 0.0
        self._platform = platform.system().lower()
        self._is_windows = self._platform == "windows"
        self._is_linux = self._platform == "linux"
        self._is_macos = self._platform == "darwin"

    async def detect(self) -> ActivityDetectionResult:
        """
        执行活动检测（异步接口）

        如果缓存未过期则直接返回缓存结果，
        否则在独立线程中执行进程扫描（避免阻塞事件循环）。
        """
        if not self.enabled:
            return ActivityDetectionResult(
                category=UserActivityCategory.UNKNOWN,
                is_busy=False,
                busy_level=0.0,
                confidence=0.0,
                timestamp=time.time(),
            )

        now = time.time()
        if (
            self._cached_result is not None
            and (now - self._cache_timestamp) < self.cache_ttl_seconds
        ):
            return self._cached_result

        try:
            import asyncio
            result = await asyncio.to_thread(self._detect_sync)
            self._cached_result = result
            self._cache_timestamp = now
            return result
        except Exception as e:
            logger.warning("UserActivityDetector.detect 异常: %s", e)
            return ActivityDetectionResult(
                category=UserActivityCategory.UNKNOWN,
                is_busy=False,
                busy_level=0.0,
                confidence=0.0,
                timestamp=time.time(),
                extra_info={"error": str(e)},
            )

    def _detect_sync(self) -> ActivityDetectionResult:
        """同步检测逻辑（在独立线程中执行）"""
        now = time.time()

        try:
            import psutil

            process_name = ""
            window_title = ""
            pid = None

            # 尝试获取前台进程信息
            if self._is_windows:
                process_name, window_title, pid = self._get_foreground_process_windows()
            elif self._is_macos:
                process_name, window_title, pid = self._get_foreground_process_macos()
            else:
                # Linux 或其他平台：获取当前最活跃的终端用户进程
                process_name, window_title, pid = self._get_active_process_fallback(psutil)

            if not process_name:
                return ActivityDetectionResult(
                    category=UserActivityCategory.IDLE,
                    process_name="",
                    window_title="",
                    display_name="空闲(桌面)",
                    is_busy=False,
                    busy_level=0.0,
                    confidence=0.7,
                    timestamp=now,
                )

            # 基于进程名进行初次分类
            category, display_name = classify_by_process_name(process_name)

            # 如果有窗口标题且是浏览器，进行二次分类
            if window_title and category in (
                UserActivityCategory.BROWSING, UserActivityCategory.UNKNOWN
            ):
                refined_category = classify_by_window_title(window_title)
                if refined_category != category:
                    category = refined_category
                    display_name = f"{display_name}({extract_relevant_keyword(window_title)})"

            # 计算忙碌程度
            busy_level = CATEGORY_BUSY_LEVEL.get(category, 0.30)
            is_busy = busy_level >= self.busy_threshold

            # 挂机检测：即使前台是游戏/工作类进程，若系统全局无键鼠输入
            # 超过阈值（人离开），降级为 idle，避免误判忙碌而漏发主动关怀。
            if is_busy:
                idle_seconds = self._get_idle_seconds()
                if idle_seconds >= IDLE_THRESHOLD_SECONDS:
                    logger.info(
                        "Activity Detection: 检测到挂机(空闲%ds≥%ds)，前台%s降级为 idle",
                        int(idle_seconds), int(IDLE_THRESHOLD_SECONDS),
                        category.value,
                    )
                    category = UserActivityCategory.IDLE
                    busy_level = 0.0
                    is_busy = False
                    display_name = "挂机(空闲)"

            result = ActivityDetectionResult(
                category=category,
                process_name=process_name,
                window_title=window_title or "",
                display_name=display_name or process_name,
                is_busy=is_busy,
                busy_level=busy_level,
                confidence=0.8 if category != UserActivityCategory.UNKNOWN else 0.4,
                timestamp=now,
                extra_info={"pid": pid},
            )

            logger.info(
                "Activity Detection: category=%s process=%s title=%s busy=%s level=%.2f",
                category.value, process_name, (window_title or "")[:50],
                is_busy, busy_level,
            )

            return result

        except ImportError:
            logger.warning("psutil 未安装，无法进行进程活动检测")
            return ActivityDetectionResult(
                category=UserActivityCategory.UNKNOWN,
                is_busy=False,
                busy_level=0.0,
                confidence=0.0,
                timestamp=now,
                extra_info={"error": "psutil not installed"},
            )
        except Exception as e:
            logger.warning("Activity detection error: %s", e)
            return ActivityDetectionResult(
                category=UserActivityCategory.UNKNOWN,
                is_busy=False,
                busy_level=0.0,
                confidence=0.0,
                timestamp=now,
                extra_info={"error": str(e)},
            )

    def _get_idle_seconds(self) -> float:
        """获取系统全局空闲时间（秒），即自上次键鼠输入以来的时间。

        使用 Win32 GetLastInputInfo + GetTickCount，非 Windows 返回 0.0。
        与 core/tools/screen_capture_tool.py 的 _get_idle_seconds 同源逻辑，
        用于挂机判定（前台虽是忙碌进程但人已离开的情况）。
        """
        if not self._is_windows:
            return 0.0
        try:
            import ctypes
            from ctypes import wintypes

            class _LastInputInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            lii = _LastInputInfo()
            lii.cbSize = ctypes.sizeof(_LastInputInfo)
            if not user32.GetLastInputInfo(ctypes.byref(lii)):
                return 0.0
            # GetTickCount 49.7 天后会回绕，用差值规避
            millis = (kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
            return millis / 1000.0
        except Exception as e:
            logger.debug("获取系统空闲时间失败: %s", e)
            return 0.0

    def _get_foreground_process_windows(self) -> Tuple[str, str, Optional[int]]:
        """获取 Windows 平台的前台窗口进程信息"""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            # 获取前台窗口句柄
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return "", "", None

            # 获取窗口标题
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                window_title = buf.value
            else:
                window_title = ""

            # 获取进程 ID
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return "", window_title, None

            # 通过 psutil 获取进程名
            try:
                import psutil
                proc = psutil.Process(pid.value)
                process_name = proc.name().lower()
                return process_name, window_title, pid.value
            except Exception:
                return "", window_title, pid.value

        except Exception as e:
            logger.debug("Windows foreground process detection failed: %s", e)
            return "", "", None

    def _get_foreground_process_macos(self) -> Tuple[str, str, Optional[int]]:
        """获取 macOS 平台的前台进程信息"""
        try:
            import subprocess

            # 使用 AppleScript 获取前台应用信息
            script = '''
            tell application "System Events"
                set frontApp to name of first application process whose frontmost is true
                set frontName to name of frontApp
            end tell
            return frontName
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            app_name = result.stdout.strip().lower() if result.returncode == 0 else ""

            # 尝试获取窗口标题
            script_title = '''
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                set frontWindow to name of front window of frontApp
            end tell
            return frontWindow
            '''
            result_title = subprocess.run(
                ["osascript", "-e", script_title],
                capture_output=True, text=True, timeout=5,
            )
            window_title = result_title.stdout.strip() if result_title.returncode == 0 else ""

            return app_name, window_title, None

        except Exception as e:
            logger.debug("MacOS foreground process detection failed: %s", e)
            return "", "", None

    def _get_active_process_fallback(self, psutil_module) -> Tuple[str, str, Optional[int]]:
        """
        回退方案：通过 CPU 使用率排序找到当前最活跃的用户进程
        用于 Linux 或其他无法获取前台窗口的平台
        """
        try:
            processes = []
            for proc in psutil_module.process_iter(["pid", "name", "cpu_percent"]):
                try:
                    info = proc.info
                    if not info or not info.get("name"):
                        continue
                    pname = info["name"].lower()
                    # 过滤系统进程和后台守护进程
                    if is_system_process(pname):
                        continue
                    cpu = info.get("cpu_percent") or 0
                    processes.append((pname, cpu, info["pid"]))
                except (psutil_module.NoSuchProcess, psutil_module.AccessDenied):
                    continue

            if not processes:
                return "", "", None

            # 按 CPU 使用率排序，取最高的
            processes.sort(key=lambda x: x[1], reverse=True)
            top_proc = processes[0]
            return top_proc[0], "", top_proc[2]

        except Exception as e:
            logger.debug("Fallback active process detection failed: %s", e)
            return "", "", None

    def invalidate_cache(self):
        """清除缓存，强制下次 detect 时重新扫描"""
        self._cached_result = None
        self._cache_timestamp = 0.0

    def get_status_summary(self) -> Dict[str, Any]:
        """获取检测器状态摘要（用于调试/API）"""
        return {
            "enabled": self.enabled,
            "busy_threshold": self.busy_threshold,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "platform": self._platform,
            "has_cached_result": self._cached_result is not None,
            "cache_age_seconds": round(time.time() - self._cache_timestamp, 1) if self._cache_timestamp > 0 else 0,
            "last_result": self._cached_result.to_dict() if self._cached_result else None,
        }


# ==================== 全局单例 ====================
_detector_instance: Optional[UserActivityDetector] = None


def get_activity_detector(
    busy_threshold: float = DEFAULT_BUSY_THRESHOLD,
    enabled: bool = True,
    cache_ttl_seconds: float = 30.0,
) -> UserActivityDetector:
    """获取全局活动检测器单例"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = UserActivityDetector(
            busy_threshold=busy_threshold,
            enabled=enabled,
            cache_ttl_seconds=cache_ttl_seconds,
        )
    return _detector_instance


def reset_activity_detector():
    """重置全局检测器（测试用）"""
    global _detector_instance
    _detector_instance = None
