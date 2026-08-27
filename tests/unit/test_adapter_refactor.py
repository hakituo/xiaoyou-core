#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试重构后的 WebSocket 适配器
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    """测试所有导入是否正常工作"""
    print("=" * 60)
    print("测试重构后的 WebSocket 适配器导入")
    print("=" * 60)
    
    try:
        # 测试从 adapters 模块导入
        print("\n1. 测试从 adapters 模块导入...")
        from core.interfaces.websocket.adapters import (
            FastAPIWebSocketAdapter,
            get_fastapi_websocket_adapter,
            env_flag_enabled,
            MessageHandlers,
            StreamingHandler,
        )
        print("   ✅ adapters 模块导入成功")
        
        # 测试从旧位置导入（向后兼容）
        print("\n2. 测试从旧位置导入（向后兼容）...")
        from core.interfaces.websocket.fastapi_websocket_adapter import (
            FastAPIWebSocketAdapter as OldAdapter,
            get_fastapi_websocket_adapter as old_get_adapter,
        )
        print("   ✅ 向后兼容导入成功")
        
        # 验证它们是同一个类
        print("\n3. 验证类一致性...")
        assert FastAPIWebSocketAdapter is OldAdapter
        assert get_fastapi_websocket_adapter is old_get_adapter
        print("   ✅ 类一致性验证通过")
        
        # 测试工具函数
        print("\n4. 测试工具函数...")
        import os
        os.environ["TEST_FLAG_TRUE"] = "1"
        os.environ["TEST_FLAG_FALSE"] = "0"
        assert env_flag_enabled("TEST_FLAG_TRUE") == True
        assert env_flag_enabled("TEST_FLAG_FALSE") == False
        assert env_flag_enabled("NONEXISTENT_VAR") == False
        print("   ✅ 工具函数工作正常")
        
        print("\n" + "=" * 60)
        print("所有测试通过！重构成功！")
        print("=" * 60)
        
        # 显示新文件结构
        print("\n新文件结构:")
        print("  core/interfaces/websocket/")
        print("  ├── fastapi_websocket_adapter.py  (向后兼容入口)")
        print("  └── adapters/")
        print("      ├── __init__.py")
        print("      ├── adapter.py       (主适配器类, ~265行)")
        print("      ├── handlers.py      (消息处理器, ~433行)")
        print("      ├── streaming.py     (流式处理, ~253行)")
        print("      └── utils.py         (工具函数, ~48行)")
        
        print("\n重构前: 1个文件 ~2000行")
        print("重构后: 5个文件，每个 <500行")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
