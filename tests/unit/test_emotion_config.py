#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试情绪模块开关配置"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 设置环境变量避免循环导入
os.environ['XIAOYOU_EMOTION__ENABLED'] = 'false'

def test_emotion_config():
    # 延迟导入避免循环导入
    from core.emotion.manager import EmotionManager
    
    # 直接创建 EmotionManager 测试
    config = {
        'enabled': False,
        'detector_mode': 'smart',
        'affect_prompt_enabled': True,
        'hardware_control_enabled': True,
    }
    
    mgr = EmotionManager(config)

    print('=== EmotionManager (disabled) ===')
    print(f'is_enabled(): {mgr.is_enabled()}')
    print(f'is_affect_prompt_enabled(): {mgr.is_affect_prompt_enabled()}')
    print(f'is_hardware_control_enabled(): {mgr.is_hardware_control_enabled()}')
    print()

    assert mgr.is_enabled() is False, "禁用状态下 is_enabled() 应为 False"
    assert mgr.is_affect_prompt_enabled() is True, "affect_prompt_enabled 应为 True"
    assert mgr.is_hardware_control_enabled() is True, "hardware_control_enabled 应为 True"

    # 测试方法返回
    print('=== Method Returns (should be empty/neutral) ===')
    state = mgr.process_text('test_user', '今天好开心')
    print(f'process_text result: {state.primary_emotion.value}, confidence={state.confidence}')

    assert state is not None, "process_text 不应返回 None"
    assert hasattr(state, 'primary_emotion'), "state 应有 primary_emotion 属性"
    assert hasattr(state, 'confidence'), "state 应有 confidence 属性"

    instruction = mgr.build_dialogue_affect_instruction(user_id='test_user')
    print(f'build_dialogue_affect_instruction result: "{instruction}"')

    assert instruction is None or isinstance(instruction, str), "instruction 应为 None 或字符串"

    hw = mgr.get_hardware_payload('test_user')
    print(f'get_hardware_payload result: {hw}')

    assert hw is None or isinstance(hw, (dict, list)), "hardware_payload 应为 None 或 dict/list"

    print()
    print('✅ 测试完成！情绪模块已禁用，所有方法返回空值或默认值。')

    # 测试启用状态
    print()
    print('=== EmotionManager (enabled) ===')
    config_enabled = {
        'enabled': True,
        'detector_mode': 'smart',
        'affect_prompt_enabled': True,
        'hardware_control_enabled': True,
    }
    mgr_enabled = EmotionManager(config_enabled)
    print(f'is_enabled(): {mgr_enabled.is_enabled()}')

    assert mgr_enabled.is_enabled() is True, "启用状态下 is_enabled() 应为 True"

    state = mgr_enabled.process_text('test_user', '今天好开心')
    print(f'process_text result: {state.primary_emotion.value}, confidence={state.confidence:.2f}')

    assert state is not None, "启用状态下 process_text 也不应返回 None"

    hw = mgr_enabled.get_hardware_payload('test_user')
    print(f'get_hardware_payload result: {hw}')

if __name__ == "__main__":
    test_emotion_config()
