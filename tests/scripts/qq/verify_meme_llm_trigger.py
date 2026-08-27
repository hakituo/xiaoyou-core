"""验证表情包 LLM 手动触发机制（[MEME:分类] 标签）。

验证点：
1. media_tags.list_normal_meme_categories() 能扫描 data/memes/ 一级子目录（排除 manual）
2. media_tags.pick_meme_image 支持普通分类（如 happy/angry）
3. media_tags.pick_meme_image 对不存在的分类 fallback 到 random
4. qq_integration.build_meme_tag_prompt() 能动态生成包含分类列表的 prompt
5. apply_qq_optimizations 对 QQ 源人设注入 [MEME:分类] 说明
6. MemeHandler._list_categories 排除 manual
7. meme.py 已无 send_auto_meme 方法
8. main.py 已无 maybe_send_auto_meme 方法
9. settings.py 已无 QQ_AUTO_MEME_* 配置
"""
import os
import sys
import tempfile

# 加入项目根目录到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

_passed = 0
_failed = 0


def _ok(msg: str):
    global _passed
    _passed += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str):
    global _failed
    _failed += 1
    print(f"  [FAIL] {msg}")


def test_list_normal_categories():
    """测试 1：list_normal_meme_categories 扫描并排除 manual"""
    print("\n=== 测试 1：list_normal_meme_categories 排除 manual ===")
    from clients.bots.qq.media_tags import list_normal_meme_categories

    cats = list_normal_meme_categories()
    if not cats:
        _fail("data/memes/ 下没有扫描到任何分类（目录不存在或为空）")
        return
    if "manual" in [c.lower() for c in cats]:
        _fail(f"manual 不应出现在分类列表中，实际：{cats}")
    else:
        _ok(f"扫描到 {len(cats)} 个分类，已排除 manual：{cats}")


def test_pick_normal_category():
    """测试 2：pick_meme_image 支持普通分类"""
    print("\n=== 测试 2：pick_meme_image 普通分类 ===")
    from clients.bots.qq.media_tags import pick_meme_image, list_normal_meme_categories, reset_recent_history

    cats = list_normal_meme_categories()
    if not cats:
        _fail("无分类可用，跳过")
        return

    reset_recent_history()
    target_cat = cats[0]
    img = pick_meme_image(target_cat)
    if img is None:
        _fail(f"分类 {target_cat} 选图失败（返回 None）")
    else:
        _ok(f"分类 {target_cat} 选图成功：{img.name}")


def test_pick_random_fallback():
    """测试 3：pick_meme_image 不存在分类时 fallback 到 random"""
    print("\n=== 测试 3：pick_meme_image 不存在分类 fallback ===")
    from clients.bots.qq.media_tags import pick_meme_image, reset_recent_history

    reset_recent_history()
    img = pick_meme_image("this_category_does_not_exist_12345")
    if img is None:
        _fail("不存在分类应 fallback 到 random，但返回 None")
    else:
        _ok(f"不存在分类 fallback 到 random 成功：{img.name}")


def test_build_meme_tag_prompt():
    """测试 4：build_meme_tag_prompt 生成包含分类的 prompt"""
    print("\n=== 测试 4：build_meme_tag_prompt 动态生成 ===")
    from core.agents.chat_agent_components.persona_system.prompt.qq_integration import build_meme_tag_prompt

    prompt = build_meme_tag_prompt()
    if not prompt:
        _fail("build_meme_tag_prompt 返回空（data/memes/ 可能不存在）")
        return
    if "[MEME:" not in prompt:
        _fail(f"prompt 不含 [MEME: 标签说明：{prompt[:100]}")
    elif "分类" not in prompt:
        _fail(f"prompt 不含分类说明：{prompt[:100]}")
    else:
        _ok(f"prompt 生成成功，长度 {len(prompt)} 字符")

    # 验证分类列表动态填入
    from clients.bots.qq.media_tags import list_normal_meme_categories
    cats = list_normal_meme_categories()
    if cats:
        first_cat = cats[0]
        if first_cat in prompt:
            _ok(f"分类列表已动态填入（含 {first_cat}）")
        else:
            _fail(f"分类 {first_cat} 未出现在 prompt 中")


def test_apply_qq_optimizations_injects_meme_prompt():
    """测试 5：apply_qq_optimizations 对 QQ 源注入 [MEME] 说明"""
    print("\n=== 测试 5：apply_qq_optimizations 注入 [MEME] 说明 ===")
    from core.agents.chat_agent_components.persona_system.prompt.qq_integration import apply_qq_optimizations

    # QQ 源（private_ 开头）
    result = apply_qq_optimizations("测试人设", "private_12345", "/configs/qq/test.json")
    if "【发表情包】" in result and "[MEME:" in result:
        _ok("QQ 源人设已注入 [MEME] 标签说明")
    else:
        _fail(f"QQ 源人设未注入 [MEME] 说明：{result[:200]}")

    # 非 QQ 源不应注入
    result_non_qq = apply_qq_optimizations("测试人设", "web_user", "/configs/sfw/test.json")
    if "【发表情包】" not in result_non_qq:
        _ok("非 QQ 源未注入 [MEME] 说明（符合预期）")
    else:
        _fail("非 QQ 源不应注入 [MEME] 说明")


def test_meme_handler_excludes_manual():
    """测试 6：MemeHandler._list_categories 排除 manual"""
    print("\n=== 测试 6：MemeHandler._list_categories 排除 manual ===")
    from clients.bots.handlers.meme import MemeHandler

    with tempfile.TemporaryDirectory() as tmp:
        memes_root = os.path.join(tmp, "data", "memes")
        os.makedirs(os.path.join(memes_root, "happy"))
        os.makedirs(os.path.join(memes_root, "manual", "sensitive"))

        class _DummyAdapter:
            _project_root = tmp
            logger = None

        handler = MemeHandler(_DummyAdapter())
        cats = handler._list_categories()
        if "manual" in cats:
            _fail(f"manual 不应出现在 _list_categories 结果中：{cats}")
        elif "happy" not in cats:
            _fail(f"happy 应在 _list_categories 结果中：{cats}")
        else:
            _ok(f"_list_categories 正确排除 manual，结果：{cats}")


def test_auto_meme_removed():
    """测试 7-9：验证自动触发链已移除"""
    print("\n=== 测试 7-9：验证自动触发链已移除 ===")

    # 7. MemeHandler 无 send_auto_meme
    from clients.bots.handlers.meme import MemeHandler
    if hasattr(MemeHandler, "send_auto_meme"):
        _fail("MemeHandler 仍含 send_auto_meme 方法")
    else:
        _ok("MemeHandler 已无 send_auto_meme 方法")

    # 8. QQAdapter 无 maybe_send_auto_meme
    from clients.bots.qq.main import QQAdapter
    if hasattr(QQAdapter, "maybe_send_auto_meme"):
        _fail("QQAdapter 仍含 maybe_send_auto_meme 方法")
    else:
        _ok("QQAdapter 已无 maybe_send_auto_meme 方法")

    # 9. settings 无 QQ_AUTO_MEME
    from clients.bots.qq import settings as qq_settings
    auto_meme_attrs = [a for a in dir(qq_settings) if a.startswith("QQ_AUTO_MEME")]
    if auto_meme_attrs:
        _fail(f"settings 仍含 QQ_AUTO_MEME_* 配置：{auto_meme_attrs}")
    else:
        _ok("settings 已无 QQ_AUTO_MEME_* 配置")


def main():
    print("=" * 60)
    print("表情包 LLM 手动触发机制验证")
    print("=" * 60)

    test_list_normal_categories()
    test_pick_normal_category()
    test_pick_random_fallback()
    test_build_meme_tag_prompt()
    test_apply_qq_optimizations_injects_meme_prompt()
    test_meme_handler_excludes_manual()
    test_auto_meme_removed()

    print("\n" + "=" * 60)
    print(f"结果：{_passed} 通过，{_failed} 失败")
    print("=" * 60)
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
