"""core.utils.logging 子包。

将原本臃肿的 core.utils.logger 模块按职责拆分为：
- handlers  : 安全/跨天文件 Handler 实现
- formatters: 日志格式化器
- config    : 配置加载与按日目录解析
- context   : request_id 上下文
- registry  : Handler 注册中心 + QueueListener 运行时管理（状态中枢）

core.utils.logger 作为对外兼容入口，re-export 上述能力。
"""
