# -*- coding: utf-8 -*-
"""data_ops 包惰性门面的回归测试。

背景：`core.services.data_ops.__init__` 曾在导入期就拉起
`service` → `bert_analyzer` → transformers / onnxruntime。而包内还有 `scene_facts`
这种只依赖标准库的纯函数模块，persona 的 `explicit_current_facts` 只是想用它做一次
正则提取，却会在未安装 transformers 的环境（CI 的 `uv sync --extra dev`）里被拖成
ModuleNotFoundError。改为按需解析后，这里守住两条底线：
1. 导入轻量子模块不得连带拉起重型依赖；
2. 门面符号仍然能按原路径取到。
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 只有导入 data_ops 重型链路才会出现的模块
_HEAVY_MODULES = (
    "transformers",
    "onnxruntime",
    "core.services.data_ops.service",
    "core.services.data_ops.api",
    "core.services.data_ops.bert_analyzer",
)


def test_light_submodule_import_does_not_pull_heavy_deps():
    """子进程里只导入轻量子模块，重型依赖链不应被带起来。"""
    code = (
        "import sys\n"
        "import core.services.data_ops.scene_facts\n"
        "loaded = [n for n in " + repr(_HEAVY_MODULES) + " if n in sys.modules]\n"
        "sys.stdout.write('loaded=' + ','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "loaded=" in result.stdout, result.stdout
    assert result.stdout.split("loaded=", 1)[1].strip() == "", result.stdout


def test_facade_exports_declared_and_unknown_attr_raises():
    import core.services.data_ops as data_ops

    assert set(data_ops.__all__) == set(data_ops._LAZY_ATTR_MODULES)
    with pytest.raises(AttributeError):
        getattr(data_ops, "definitely_not_exported")


def test_facade_symbol_resolves_without_heavy_deps():
    """门面符号按原路径可取；这里挑一个不依赖 transformers 的符号验证解析逻辑。"""
    import core.services.data_ops as data_ops

    assert callable(getattr(data_ops, "validate_internal_token"))
