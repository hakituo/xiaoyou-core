"""UIE 信息抽取验证脚本。

验证内容：
1. UIE 后端加载（ONNX 优先，PaddleNLP 回退）
2. 各 schema 字段的提取效果（起床时间/睡觉时间/吃的食物/学习内容等）
3. ActivityExtractor._uie_time_to_hhmm 时间转换逻辑
4. UIE 不可用时的回退行为

使用方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\uie\\verify_uie_extraction.py

前置条件（可选）：
    若要测试 ONNX 后端，先运行: python scripts/setup/setup_uie_model.py
    若要测试 PaddleNLP 后端，先安装: pip install paddlepaddle paddlenlp
"""
import asyncio
import os
import sys
import time

# 确保能导入项目模块
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _print_header(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _print_case(text: str, expected: str, actual: any) -> bool:
    """打印单个测试用例结果，返回是否通过。"""
    actual_str = str(actual) if actual is not None else "(空)"
    ok = bool(actual)
    mark = "[OK]  " if ok else "[FAIL]"
    print(f"  {mark} 输入: {text}")
    print(f"        期望: {expected}")
    print(f"        实际: {actual_str}")
    return ok


def test_uie_backend() -> bool:
    """测试 UIE 后端加载。"""
    _print_header("1. UIE 后端加载测试")
    try:
        from core.services.data_ops.uie_extractor import get_uie_extractor

        t0 = time.time()
        extractor = get_uie_extractor()
        load_ms = (time.time() - t0) * 1000

        if not extractor._backend:
            print("  [SKIP] UIE 后端不可用")
            print("         请运行: python scripts/setup/setup_uie_model.py")
            print("         或安装: pip install paddlepaddle paddlenlp")
            return False

        print(f"  [OK] 后端: {extractor._backend}  加载耗时: {load_ms:.0f}ms")
        return True
    except Exception as e:
        print(f"  [FAIL] 加载异常: {e}")
        return False


def test_uie_extraction(uie_available: bool) -> None:
    """测试 UIE 各字段提取效果。"""
    _print_header("2. UIE 字段提取测试")

    if not uie_available:
        print("  [SKIP] UIE 后端不可用，跳过提取测试")
        return

    from core.services.data_ops.uie_extractor import get_uie_extractor

    extractor = get_uie_extractor()

    # 测试用例: (文本, 期望出现的字段)
    test_cases = [
        ("我今天早上7点起的", ["起床时间"]),
        ("昨晚11点半睡的", ["睡觉时间"]),
        ("刚吃了一碗面条", ["吃的食物"]),
        ("早餐吃了面包和牛奶", ["吃的食物", "餐次"]),
        ("刚复习了高数第三章", ["学习内容"]),
        ("出门打了一场篮球", ["活动内容"]),
        ("今天有点头疼", ["健康症状"]),
        ("心情有点郁闷", ["情绪"]),
        ("晚上10点睡的，早上6点起的", ["起床时间", "睡觉时间"]),
    ]

    pass_count = 0
    for text, expected_fields in test_cases:
        print(f"\n  输入: {text}")
        try:
            t0 = time.time()
            result = extractor.extract(text, expected_fields)
            elapsed_ms = (time.time() - t0) * 1000
            print(f"  耗时: {elapsed_ms:.0f}ms")
            if not result:
                print("  [FAIL] 未提取到任何字段")
                continue
            for field in expected_fields:
                spans = result.get(field) or []
                if spans:
                    text_val = spans[0].get("text", "")
                    prob = spans[0].get("probability", 0.0)
                    print(f"  [OK]  {field}: '{text_val}' (p={prob:.2f})")
                    pass_count += 1
                else:
                    print(f"  [FAIL] {field}: 未提取到")
        except Exception as e:
            print(f"  [FAIL] 异常: {e}")

    print(f"\n  小结: {pass_count}/{sum(len(c[1]) for c in test_cases)} 字段提取成功")


def test_time_normalization() -> None:
    """测试 ActivityExtractor._uie_time_to_hhmm 时间转换。"""
    _print_header("3. UIE 时间标准化测试")

    # 直接实例化 ActivityExtractor 会触发 daily_manager 初始化，
    # 这里用一个轻量 stub 测试 _uie_time_to_hhmm 逻辑
    from core.services.daily.extractor import ActivityExtractor

    # 用 __new__ 绕过 __init__ 避免触发 daily_manager
    extractor = ActivityExtractor.__new__(ActivityExtractor)

    # 测试用例: (uie_time, raw, is_sleep, 期望 HH:MM 或 None)
    cases = [
        ("7点", "我今天早上7点起的", False, "07:00"),
        ("7点半", "早上7点半醒了", False, "07:30"),
        ("11点", "昨晚11点睡的", True, "23:00"),
        ("11点半", "晚上11点半睡的", True, "23:30"),
        ("6点", "晚上6点起的", False, "18:00"),  # raw 有"晚上"，晚上6点 = 18:00
        ("凌晨2点", "熬夜到凌晨2点才睡", True, "02:00"),
        ("7点20", "今早7点20起床", False, "07:20"),
        ("", "没有时间信息", False, None),
    ]

    pass_count = 0
    for uie_time, raw, is_sleep, expected in cases:
        actual = extractor._uie_time_to_hhmm(uie_time, raw, is_sleep)
        ok = actual == expected
        mark = "[OK]  " if ok else "[FAIL]"
        print(f"  {mark} uie='{uie_time}' raw='{raw}' is_sleep={is_sleep}")
        print(f"        期望: {expected}  实际: {actual}")
        if ok:
            pass_count += 1

    print(f"\n  小结: {pass_count}/{len(cases)} 通过")


def test_extractor_fallback() -> None:
    """测试 UIE 不可用时 ActivityExtractor 回退正则。"""
    _print_header("4. UIE 不可用时回退测试")

    from core.services.daily.extractor import ActivityExtractor

    extractor = ActivityExtractor.__new__(ActivityExtractor)
    # 模拟 UIE 不可用
    extractor._uie_available = False
    extractor._uie_extractor = None

    uie_extractor = extractor._get_uie_extractor()
    if uie_extractor is not None:
        print("  [WARN] UIE 实际可用，无法测试回退场景")
        return

    print("  [OK] UIE 不可用时 _get_uie_extractor 返回 None")

    # 测试原正则方法仍可用
    meal = extractor._extract_meal_content("刚吃了一碗面条")
    _print_case("刚吃了一碗面条", "面条", meal)

    symptom = extractor._extract_health_symptom("今天头疼")
    _print_case("今天头疼", "头疼", symptom)

    mood = extractor._extract_mood_label("心情有点开心")
    _print_case("心情有点开心", "开心", mood)


async def test_async_integration(uie_available: bool) -> None:
    """测试异步集成（_uie_extract_async）。"""
    _print_header("5. 异步 UIE 提取集成测试")

    from core.services.daily.extractor import ActivityExtractor

    extractor = ActivityExtractor.__new__(ActivityExtractor)
    extractor._uie_available = None
    extractor._uie_extractor = None

    if not uie_available:
        # 测试 UIE 不可用时返回空 dict
        result = await extractor._uie_extract_async("我今天7点起的", ["起床时间"])
        ok = result == {}
        mark = "[OK]  " if ok else "[FAIL]"
        print(f"  {mark} 输入: UIE 不可用时提取")
        print(f"        期望: {{}}  实际: {result}")
        return

    # UIE 可用时测试异步提取
    test_cases = [
        ("我今天早上7点起的", ["起床时间"]),
        ("刚吃了一碗面条", ["吃的食物"]),
        ("心情有点郁闷", ["情绪"]),
    ]

    for text, schema in test_cases:
        print(f"\n  输入: {text}")
        try:
            t0 = time.time()
            result = await extractor._uie_extract_async(text, schema)
            elapsed_ms = (time.time() - t0) * 1000
            print(f"  耗时: {elapsed_ms:.0f}ms")
            if not result:
                print("  [FAIL] 返回空结果")
                continue
            for field, spans in result.items():
                if spans:
                    print(f"  [OK]  {field}: '{spans[0].get('text', '')}'")
                else:
                    print(f"  [FAIL] {field}: 空 spans")
        except Exception as e:
            print(f"  [FAIL] 异常: {e}")


def main() -> int:
    print("=" * 60)
    print("  UIE 信息抽取验证脚本")
    print("=" * 60)

    # 1. 后端加载
    uie_available = test_uie_backend()

    # 2. 字段提取
    test_uie_extraction(uie_available)

    # 3. 时间标准化
    test_time_normalization()

    # 4. 回退测试
    test_extractor_fallback()

    # 5. 异步集成
    asyncio.run(test_async_integration(uie_available))

    _print_header("验证完成")
    if not uie_available:
        print("  UIE 后端未就绪。请执行以下步骤之一：")
        print("  1. 运行: python scripts/setup/setup_uie_model.py (推荐，ONNX 后端)")
        print("  2. 安装: pip install paddlepaddle paddlenlp (PaddleNLP 后端)")
    else:
        print("  UIE 后端就绪，集成代码可用。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
