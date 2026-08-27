"""
ScreenCaptureTool 验证脚本

验证项：
1. 工具能正确导入和实例化
2. 工具能注册到 ToolRegistry
3. Master 权限检查逻辑正确（master/非 master/空 user_id）
4. 挂机检测 API 可用（返回非负数）
5. 活动屏幕边界获取可用（返回合法 bbox 或 None）
6. 截图功能可用（实际截一张图，验证文件生成）
7. 截图清理逻辑可用（生成过期文件验证被删除）
8. 冷却机制可用（连续调用第二次被拦截）

注意：不验证视觉模型分析（依赖 API Key 和网络），仅验证到 describe_image 调用入口。

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\tools\\verify_screen_capture_tool.py
    或
    venv_cpu\\Scripts\\python.exe tests\\scripts\\tools\\verify_screen_capture_tool.py
"""

import asyncio
import os
import sys
import time

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def test_import_and_instantiate() -> bool:
    """测试 1：导入和实例化"""
    print("\n[测试 1] 导入和实例化")
    try:
        from core.tools.screen_capture_tool import ScreenCaptureTool, ScreenCaptureInput
        tool = ScreenCaptureTool()
        if tool.name != "look_at_screen":
            _fail(f"name 不匹配: {tool.name}")
            return False
        if tool.category != "utility":
            _fail(f"category 不匹配: {tool.category}")
            return False
        if tool.args_schema is not ScreenCaptureInput:
            _fail("args_schema 不匹配")
            return False
        _ok(f"工具实例化成功，name={tool.name}, category={tool.category}")
        return True
    except Exception as e:
        _fail(f"导入/实例化失败: {e}")
        return False


def test_registry_registration() -> bool:
    """测试 2：注册到 ToolRegistry"""
    print("\n[测试 2] 注册到 ToolRegistry")
    try:
        from core.tools.registry import ToolRegistry, register_all_tools
        registry = ToolRegistry()
        register_all_tools(registry)
        tool = registry.get_tool("look_at_screen")
        if tool is None:
            _fail("注册后 get_tool('look_at_screen') 返回 None")
            return False
        if not registry.is_enabled("look_at_screen"):
            _fail("工具未启用")
            return False
        _ok("工具已注册到 ToolRegistry 且启用")
        return True
    except Exception as e:
        _fail(f"注册测试失败: {e}")
        return False


def test_master_permission() -> bool:
    """测试 3：Master 权限检查"""
    print("\n[测试 3] Master 权限检查")
    try:
        from core.tools.screen_capture_tool import ScreenCaptureTool
        tool = ScreenCaptureTool()

        # 3.1 空 user_id → 非 master
        tool.set_runtime_context({"user_id": ""})
        if tool._is_master():
            _fail("空 user_id 不应判定为 master")
            return False
        _ok("空 user_id → 非 master")

        # 3.2 default → master
        tool.set_runtime_context({"user_id": "default"})
        if not tool._is_master():
            _fail("default 应判定为 master")
            return False
        _ok("default → master")

        # 3.3 default_user → master
        tool.set_runtime_context({"user_id": "default_user"})
        if not tool._is_master():
            _fail("default_user 应判定为 master")
            return False
        _ok("default_user → master")

        # 3.4 普通 QQ 私聊（非 master）→ 非 master
        tool.set_runtime_context({"user_id": "private_99999__persona__aveline_qq"})
        if tool._is_master():
            _fail("非 master QQ 私聊不应判定为 master")
            return False
        _ok("非 master QQ 私聊 → 非 master")

        # 3.5 群聊 → 非 master
        tool.set_runtime_context({"user_id": "group_12345__persona__aveline_qq_group"})
        if tool._is_master():
            _fail("群聊不应判定为 master")
            return False
        _ok("群聊 → 非 master")

        # 3.6 master QQ 私聊（如果配置了 MASTER_QQ_ID）
        try:
            from clients.bots.qq.settings import MASTER_QQ_ID
            if MASTER_QQ_ID:
                tool.set_runtime_context({"user_id": f"private_{MASTER_QQ_ID}__persona__aveline_qq_master"})
                if not tool._is_master():
                    _fail(f"master QQ 私聊（private_{MASTER_QQ_ID}...）应判定为 master")
                    return False
                _ok(f"master QQ 私聊（MASTER_QQ_ID={MASTER_QQ_ID}）→ master")
            else:
                _ok("MASTER_QQ_ID 未配置，跳过 master QQ 私聊测试")
        except ImportError:
            _ok("clients.bots.qq.settings 不可用（非 QQ 部署），跳过 master QQ 私聊测试")

        return True
    except Exception as e:
        _fail(f"Master 权限检查测试失败: {e}")
        return False


def test_idle_detection() -> bool:
    """测试 4：挂机检测 API"""
    print("\n[测试 4] 挂机检测 API")
    try:
        from core.tools.screen_capture_tool import ScreenCaptureTool
        tool = ScreenCaptureTool()
        idle = tool._get_idle_seconds()
        if idle < 0:
            _fail(f"空闲时间不应为负数: {idle}")
            return False
        _ok(f"系统空闲时间: {idle:.1f} 秒（非负数，API 正常）")
        return True
    except Exception as e:
        _fail(f"挂机检测测试失败: {e}")
        return False


def test_active_screen_bbox() -> bool:
    """测试 5：活动屏幕边界获取"""
    print("\n[测试 5] 活动屏幕边界获取")
    try:
        from core.tools.screen_capture_tool import ScreenCaptureTool
        tool = ScreenCaptureTool()
        bbox = tool._get_active_screen_bbox()
        if bbox is None:
            _ok("返回 None（可能非 Windows 或无显示器信息），将回退主屏截图")
            return True
        left, top, right, bottom = bbox
        if right <= left or bottom <= top:
            _fail(f"bbox 不合法: {bbox}")
            return False
        _ok(f"活动屏幕边界: {bbox}（宽={right-left}, 高={bottom-top}）")
        return True
    except Exception as e:
        _fail(f"活动屏幕边界测试失败: {e}")
        return False


def test_screenshot_capture() -> bool:
    """测试 6：实际截图（含自适应压缩）"""
    print("\n[测试 6] 实际截图（含自适应压缩）")
    try:
        from core.tools.screen_capture_tool import ScreenCaptureTool, _SCREENSHOT_DIR
        tool = ScreenCaptureTool()
        path = tool._capture_active_screen()
        if not os.path.exists(path):
            _fail(f"截图文件不存在: {path}")
            return False
        size = os.path.getsize(path)
        if size < 1000:
            _fail(f"截图文件过小（{size} 字节），可能损坏")
            return False
        if not path.lower().endswith(".jpg"):
            _fail(f"截图应为 JPEG 格式，实际: {path}")
            return False
        # 验证是合法 JPEG
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        _ok(f"截图成功: {path}（{size} 字节, JPEG 合法）")
        return True
    except Exception as e:
        _fail(f"截图测试失败: {e}")
        return False


def test_compress_strategy() -> bool:
    """测试 6.5：自适应压缩分档策略"""
    print("\n[测试 6.5] 自适应压缩分档策略")
    try:
        from core.tools.screen_capture_tool import ScreenCaptureTool
        from PIL import Image

        tool = ScreenCaptureTool()

        # 6.5.1 分档逻辑
        cases = [
            (1366, 1366, "1080p 1366宽 → 不缩"),
            (1920, 1920, "1080p 1920宽 → 不缩"),
            (2560, 1920, "2.5K 2560宽 → 缩到1920 (75%)"),
            (3000, 2560, "3K 3000宽 → 缩到2560 (85%)"),
            (3840, 2560, "4K 3840宽 → 缩到2560 (67%)"),
            (5120, 3000, "5K 5120宽 → 缩到3000 (58%)"),
            (7680, 3000, "8K 7680宽 → 缩到3000 (兜底)"),
        ]
        for src_w, expected_w, desc in cases:
            actual_w = tool._get_compress_target_width(src_w)
            if actual_w != expected_w:
                _fail(f"分档错误: {desc}, 期望 {expected_w} 实际 {actual_w}")
                return False
            _ok(f"{desc}: 目标宽 {actual_w}")

        # 6.5.2 压缩函数：构造 2.5K 假图，验证缩放 + JPEG 输出
        fake_img = Image.new("RGB", (2560, 1440), color=(100, 150, 200))
        compressed, target_w = tool._compress_screenshot(fake_img)
        if target_w != 1920:
            _fail(f"2.5K 压缩目标宽应为 1920，实际 {target_w}")
            return False
        # 验证是合法 JPEG
        verify_img = Image.open(__import__("io").BytesIO(compressed))
        verify_img.verify()
        if len(compressed) > 50000:  # 纯色 2.5K JPEG 应该很小
            _fail(f"纯色图压缩后过大: {len(compressed)} 字节")
            return False
        _ok(f"2.5K 纯色图压缩: {len(compressed)} 字节, 目标宽 {target_w}")

        # 6.5.3 RGBA 输入应自动转 RGB
        fake_rgba = Image.new("RGBA", (1920, 1080), color=(100, 150, 200, 255))
        compressed2, target_w2 = tool._compress_screenshot(fake_rgba)
        verify_img2 = Image.open(__import__("io").BytesIO(compressed2))
        verify_img2.verify()
        _ok(f"RGBA 输入自动转 RGB: {len(compressed2)} 字节")

        return True
    except Exception as e:
        _fail(f"压缩策略测试失败: {e}")
        return False


def test_cleanup_logic() -> bool:
    """测试 7：截图清理逻辑"""
    print("\n[测试 7] 截图清理逻辑")
    try:
        from core.tools.screen_capture_tool import (
            ScreenCaptureTool,
            _SCREENSHOT_DIR,
            _SCREENSHOT_TTL_SECONDS,
        )
        os.makedirs(_SCREENSHOT_DIR, exist_ok=True)

        # 创建一个过期文件（修改时间为 25 小时前）
        old_file = os.path.join(_SCREENSHOT_DIR, "test_old_expired.png")
        with open(old_file, "wb") as f:
            f.write(b"fake")
        old_time = time.time() - _SCREENSHOT_TTL_SECONDS - 3600
        os.utime(old_file, (old_time, old_time))

        # 创建一个新文件
        new_file = os.path.join(_SCREENSHOT_DIR, "test_new_valid.png")
        with open(new_file, "wb") as f:
            f.write(b"fake")

        tool = ScreenCaptureTool()
        tool._cleanup_old_screenshots()

        if os.path.exists(old_file):
            _fail(f"过期文件未被清理: {old_file}")
            return False
        if not os.path.exists(new_file):
            _fail(f"新文件不应被清理: {new_file}")
            return False

        # 清理测试文件
        try:
            os.remove(new_file)
        except OSError:
            pass

        _ok("清理逻辑正常：过期文件已删除，新文件保留")
        return True
    except Exception as e:
        _fail(f"清理逻辑测试失败: {e}")
        return False


async def test_cooldown_and_full_run() -> bool:
    """测试 8：冷却机制 + 完整运行（mock 视觉模型）"""
    print("\n[测试 8] 冷却机制 + 完整运行")
    try:
        import core.tools.screen_capture_tool as mod
        from core.tools.screen_capture_tool import ScreenCaptureTool

        # 重置冷却
        mod._last_capture_ts = 0.0

        tool = ScreenCaptureTool()
        # 用 default 身份（master）
        tool.set_runtime_context({"user_id": "default"})

        # mock 视觉模块，避免依赖 API Key
        class _FakeVM:
            async def describe_image(self, image, prompt):
                return {"status": "success", "response": "[MOCK] 用户在写代码"}

        import core.core_engine.service_singletons as sgl
        original_get = sgl.get_vision_module
        sgl.get_vision_module = lambda: _FakeVM()

        try:
            result = await tool.run()
            if "MOCK" not in result:
                _fail(f"第一次调用未返回预期结果: {result}")
                return False
            _ok(f"第一次调用成功: {result[:60]}...")

            # 第二次调用应被冷却拦截
            result2 = await tool.run()
            if "冷却" not in result2:
                _fail(f"第二次调用应被冷却拦截，实际: {result2}")
                return False
            _ok(f"第二次调用被冷却拦截: {result2[:40]}...")
        finally:
            sgl.get_vision_module = original_get

        return True
    except Exception as e:
        _fail(f"冷却/完整运行测试失败: {e}")
        return False


async def test_non_master_blocked() -> bool:
    """测试 9：非 master 被拦截"""
    print("\n[测试 9] 非 master 被拦截")
    try:
        import core.tools.screen_capture_tool as mod
        mod._last_capture_ts = 0.0

        from core.tools.screen_capture_tool import ScreenCaptureTool
        tool = ScreenCaptureTool()
        tool.set_runtime_context({"user_id": "private_99999__persona__aveline_qq"})
        result = await tool.run()
        if "权限不足" not in result:
            _fail(f"非 master 应被拦截，实际: {result}")
            return False
        _ok(f"非 master 被拦截: {result[:40]}...")
        return True
    except Exception as e:
        _fail(f"非 master 拦截测试失败: {e}")
        return False


async def main():
    print("=" * 60)
    print("ScreenCaptureTool 验证脚本")
    print("=" * 60)

    results = []
    results.append(test_import_and_instantiate())
    results.append(test_registry_registration())
    results.append(test_master_permission())
    results.append(test_idle_detection())
    results.append(test_active_screen_bbox())
    results.append(test_screenshot_capture())
    results.append(test_compress_strategy())
    results.append(test_cleanup_logic())
    results.append(await test_cooldown_and_full_run())
    results.append(await test_non_master_blocked())

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"验证结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed == total:
        print("✓ 全部验证通过")
        sys.exit(0)
    else:
        print("✗ 存在失败项")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
