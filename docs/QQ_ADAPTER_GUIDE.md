# QQ 接入模块配置与部署指南

本文档详细介绍了 xiaoyou-core 项目中 QQ 接入模块的配置方法、部署流程以及最佳实践。

## 架构概述

QQ 接入模块采用以下架构：

- **go-cqhttp**: 负责 QQ 协议层通信，处理登录、消息收发等底层功能
- **FastAPI 服务**: 作为中间适配器，接收 go-cqhttp 推送的消息，调用核心模型，返回生成结果

```
QQ客户端 <---> go-cqhttp <---> FastAPI服务(qq_adapter.py) <---> xiaoyou-core核心模块
```

## 环境要求

- Python 3.8+
- FastAPI、httpx、uvicorn
- go-cqhttp (需单独下载安装)

## 第一部分：go-cqhttp 配置

### 1. 下载与安装 go-cqhttp

1. 前往 [go-cqhttp 官方仓库](https://github.com/Mrs4s/go-cqhttp/releases) 下载适合你系统的最新版本
2. 解压到任意位置，运行可执行文件生成配置文件

### 2. 配置 go-cqhttp

编辑 `config.yml` 文件，配置以下关键部分：

```yaml
# 账号配置
account:
  uin: 1234567890  # 你的QQ账号
  password: ''     # 密码为空将使用扫码登录
  encrypt: false
  status: 0
  relogin:
    delay: 3       # 重连延迟
    interval: 3    # 重连间隔
    max-times: 0   # 0表示无限重试

# HTTP 通信配置
servers:
  - http:
      host: 127.0.0.1
      port: 5700
      timeout: 5
      long-polling:
        enabled: false
        max-queue-size: 2000
      middlewares:
        <<: *default
      post:
        - url: "http://127.0.0.1:8000/qq/callback"  # 指向 FastAPI 服务的回调地址
          secret: "your_webhook_token"  # 与 FastAPI 配置中的 webhook_token 保持一致
```

### 3. 启动 go-cqhttp

运行 go-cqhttp 可执行文件，首次启动会要求扫码登录。登录成功后，保持程序运行。

## 第二部分：xiaoyou-core QQ 适配器配置

### 1. 安装依赖

```bash
pip install fastapi httpx uvicorn
```

### 2. 配置文件设置

在 xiaoyou-core 的主配置文件中添加 QQ 机器人相关配置：

```json
{
  "qq_bot": {
    "enabled": true,
    "go_cqhttp_api": "http://127.0.0.1:5700",
    "webhook_token": "your_webhook_token",  // 与 go-cqhttp 中的 secret 一致
    
    // 安全配置
    "ip_whitelist": ["127.0.0.1", "192.168.1.0/24"],  // 支持IP或CIDR格式
    "max_request_size": 1048576,  // 1MB
    
    // 限流配置
    "rate_limit_window": 3,  // 秒
    "max_concurrent_per_user": 1,
    "max_tts_concurrent": 3,
    "global_rate_limit": 30  // 每分钟请求数
  }
}
```

### 3. 配置说明

#### 基本配置
- `enabled`: 是否启用QQ机器人
- `go_cqhttp_api`: go-cqhttp API地址
- `webhook_token`: 用于验证请求合法性的密钥

#### 安全配置
- `ip_whitelist`: 允许访问的IP白名单，支持单个IP和CIDR格式
- `max_request_size`: 最大请求体大小（字节）

#### 限流配置
- `rate_limit_window`: 单个用户请求限流窗口（秒）
- `max_concurrent_per_user`: 每用户最大并发数
- `max_tts_concurrent`: TTS生成最大并发数
- `global_rate_limit`: 全局请求频率限制（每分钟）

## 第三部分：部署流程

### 1. 启动 QQ 适配器服务

使用 uvicorn 启动 FastAPI 服务：

```bash
cd d:\AI\xiaoyou-core
echo "from bots.qq_adapter import app

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)" > start_qq_adapter.py

python start_qq_adapter.py
```

### 2. 生产环境部署（可选）

对于生产环境，推荐使用 gunicorn 配合 uvicorn worker：

```bash
pip install gunicorn

# 启动服务
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8000 "bots.qq_adapter:app"
```

### 3. 使用 Nginx 反向代理（推荐）

配置 Nginx 作为反向代理，提供更好的性能和安全性：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 限流配置
        limit_req zone=one burst=10 nodelay;
    }
}

# 限流配置
limit_req_zone $binary_remote_addr zone=one:10m rate=30r/m;
```

## 第四部分：安全最佳实践

### 1. 密钥管理
- 使用强随机生成的 `webhook_token`
- 定期更换密钥
- 不要在代码或日志中明文显示密钥

### 2. IP 限制
- 严格限制 `ip_whitelist`，只允许 go-cqhttp 服务器的 IP 访问
- 生产环境避免使用 `0.0.0.0` 监听地址

### 3. 请求验证
- 始终验证请求的 token 和 IP
- 限制请求体大小，防止拒绝服务攻击
- 实施请求频率限制

### 4. 日志管理
- 定期检查安全日志（位于 `logs/security.log`）
- 监控异常访问模式
- 日志中敏感信息脱敏

## 第五部分：故障排除

### 常见问题与解决方案

#### 1. go-cqhttp 无法推送消息到 FastAPI 服务
- 检查网络连接和防火墙设置
- 确认 webhook_token 配置一致
- 验证回调 URL 是否正确

#### 2. 消息处理延迟或失败
- 检查并发配置是否合理
- 查看系统资源使用情况
- 检查模型服务是否正常运行

#### 3. 安全相关错误
- 检查 IP 白名单配置
- 验证 token 是否过期或不一致
- 检查是否触发了请求频率限制

### 日志查看

- QQ 适配器日志：`logs/qq_bot.log`
- 安全日志：`logs/security.log`
- go-cqhttp 日志：go-cqhttp 安装目录下的日志文件

## 第六部分：扩展与自定义

### 1. 添加新的消息处理逻辑

在 `qq_adapter.py` 中，你可以自定义 `process_message_event` 函数来实现特定的消息处理逻辑。

### 2. 支持更多消息类型

当前适配器支持文本消息和语音消息，你可以扩展代码以支持图片、文件等其他消息类型。

### 3. 自定义回复策略

可以修改 `should_reply` 函数来实现更复杂的回复判断逻辑，例如根据关键词、用户角色等决定是否回复。

## 版本信息

- 文档版本：v1.0
- 最后更新：2023-09-15

---

本文档由 xiaoyou-core 开发团队编写。如有问题或建议，请提交 issue 或联系开发团队。