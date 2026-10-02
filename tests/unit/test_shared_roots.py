"""跨系统共享目录解析的单元测试（双系统共用同一份日志 / 学习数据中转）。"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.project_root import get_project_root  # noqa: E402
from core.utils.shared_roots import (  # noqa: E402
    SHARED_ROOT_ENV,
    get_learning_hub_root,
    get_logs_root,
    get_shared_root,
)


def test_unset_shared_root_falls_back_to_project_root(monkeypatch):
    """未配置共享根时，日志根与学习数据中转都退回项目根下的原位置。"""
    monkeypatch.delenv(SHARED_ROOT_ENV, raising=False)

    assert get_shared_root() is None
    assert get_logs_root() == get_project_root() / "logs"
    assert get_learning_hub_root() is None


def test_shared_root_redirects_logs_and_hub(monkeypatch, tmp_path):
    """配置共享根后，日志与学习数据中转都落到共享根下。"""
    monkeypatch.setenv(SHARED_ROOT_ENV, str(tmp_path))

    assert get_shared_root() == tmp_path
    assert get_logs_root() == tmp_path / "logs"
    assert get_learning_hub_root() == tmp_path / "learning_hub"


def test_blank_shared_root_is_ignored(monkeypatch):
    """空字符串视同未配置，避免误把日志写到当前目录。"""
    monkeypatch.setenv(SHARED_ROOT_ENV, "   ")

    assert get_shared_root() is None
    assert get_logs_root() == get_project_root() / "logs"


def test_log_config_follows_shared_root(monkeypatch, tmp_path):
    """日志配置解析出的按日目录随共享根走，两个系统因此写同一个文件夹。"""
    from core.utils.logging.config import _resolve_daily_log_dir

    monkeypatch.setenv(SHARED_ROOT_ENV, str(tmp_path))
    resolved = Path(_resolve_daily_log_dir("logs"))

    assert resolved.parts[: len(tmp_path.parts) + 1] == (*tmp_path.parts, "logs")


def test_absolute_log_dir_is_not_hijacked(monkeypatch, tmp_path):
    """用户显式配置的绝对日志目录不被共享根劫持。"""
    from core.utils.logging.config import _resolve_daily_log_dir

    monkeypatch.setenv(SHARED_ROOT_ENV, str(tmp_path / "shared"))
    custom = tmp_path / "custom-logs"

    assert _resolve_daily_log_dir(str(custom)).startswith(str(custom))


@pytest.mark.parametrize("empty", ["", "   "])
def test_shared_root_ignores_blank_values(monkeypatch, empty):
    """各种空白取值都不应产生共享根。"""
    monkeypatch.setenv(SHARED_ROOT_ENV, empty)

    assert get_shared_root() is None
