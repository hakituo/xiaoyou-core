#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一构建所有 C++ 模块
"""

import os
import sys
import subprocess
import shutil

# C++ 模块根目录
CPP_MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cpp_modules")


def run_command(cmd, cwd=None):
    """运行命令并返回是否成功"""
    print(f"\n>>> 执行命令: {cmd}")
    try:
        subprocess.run(cmd, shell=True, cwd=cwd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 命令执行失败: {e}")
        return False


def build_cpp_scheduler():
    """构建 cpp_scheduler"""
    print("\n" + "=" * 60)
    print("📦 构建 cpp_scheduler")
    print("=" * 60)
    
    cpp_scheduler_dir = os.path.join(CPP_MODULES_DIR, "cpp_scheduler")
    build_dir = os.path.join(cpp_scheduler_dir, "build")
    
    if os.path.exists(build_dir):
        print("🧹 清理旧的构建目录...")
        shutil.rmtree(build_dir)
    
    os.makedirs(build_dir, exist_ok=True)
    
    print("🔧 配置 CMake...")
    if not run_command('cmake -S . -B build -G "Visual Studio 17 2022" -A x64', cwd=cpp_scheduler_dir):
        return False
    
    print("🔨 编译项目...")
    if not run_command("cmake --build build --config Release", cwd=cpp_scheduler_dir):
        return False
    
    print("✅ cpp_scheduler 构建完成!")
    return True


def build_cpp_bert_engine():
    """构建 cpp_bert_engine"""
    print("\n" + "=" * 60)
    print("📦 构建 cpp_bert_engine")
    print("=" * 60)
    
    cpp_bert_dir = os.path.join(CPP_MODULES_DIR, "cpp_bert_engine")
    build_dir = os.path.join(cpp_bert_dir, "build")
    
    if os.path.exists(build_dir):
        print("🧹 清理旧的构建目录...")
        shutil.rmtree(build_dir)
    
    os.makedirs(build_dir, exist_ok=True)
    
    print("🔧 配置 CMake...")
    if not run_command("cmake ..", cwd=build_dir):
        return False
    
    print("🔨 编译项目...")
    if not run_command("cmake --build . --config Release", cwd=build_dir):
        return False
    
    print("✅ cpp_bert_engine 构建完成!")
    return True


def build_cpp_audio_processor():
    """构建 cpp_audio_processor"""
    print("\n" + "=" * 60)
    print("📦 构建 cpp_audio_processor")
    print("=" * 60)
    
    cpp_audio_dir = os.path.join(CPP_MODULES_DIR, "cpp_audio_processor")
    build_dir = os.path.join(cpp_audio_dir, "build")
    
    if os.path.exists(build_dir):
        print("🧹 清理旧的构建目录...")
        shutil.rmtree(build_dir)
    
    os.makedirs(build_dir, exist_ok=True)
    
    print("🔧 配置 CMake...")
    if not run_command("cmake ..", cwd=build_dir):
        return False
    
    print("🔨 编译项目...")
    if not run_command("cmake --build . --config Release", cwd=build_dir):
        return False
    
    print("✅ cpp_audio_processor 构建完成!")
    return True


def main():
    print("🚀 开始构建所有 C++ 模块...")
    
    # 构建 cpp_scheduler（最重要）
    success = build_cpp_scheduler()
    if not success:
        print("\n❌ cpp_scheduler 构建失败!")
        return 1
    
    # 构建 cpp_bert_engine
    success = build_cpp_bert_engine()
    if not success:
        print("\n⚠️  cpp_bert_engine 构建失败，但继续其他模块...")
    
    # 构建 cpp_audio_processor
    success = build_cpp_audio_processor()
    if not success:
        print("\n⚠️  cpp_audio_processor 构建失败，但继续其他模块...")
    
    print("\n" + "=" * 60)
    print("🎉 所有模块构建完成!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

