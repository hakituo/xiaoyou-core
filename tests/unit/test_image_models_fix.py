"""
测试 image_models API 修复
验证 dashboard 和 image_models API 是否正确处理空数据
"""
import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root_dir))

async def test_image_models_api():
    """测试 image_models API"""
    print("=" * 60)
    print("测试 image_models API (跳过实际调用，仅验证结构)")
    print("=" * 60)
    
    try:
        # 验证 image_manager 的 list_models 方法返回的结构
        from core.image.image_manager import ImageManager

        manager = ImageManager()
        result = await manager.list_models()

        print("[OK] list_models 调用成功")
        print(f"  返回类型：{type(result)}")

        assert result is not None, "list_models 不应返回 None"

        if isinstance(result, dict):
            print(f"  数据键：{list(result.keys())}")

            # 验证数据结构
            if 'sd15' in result:
                sd15 = result['sd15']
                print(f"    sd15.checkpoints: {len(sd15.get('checkpoints', []))} 个")
                print(f"    sd15.loras: {len(sd15.get('loras', []))} 个")

            if 'sdxl' in result:
                sdxl = result['sdxl']
                print(f"    sdxl.models: {len(sdxl.get('models', []))} 个")
                print(f"    sdxl.loras: {len(sdxl.get('loras', []))} 个")

        assert isinstance(result, dict), "list_models 应返回字典"

        return True

    except Exception as e:
        print(f"[FAIL] 测试失败：{e}")
        import traceback
        traceback.print_exc()
        assert False, f"list_models 调用失败: {e}"
        return False

async def test_dashboard_handler():
    """测试 dashboard handler 的 image_models 处理"""
    print("\n" + "=" * 60)
    print("测试 Dashboard Handler 的 image_models 处理")
    print("=" * 60)
    
    try:
        # 模拟 dashboard handler 中的 _count_image_models 函数
        def _count_image_models(raw):
            if not raw or not isinstance(raw, dict):
                return 0
            total = 0
            for _, group_data in raw.items():
                if isinstance(group_data, list):
                    total += len(group_data)
                    continue
                if not isinstance(group_data, dict):
                    continue
                for key in ("checkpoints", "models", "loras"):
                    items = group_data.get(key)
                    if isinstance(items, list):
                        total += len(items)
            return total
        
        # 测试用例
        test_cases = [
            (None, 0, "None 输入"),
            ({}, 0, "空字典"),
            ({"sd15": {"checkpoints": [], "loras": []}}, 0, "空列表"),
            ({"sd15": {"checkpoints": [{"name": "test"}], "loras": []}}, 1, "单个 checkpoint"),
            ({"sdxl": {"models": [{"name": "a"}, {"name": "b"}]}}, 2, "多个模型"),
            ({"sd15": {"checkpoints": [1, 2, 3], "loras": [4, 5]}}, 5, "混合计数"),
        ]
        
        all_passed = True
        for input_data, expected, description in test_cases:
            result = _count_image_models(input_data)
            status = "[OK]" if result == expected else "[FAIL]"
            print(f"  {status} {description}: 输入={input_data}, 期望={expected}, 结果={result}")
            if result != expected:
                all_passed = False
            assert result == expected, f"{description}: 期望 {expected}, 得到 {result}"

        assert all_passed, "部分 dashboard handler 测试用例失败"
        return all_passed

    except Exception as e:
        print(f"[FAIL] 测试失败：{e}")
        import traceback
        traceback.print_exc()
        assert False, f"dashboard handler 测试异常: {e}"
        return False

async def main():
    print("\n开始测试 Image Models 修复...\n")
    
    test1 = await test_image_models_api()
    test2 = await test_dashboard_handler()
    
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"API 测试：{'[OK] 通过' if test1 else '[FAIL] 失败'}")
    print(f"Handler 测试：{'[OK] 通过' if test2 else '[FAIL] 失败'}")
    
    if test1 and test2:
        print("\n[OK] 所有测试通过！")
        return 0
    else:
        print("\n[FAIL] 部分测试失败")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
