"""学习系统统一路径解析。

背景：``student_state`` / ``daily_tracker`` / ``weakness_tracker`` 原先各自复制了
一份「读配置 -> 解析 study_root -> 拼 .state」的逻辑。新增 ConceptState、
LearningEvent 时如果继续各抄一份，后续调整存储根目录就会漏改。

这里收敛为唯一实现，所有学习系统的本地状态文件都从这里取路径。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger("StudyPaths")

# 配置缺失时的兜底相对路径（相对项目根目录）
_FALLBACK_STUDY_ROOT = "data/study"


def get_study_root() -> Path:
    """返回学习根目录（绝对路径）。

    优先读 ``config.integrated_config.get_settings().study.study_root``，
    经跨平台兼容层解析（Windows 盘符路径在 POSIX 下镜像到项目父目录）；
    配置缺失或异常时退回项目根目录下的 ``data/study``。
    """
    try:
        from config.integrated_config import get_settings
        from core.utils.data.data_paths import resolve_cross_platform_path

        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            return resolve_cross_platform_path(study_root)
    except Exception:
        pass
    return (get_project_root() / _FALLBACK_STUDY_ROOT).resolve()


def get_state_dir() -> Path:
    """返回学习系统状态目录 ``{study_root}/.state``。"""
    return get_study_root() / ".state"


def get_state_file(name: str) -> Path:
    """返回状态目录下的指定文件路径。"""
    return get_state_dir() / name


def get_daily_dir() -> Path:
    """返回每日记录目录 ``{study_root}/.state/daily``。"""
    return get_state_dir() / "daily"


def get_event_dir() -> Path:
    """返回学习事件目录 ``{study_root}/.state/learning_events``。"""
    return get_state_dir() / "learning_events"


def ensure_state_dir() -> Path:
    """确保状态目录存在并返回它。"""
    d = get_state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_corrupt_file(path: Path, *, suffix: Optional[str] = None) -> Optional[Path]:
    """把损坏的状态文件改名为 ``<name>.corrupt-<时间戳>`` 备份。

    用于状态文件解析失败时安全恢复：既不让损坏内容继续被读取，
    也不直接删除用户数据，便于事后人工排查。
    """
    try:
        if not path.exists():
            return None
        from core.utils.time_utils import now_str

        stamp = suffix or now_str("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        path.rename(target)
        return target
    except Exception as e:  # noqa: BLE001
        # 备份失败不能连累主流程，但必须留下痕迹，否则损坏文件会被静默覆盖
        logger.warning("备份损坏状态文件失败 %s：%s", path, e)
        return None
