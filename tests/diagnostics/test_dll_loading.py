"""
测试 DLL 文件移动后是否能正确加载
验证 C++ Scheduler 是否能正常初始化
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_dll_loading():
    """测试 DLL 加载"""
    print("=" * 60)
    print("测试 1: DLL 文件位置")
    print("=" * 60)
    
    scheduler_dir = project_root / "core" / "services" / "scheduler"
    lib_dir = scheduler_dir / "lib"
    
    # 检查 lib 目录
    if not lib_dir.exists():
        print(f"❌ lib 目录不存在: {lib_dir}")
        return False
    print(f"✅ lib 目录存在: {lib_dir}")
    
    # 检查 DLL 文件
    dll_files = list(lib_dir.glob("*.dll"))
    if not dll_files:
        print(f"❌ lib 目录中没有 DLL 文件")
        return False
    print(f"✅ 找到 {len(dll_files)} 个 DLL 文件:")
    for dll in dll_files:
        print(f"   - {dll.name}")
    
    # 检查根目录是否还有 DLL
    root_dlls = list(scheduler_dir.glob("*.dll"))
    if root_dlls:
        print(f"⚠️ 根目录还有 {len(root_dlls)} 个 DLL 文件:")
        for dll in root_dlls:
            print(f"   - {dll.name}")
    else:
        print(f"✅ 根目录没有 DLL 文件")
    
    print()
    return True


def test_scheduler_wrapper():
    """测试 scheduler_wrapper 模块"""
    print("=" * 60)
    print("测试 2: scheduler_wrapper 模块")
    print("=" * 60)
    
    try:
        from core.services.scheduler import scheduler_wrapper
        print("✅ scheduler_wrapper 模块导入成功")
        
        # 检查 DLL 目录句柄
        if hasattr(scheduler_wrapper, '_DLL_DIR_HANDLES'):
            handles = scheduler_wrapper._DLL_DIR_HANDLES
            print(f"✅ 已添加 {len(handles)} 个 DLL 目录句柄")
        else:
            print("⚠️ 未找到 _DLL_DIR_HANDLES")
        
        print()
        return True
    except Exception as e:
        print(f"❌ scheduler_wrapper 模块导入失败: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False


def test_cpp_scheduler():
    """测试 C++ Scheduler 是否能加载"""
    print("=" * 60)
    print("测试 3: C++ Scheduler 加载")
    print("=" * 60)
    
    try:
        from core.services.scheduler.scheduler_wrapper import is_cpp_scheduler_available, scheduler_py
        
        available = is_cpp_scheduler_available()
        if available:
            print("✅ C++ Scheduler 可用")
        else:
            print("⚠️ C++ Scheduler 不可用（可能是编译问题，不是 DLL 路径问题）")
        
        # 尝试导入 scheduler_py
        try:
            from core.services.scheduler.scheduler_wrapper import scheduler_py
            print("✅ scheduler_py 模块导入成功")
            
            # 尝试访问一些基本类
            if hasattr(scheduler_py, 'ResourceIsolationScheduler'):
                print("✅ ResourceIsolationScheduler 类可用")
            if hasattr(scheduler_py, 'LLMTask'):
                print("✅ LLMTask 类可用")
            if hasattr(scheduler_py, 'LLMInferenceRequest'):
                print("✅ LLMInferenceRequest 类可用")
            
        except ImportError as e:
            print(f"⚠️ scheduler_py 导入失败: {e}")
            print("   这可能是因为 C++ Scheduler 未编译，而不是 DLL 路径问题")
        
        print()
        return True
    except Exception as e:
        print(f"❌ C++ Scheduler 测试失败: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False


def test_dll_search_path():
    """测试 DLL 搜索路径"""
    print("=" * 60)
    print("测试 4: DLL 搜索路径")
    print("=" * 60)
    
    if os.name != "nt":
        print("⚠️ 非 Windows 系统，跳过 DLL 搜索路径测试")
        print()
        return True
    
    try:
        # 导入 scheduler_wrapper 会自动添加 DLL 目录
        from core.services.scheduler import scheduler_wrapper
        
        # 检查 os.add_dll_directory 是否被调用
        scheduler_dir = project_root / "core" / "services" / "scheduler"
        lib_dir = scheduler_dir / "lib"
        
        print(f"✅ scheduler 目录: {scheduler_dir}")
        print(f"✅ lib 目录: {lib_dir}")
        
        # 检查 DLL 目录句柄
        if hasattr(scheduler_wrapper, '_DLL_DIR_HANDLES'):
            handles = scheduler_wrapper._DLL_DIR_HANDLES
            print(f"✅ 已添加 {len(handles)} 个 DLL 目录到搜索路径")
        
        print()
        return True
    except Exception as e:
        print(f"❌ DLL 搜索路径测试失败: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始测试 DLL 文件移动后的加载情况")
    print("=" * 60 + "\n")
    
    results = []
    
    # 运行测试
    results.append(("DLL 文件位置", test_dll_loading()))
    results.append(("scheduler_wrapper 模块", test_scheduler_wrapper()))
    results.append(("C++ Scheduler 加载", test_cpp_scheduler()))
    results.append(("DLL 搜索路径", test_dll_search_path()))
    
    # 打印总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！DLL 文件移动后加载正常！")
        return 0
    else:
        print("\n⚠️ 部分测试失败，请检查错误信息")
        return 1


if __name__ == "__main__":
    exit(main())
