# 项目代码风格指南

本文档定义了 xiaoyou-core 项目的代码风格规范，所有团队成员在开发过程中应当遵循这些规范，以确保代码的一致性和可读性。

## 1. 语言选择

- 主要开发语言：Python 3.8+
- 配置文件格式：YAML（优先），JSON（辅助）
- 前端代码：JavaScript/HTML/CSS

## 2. 命名约定

### 2.1 Python 命名规范

- **变量和函数名**：使用下划线分隔的小写字母（snake_case）
  ```python
  # 正确示例
  user_id = 123
  def get_user_data():
      pass
  ```

- **类名**：使用首字母大写的驼峰命名法（PascalCase）
  ```python
  # 正确示例
  class UserManager:
      pass
  ```

- **常量**：使用全大写字母，下划线分隔
  ```python
  # 正确示例
  MAX_CONNECTIONS = 100
  DEFAULT_TIMEOUT = 30
  ```

- **模块和文件名**：使用小写字母，下划线分隔
  ```python
  # 正确示例
  user_service.py
  data_processor.py
  ```

- **包名**：使用小写字母，不使用下划线
  ```python
  # 正确示例
  import core.utils
  import web.services
  ```

### 2.2 其他语言命名规范

- **JavaScript**：使用小驼峰命名法（camelCase），类名使用 PascalCase
- **HTML/CSS**：使用短横线分隔的小写字母（kebab-case）

## 3. 代码格式

### 3.1 缩进

- 使用 4 个空格进行缩进，不使用制表符（tab）

### 3.2 行长度

- 每行代码长度不应超过 88 个字符（符合 PEP 8 标准）
- 长行应该进行适当的换行，遵循以下规则：
  - 在二元运算符前换行
  - 使用括号进行分组，避免使用反斜杠进行换行
  
  ```python
  # 正确示例
  total = (
      first_variable + second_variable
      + third_variable - fourth_variable
  )
  ```

### 3.3 空行

- 类定义和函数定义之间使用两个空行
- 函数内部的逻辑块之间使用一个空行
- 文件末尾保留一个空行

### 3.4 导入语句

- 导入语句按以下顺序分组，每组之间用空行分隔：
  1. 标准库导入
  2. 第三方库导入
  3. 项目内部模块导入

- 使用绝对导入而非相对导入（除非是同一包内的子模块）

```python
# 正确示例
import os
import sys
import asyncio

import numpy as np
from fastapi import FastAPI

from core.utils.logger import get_logger
from web.routes import router
```

## 4. 注释

### 4.1 文档字符串（Docstrings）

- 所有公共模块、类、函数和方法都必须有文档字符串
- 使用 Google 风格的文档字符串

```python
# 正确示例
def process_data(data, threshold=0.5):
    """
    处理输入数据，根据阈值过滤结果
    
    Args:
        data: 要处理的数据列表
        threshold: 过滤阈值，默认为0.5
        
    Returns:
        过滤后的结果列表
        
    Raises:
        ValueError: 当输入数据格式不正确时
    """
    pass
```

### 4.2 行内注释

- 行内注释应该简洁明了，用于解释复杂的逻辑或算法
- 注释与代码之间至少有两个空格

```python
# 正确示例
total = 0  # 初始化计数器
```

## 5. 代码组织

### 5.1 类结构

- 类的方法按以下顺序组织：
  1. 特殊方法（`__init__`, `__str__` 等）
  2. 静态方法和类方法
  3. 属性方法（`@property`）
  4. 公共方法
  5. 私有方法（以单下划线 `_` 开头）

### 5.2 函数结构

- 函数应该简短，每个函数只负责一个任务
- 函数参数不应过多，推荐不超过5个参数
- 优先使用默认参数和关键字参数提高可读性

## 6. 错误处理

- 使用 `try-except` 块捕获特定异常，而不是捕获所有异常
- 使用统一的错误处理模块：`core.utils.error_handler`
- 抛出异常时，提供清晰的错误消息，说明发生了什么错误以及可能的原因

```python
# 推荐方式
from core.utils.error_handler import with_error_handling

@with_error_handling(error_message="处理数据失败", re_raise=True)
def process_data(data):
    # 处理逻辑
    pass
```

## 7. 日志记录

- 使用统一的日志模块：`core.utils.logger`
- 选择适当的日志级别：DEBUG、INFO、WARNING、ERROR、CRITICAL
- 日志消息应该清晰描述发生了什么，包含足够的上下文信息

```python
# 正确示例
from core.utils.logger import get_logger

logger = get_logger("MODULE_NAME")

logger.info(f"处理用户请求: user_id={user_id}")
logger.error(f"数据库连接失败: {error}")
```

## 8. 配置管理

- 使用统一的配置管理模块：`config.integrated_config`
- 避免硬编码配置值
- 区分开发环境和生产环境配置

## 9. 格式化工具

- 使用 `black` 进行代码格式化
- 使用 `isort` 管理导入语句
- 使用 `flake8` 检查代码质量

推荐的格式化命令：
```bash
black .
isort .
flake8 .
```

## 10. 版本控制

- 提交信息应该简洁明了，描述具体的更改内容
- 遵循提交信息规范：`类型: 简短描述`
  - 类型包括：feat（新功能）、fix（修复bug）、docs（文档更改）、style（代码风格）、refactor（代码重构）、chore（杂项更改）

---

遵循这些代码风格规范有助于提高代码的可读性、可维护性和一致性，同时也能减少潜在的错误和技术债务。