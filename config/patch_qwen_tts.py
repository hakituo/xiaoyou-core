#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qwen_tts 兼容性补丁脚本

修复 qwen_tts 0.1.1 与 transformers 4.57.3 的兼容性问题。
重装 qwen_tts 或 transformers 后需要重新运行此脚本。

兼容问题列表：
1. create_causal_mask() 参数名 inputs_embeds → input_embeds
2. create_causal_mask() 缺少必需参数 cache_position
3. @check_model_inputs 装饰器调用方式不匹配（需加括号）

用法：
    python config/patch_qwen_tts.py
"""

import os
import sys

# 目标文件
SITE_PACKAGES = os.path.join(
    os.path.dirname(sys.executable), "..", "Lib", "site-packages"
)
if not os.path.isdir(SITE_PACKAGES):
    # Linux/Mac 路径
    SITE_PACKAGES = os.path.join(
        os.path.dirname(sys.executable), "..", "lib",
        f"python{sys.version_info.major}.{sys.version_info.minor}",
        "site-packages"
    )

MODELING_FILE = os.path.join(
    SITE_PACKAGES, "qwen_tts", "core", "models", "modeling_qwen3_tts.py"
)
TOKENIZER_FILE = os.path.join(
    SITE_PACKAGES, "qwen_tts", "core", "tokenizer_12hz",
    "modeling_qwen3_tts_tokenizer_v2.py"
)


def patch_file(filepath, old, new, description):
    """在文件中替换文本"""
    if not os.path.exists(filepath):
        print(f"  [跳过] 文件不存在: {filepath}")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if new in content:
        print(f"  [已修复] {description}")
        return True

    if old not in content:
        print(f"  [无需修复] {description} (未找到旧代码，可能已在新版中修正)")
        return True

    content = content.replace(old, new)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [已修复] {description}")
    return True


def main():
    print("=" * 50)
    print("qwen_tts 兼容性补丁 (transformers 4.57.3)")
    print("=" * 50)

    patches_applied = 0

    # === 补丁 1: modeling_qwen3_tts.py ===
    print(f"\n[1] 修补 {MODELING_FILE}")

    # 1a: mask_kwargs 中的 inputs_embeds → input_embeds + 添加 cache_position
    patches_applied += patch_file(
        MODELING_FILE,
        '''            mask_kwargs = {
                "config": self.config,
                "inputs_embeds": inputs_embeds,
                "attention_mask": attention_mask,
                "past_key_values": past_key_values,
            }''',
        '''            mask_kwargs = {
                "config": self.config,
                "input_embeds": inputs_embeds,
                "attention_mask": attention_mask,
                "cache_position": cache_position,
                "past_key_values": past_key_values,
            }''',
        "mask_kwargs: inputs_embeds → input_embeds + 添加 cache_position"
    )

    # 1b: 直接传参的 inputs_embeds → input_embeds + 添加 cache_position
    patches_applied += patch_file(
        MODELING_FILE,
        '''        causal_mask = mask_function(
            config=self.config,
            inputs_embeds=inputs_embeds,
            attention_mask=attention_mask,
            past_key_values=past_key_values,
            position_ids=text_position_ids,
        )''',
        '''        causal_mask = mask_function(
            config=self.config,
            input_embeds=inputs_embeds,
            attention_mask=attention_mask,
            cache_position=cache_position,
            past_key_values=past_key_values,
            position_ids=text_position_ids,
        )''',
        "直接传参: inputs_embeds → input_embeds + 添加 cache_position"
    )

    # === 补丁 2: modeling_qwen3_tts_tokenizer_v2.py ===
    print(f"\n[2] 修补 {TOKENIZER_FILE}")

    # 2a: mask_kwargs 中的 inputs_embeds → input_embeds + 添加 cache_position
    patches_applied += patch_file(
        TOKENIZER_FILE,
        '''            mask_kwargs = {
                "config": self.config,
                "inputs_embeds": inputs_embeds,
                "attention_mask": attention_mask,
                "past_key_values": past_key_values,
                "position_ids": position_ids,
            }''',
        '''            mask_kwargs = {
                "config": self.config,
                "input_embeds": inputs_embeds,
                "attention_mask": attention_mask,
                "cache_position": cache_position,
                "past_key_values": past_key_values,
                "position_ids": position_ids,
            }''',
        "tokenizer mask_kwargs: inputs_embeds → input_embeds + 添加 cache_position"
    )

    # 2b: @check_model_inputs → @check_model_inputs()
    patches_applied += patch_file(
        TOKENIZER_FILE,
        "    @check_model_inputs\n    @auto_docstring",
        "    @check_model_inputs()\n    @auto_docstring",
        "@check_model_inputs → @check_model_inputs()"
    )

    print(f"\n{'=' * 50}")
    print(f"补丁完成！共处理 {patches_applied} 处")
    print("=" * 50)

    # 验证
    print("\n[验证] 检查关键文件...")
    errors = []

    for filepath in [MODELING_FILE, TOKENIZER_FILE]:
        if not os.path.exists(filepath):
            errors.append(f"文件不存在: {filepath}")
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        # 检查是否还有未修复的旧代码
        if '"inputs_embeds": inputs_embeds,' in content and "create_causal_mask" in content:
            errors.append(f"{filepath} 中仍有未修复的 inputs_embeds")

    if errors:
        print("  [警告] 以下问题需要手动检查:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  所有补丁已正确应用！")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
