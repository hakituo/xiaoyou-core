"""跨平台路径兼容层测试。

验证 core.utils.data.data_paths.resolve_cross_platform_path：
- POSIX 下 Windows 盘符路径按镜像表重定向（D:\\AI\\Study → ~/Study）；
- 斜杠方向与大小写归一化后命中同一条镜像；
- POSIX 绝对路径、~ 展开、相对路径的解析规则；
- 学习根目录的全部解析入口结果一致。

注：Windows 上 ``D:\\AI\\Study`` 被原生 Path 判定为绝对路径、第一关直接原样返回，
该平台行为由 pathlib 平台语义保证，无需在 POSIX 上模拟。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.utils.common import get_project_root
from core.utils.data.data_paths import (
    get_study_root_dir,
    resolve_cross_platform_path,
)


def test_windows_study_root_mirrors_to_home_study():
    """登记过的 Windows 盘符路径在 POSIX 下重定向到 ~/Study。"""
    assert resolve_cross_platform_path(r"D:\projects\study") == (Path.home() / "Study").resolve()


@pytest.mark.parametrize(
    "raw",
    [r"D:\projects\study", "D:/AI/Study", r"d:\ai\study", "d:/ai/study"],
)
def test_windows_path_slash_and_case_normalization(raw):
    """正反斜杠与大小写差异归一化后命中同一条镜像。"""
    assert resolve_cross_platform_path(raw) == (Path.home() / "Study").resolve()


def test_posix_absolute_passthrough():
    assert str(resolve_cross_platform_path("/srv/data/study")) == "/srv/data/study"


def test_home_expansion():
    assert resolve_cross_platform_path("~/custom_dir") == (Path.home() / "custom_dir").resolve()


def test_relative_anchors_to_project_root():
    expected = (get_project_root() / "data" / "study").resolve()
    assert resolve_cross_platform_path("data/study") == expected


def test_unregistered_drive_mirrors_beside_project():
    """未登记的盘符路径兜底镜像到项目父目录（盘符根 ↔ 父目录）。"""
    expected = (get_project_root().parent / "other" / "dir").resolve()
    assert resolve_cross_platform_path(r"E:\other\dir") == expected


def test_empty_value_anchors_to_project_root():
    assert resolve_cross_platform_path("") == get_project_root().resolve()


def test_all_study_root_entry_points_agree():
    """生产代码的四个 study_root 解析入口必须收敛到同一结果。"""
    from core.services.study.paths import get_study_root
    from core.services.study.summary_generator import _get_study_root as summary_root
    from core.tools.study_data_tool import StudyDataTool
    from core.tools.study_profile_tool import _get_study_root as profile_root

    canonical = get_study_root_dir()
    assert get_study_root() == canonical
    assert summary_root() == canonical
    assert profile_root() == str(canonical)
    assert StudyDataTool()._base_dir == canonical
