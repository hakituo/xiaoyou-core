#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
xiaoyou-core 安装配置脚本
用于将项目作为标准Python包安装
"""

import os
from setuptools import setup, find_packages

# 获取项目根目录
HERE = os.path.abspath(os.path.dirname(__file__))

# 读取README.md作为长描述
with open(os.path.join(HERE, 'README.md'), 'r', encoding='utf-8') as f:
    long_description = f.read()

# 读取版本号
with open(os.path.join(HERE, 'src', '__init__.py'), 'r', encoding='utf-8') as f:
    for line in f:
        if line.startswith('__version__'):
            version = line.split('=')[1].strip().strip('"')
            break
    else:
        version = '0.1.0'  # 默认版本号

# 安装要求
with open(os.path.join(HERE, 'requirements.txt'), 'r', encoding='utf-8') as f:
    install_requires = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]

setup(
    # 包基本信息
    name='xiaoyou-core',
    version=version,
    description='AI Core System for Multi-modal Interaction',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/yourusername/xiaoyou-core',  # 替换为实际GitHub URL
    author='Your Name',  # 替换为实际作者名
    author_email='your.email@example.com',  # 替换为实际邮箱
    license='MIT',
    
    # 项目分类
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
    ],
    
    # Python版本要求
    python_requires='>=3.9',
    
    # 包发现
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    
    # 安装依赖
    install_requires=install_requires,
    
    # 可选依赖
    extras_require={
        'dev': [
            'pytest>=7.3.0',
            'black>=23.3.0',
            'flake8>=6.0.0',
            'mypy>=1.3.0',
            'pre-commit>=3.3.0',
        ],
        'docs': [
            'sphinx>=6.1.0',
            'sphinx-rtd-theme>=1.2.0',
        ],
        'audio': [
            'pyaudio>=0.2.13',
            'soundfile>=0.12.0',
            'pydub>=0.25.0',
        ],
        'image': [
            'pillow>=9.4.0',
            'opencv-python>=4.7.0.72',
        ],
        'redis': [
            'redis>=4.5.0',
        ],
    },
    
    # 入口点（命令行工具）
    entry_points={
        'console_scripts': [
            'xiaoyou=src.cli.main:main',
        ],
    },
    
    # 数据文件
    include_package_data=True,
    package_data={
        'xiaoyou': ['config/*', 'data/*'],
    },
    
    # 项目URL
    project_urls={
        'Bug Reports': 'https://github.com/yourusername/xiaoyou-core/issues',
        'Source': 'https://github.com/yourusername/xiaoyou-core',
    },
)