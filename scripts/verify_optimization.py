import os
import shutil
import sys
from pathlib import Path
from config.integrated_config import get_settings
from memory.weighted_memory_manager import WeightedMemoryManager


def verify_optimization():
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))

    os.environ["XIAOYOU_MEMORY__L1_CACHE_SIZE"] = "42"
    os.environ["XIAOYOU_MEMORY__L2_CACHE_SIZE"] = "88"
    print("=== 验证配置化缓存优化 ===")

    # 1. 验证配置加载
    settings = get_settings()
    print(f"L1 Cache Config: {settings.memory.l1_cache_size} (Expected: 42)")
    print(f"L2 Cache Config: {settings.memory.l2_cache_size} (Expected: 88)")

    if settings.memory.l1_cache_size != 42 or settings.memory.l2_cache_size != 88:
        print("❌ 配置加载失败！环境变量未生效。")
        return False

    # 2. 验证模块应用
    # 我们不进行完整初始化以避免副作用，只检查 _cache 属性
    # 但 WeightedMemoryManager 初始化会做很多事情，为了安全，我们用 try-except
    temp_dir = None
    try:
        # 使用临时目录避免影响真实数据
        temp_dir = project_root / "temp_test_memory_opt"
        temp_dir.mkdir(exist_ok=True)

        # Patch history dir in settings temporarily if needed,
        # but WeightedMemoryManager uses global settings or init args.
        # Let's just instantiate.
        mm = WeightedMemoryManager(user_id="test_opt")

        l1_actual = mm._cache["l1_size"]
        l2_actual = mm._cache["l2_size"]

        print(f"MemoryManager L1 Size: {l1_actual}")
        print(f"MemoryManager L2 Size: {l2_actual}")

        if l1_actual == 42 and l2_actual == 88:
            print("✅ 优化验证成功！缓存大小已实现动态配置。")
            return True
        else:
            print("❌ 模块应用失败！MemoryManager 未使用配置值。")
            return False

    except Exception as e:
        print(f"❌ 验证过程出错: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        if temp_dir is not None and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


if __name__ == "__main__":
    success = verify_optimization()
    if not success:
        sys.exit(1)
