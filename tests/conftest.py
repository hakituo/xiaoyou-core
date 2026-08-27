"""
pytest 配置文件

配置测试发现路径和异步测试支持
使用 pytest-asyncio 处理异步测试
"""
import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):
    """pytest 配置钩子"""
    # 配置测试发现路径
    config.addinivalue_line(
        "markers", "asyncio: mark test as an asyncio test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "gpu: mark test as requiring GPU"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )


def pytest_collection_modifyitems(config, items):
    """
    测试收集后处理钩子
    为测试添加默认标记
    """
    # 根据文件路径自动添加标记
    for item in items:
        # 单元测试
        if "unit" in str(item.fspath):
            item.add_marker("unit")
        # 集成测试
        elif "integration" in str(item.fspath):
            item.add_marker("integration")
        # 压力测试
        elif "stress" in str(item.fspath):
            item.add_marker("slow")
        # 调度器测试
        elif "scheduler" in str(item.fspath):
            item.add_marker("integration")
