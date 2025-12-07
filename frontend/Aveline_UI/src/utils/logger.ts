// 前端日志服务

// 日志级别枚举
export enum LogLevel {
  DEBUG = 'DEBUG',
  INFO = 'INFO',
  WARN = 'WARN',
  ERROR = 'ERROR',
  CRITICAL = 'CRITICAL'
}

// 日志配置接口
interface LoggerConfig {
  level: LogLevel;
  enableConsole: boolean;
  enablePerformanceTracking: boolean;
  sanitizeSensitiveInfo: boolean;
  maxMessageLength: number;
}

// 默认配置
const DEFAULT_CONFIG: LoggerConfig = {
  level: LogLevel.INFO,
  enableConsole: true,
  enablePerformanceTracking: true,
  sanitizeSensitiveInfo: true,
  maxMessageLength: 1000
};

// 日志级别数值映射，用于比较
const LOG_LEVEL_VALUES: Record<LogLevel, number> = {
  [LogLevel.DEBUG]: 10,
  [LogLevel.INFO]: 20,
  [LogLevel.WARN]: 30,
  [LogLevel.ERROR]: 40,
  [LogLevel.CRITICAL]: 50
};

// 敏感信息正则表达式
const SENSITIVE_PATTERNS: Record<string, RegExp> = {
  token: /(token|access_key|secret|password|credential|api[_-]?key)\s*[:=]\s*["']?([^"'\s]{6,})["']?/gi,
  email: /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
  phone: /\b(\d{11}|\+?\d{1,4}[\s-]?\(?\d{1,3}\)?[\s-]?\d{1,4}[\s-]?\d{1,4})\b/g,
  id: /\b(ID|身份证|证件)[:：]\s*([A-Za-z0-9-]{6,})\b/g
};

// 性能跟踪类
class PerformanceTracker {
  private startTimeMap: Map<string, number> = new Map();
  
  start(id: string): void {
    this.startTimeMap.set(id, performance.now());
  }
  
  end(id: string): { duration: number; exists: boolean } {
    const startTime = this.startTimeMap.get(id);
    if (startTime !== undefined) {
      this.startTimeMap.delete(id);
      return {
        duration: performance.now() - startTime,
        exists: true
      };
    }
    return { duration: 0, exists: false };
  }
  
  clear(id?: string): void {
    if (id) {
      this.startTimeMap.delete(id);
    } else {
      this.startTimeMap.clear();
    }
  }
}

// 日志记录器类
class Logger {
  private config: LoggerConfig;
  private performanceTracker: PerformanceTracker;
  private sessionId: string;
  
  constructor(config: Partial<LoggerConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.performanceTracker = new PerformanceTracker();
    this.sessionId = this.generateSessionId();
    
    // 记录应用启动信息
    this.info('Logger initialized', { 
      sessionId: this.sessionId,
      level: this.config.level 
    });
  }
  
  // 生成会话ID
  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
  }
  
  // 获取时间戳字符串
  private getTimestamp(): string {
    const now = new Date();
    return now.toISOString();
  }
  
  // 清理敏感信息
  private sanitize(data: any): any {
    if (!this.config.sanitizeSensitiveInfo) {
      return data;
    }
    
    if (typeof data === 'string') {
      let sanitized = data;
      
      // 替换所有敏感模式
      Object.values(SENSITIVE_PATTERNS).forEach(pattern => {
        sanitized = sanitized.replace(pattern, (match: string, key: string, value: any) => {
          // 确保 value 是字符串类型
          const stringValue = String(value);
          // 只保留前3个和后3个字符，中间用星号替换
          const visibleChars = 3;
          if (stringValue.length <= visibleChars * 2) {
            return `${key}: ***`;
          }
          const maskedValue = stringValue.substring(0, visibleChars) + 
            '*'.repeat(Math.min(stringValue.length - visibleChars * 2, 10)) + 
            stringValue.substring(stringValue.length - visibleChars);
          return `${key}: ${maskedValue}`;
        });
      });
      
      // 限制消息长度
      if (typeof sanitized === 'string' && sanitized.length > this.config.maxMessageLength) {
        sanitized = sanitized.substring(0, this.config.maxMessageLength) + '... (truncated)';
      }
      
      return sanitized;
    }
    
    // 处理对象，递归清理
      if (typeof data === 'object' && data !== null) {
        if (Array.isArray(data)) {
          return data.map(item => this.sanitize(item));
        } else {
          const cloned: Record<string, any> = {};
          
          Object.keys(data).forEach(key => {
            // 检查键名是否包含敏感信息
            const lowerKey = key.toLowerCase();
            if (lowerKey.includes('password') || 
                lowerKey.includes('token') || 
                lowerKey.includes('secret') ||
                lowerKey.includes('key') ||
                lowerKey.includes('credential')) {
              cloned[key] = '***';
            } else {
              cloned[key] = this.sanitize(data[key]);
            }
          });
          
          return cloned;
        }
      }
    
    return data;
  }
  
  // 格式化日志消息
  private formatLog(level: LogLevel, message: string, meta?: any): string {
    const timestamp = this.getTimestamp();
    const sanitizedMeta = meta ? this.sanitize(meta) : undefined;
    
    let logStr = `[${timestamp}] [${level}] [${this.sessionId}] ${message}`;
    
    if (sanitizedMeta) {
      try {
        logStr += ' ' + JSON.stringify(sanitizedMeta);
      } catch (e) {
        logStr += ' [Meta object could not be stringified]';
      }
    }
    
    return logStr;
  }
  
  // 判断是否应该记录该级别的日志
  private shouldLog(level: LogLevel): boolean {
    return LOG_LEVEL_VALUES[level] >= LOG_LEVEL_VALUES[this.config.level];
  }
  
  // 执行日志记录
  private log(level: LogLevel, message: string, meta?: any): void {
    if (!this.shouldLog(level)) {
      return;
    }
    
    const logMessage = this.formatLog(level, message, meta);
    
    // 输出到控制台
    if (this.config.enableConsole) {
      switch (level) {
        case LogLevel.DEBUG:
          console.debug(logMessage);
          break;
        case LogLevel.INFO:
          console.info(logMessage);
          break;
        case LogLevel.WARN:
          console.warn(logMessage);
          break;
        case LogLevel.ERROR:
        case LogLevel.CRITICAL:
          console.error(logMessage);
          break;
      }
    }
    
    // 这里可以扩展到发送到服务器或其他存储位置
    // 例如: this.sendToServer(level, logMessage);
  }
  
  // 日志方法
  debug(message: string, meta?: any): void {
    this.log(LogLevel.DEBUG, message, meta);
  }
  
  info(message: string, meta?: any): void {
    this.log(LogLevel.INFO, message, meta);
  }
  
  warn(message: string, meta?: any): void {
    this.log(LogLevel.WARN, message, meta);
  }
  
  error(message: string, error?: Error | any, meta?: any): void {
    const errorInfo = error ? {
      name: error.name || 'Error',
      message: error.message,
      stack: this.config.level === LogLevel.DEBUG ? error.stack : undefined
    } : undefined;
    
    this.log(LogLevel.ERROR, message, {
      ...errorInfo,
      ...meta
    });
  }
  
  critical(message: string, error?: Error | any, meta?: any): void {
    const errorInfo = error ? {
      name: error.name || 'Error',
      message: error.message,
      stack: error.stack
    } : undefined;
    
    this.log(LogLevel.CRITICAL, message, {
      ...errorInfo,
      ...meta
    });
  }
  
  // 性能跟踪方法
  startTimer(id: string): void {
    if (!this.config.enablePerformanceTracking) {
      return;
    }
    this.performanceTracker.start(id);
  }
  
  endTimer(id: string, operation?: string, meta?: any): number | null {
    if (!this.config.enablePerformanceTracking) {
      return null;
    }
    
    const result = this.performanceTracker.end(id);
    if (result.exists) {
      const duration = result.duration;
      
      // 如果操作名称存在，记录性能信息
      if (operation) {
        this.info(`${operation} completed`, {
          duration: `${duration.toFixed(2)}ms`,
          ...meta
        });
      }
      
      return duration;
    }
    
    return null;
  }
  
  // 记录API请求
  logApiRequest(endpoint: string, method: string, requestId?: string, data?: any): void {
    this.info('API request', {
      endpoint,
      method,
      requestId,
      data: this.sanitize(data)
    });
  }
  
  // 记录API响应
  logApiResponse(endpoint: string, method: string, requestId?: string, 
                statusCode?: number, duration?: number, data?: any): void {
    const meta: any = {
      endpoint,
      method,
      requestId,
      statusCode
    };
    
    if (duration !== undefined) {
      meta.duration = `${duration.toFixed(2)}ms`;
    }
    
    if (statusCode && statusCode >= 400) {
      this.warn('API response error', {
        ...meta,
        errorData: this.sanitize(data)
      });
    } else {
      // 对成功响应，只在DEBUG级别记录详细数据
      if (this.config.level === LogLevel.DEBUG) {
        meta.responseData = this.sanitize(data);
      }
      this.info('API response', meta);
    }
  }
  
  // 记录错误
  logError(context: string, error: any, additionalInfo?: any): void {
    const errorType = error?.constructor?.name || 'UnknownError';
    const errorMessage = error?.message || String(error);
    const stack = this.config.level === LogLevel.DEBUG ? error?.stack : undefined;
    
    this.error(`${context} - ${errorType}: ${errorMessage}`, undefined, {
      errorType,
      stack,
      additionalInfo: this.sanitize(additionalInfo)
    });
  }
  
  // 更新配置
  updateConfig(config: Partial<LoggerConfig>): void {
    this.config = { ...this.config, ...config };
    this.info('Logger config updated', { newConfig: this.config });
  }
  
  // 获取当前会话ID
  getSessionId(): string {
    return this.sessionId;
  }
}

// 创建全局日志实例
const logger = new Logger();

// 导出日志器和工具函数
export default logger;

// 导出用于组件的错误边界日志助手
export const logComponentError = (componentName: string, error: Error, errorInfo?: React.ErrorInfo): void => {
  logger.error(`${componentName} component error`, error, {
    component: componentName,
    errorInfo: errorInfo?.componentStack ? { componentStack: errorInfo.componentStack } : undefined
  });
};

// 导出用于API错误的日志助手
export const logApiError = (endpoint: string, method: string, error: any, requestId?: string): void => {
  logger.error(`API call failed: ${method} ${endpoint}`, error, {
    endpoint,
    method,
    requestId,
    errorType: error?.type || 'UnknownError',
    statusCode: error?.statusCode
  });
};

// 导出性能日志助手
export const measurePerformance = async <T>(
  operationName: string,
  fn: () => Promise<T>,
  meta?: any
): Promise<T> => {
  const timerId = `${operationName}_${Date.now()}`;
  logger.startTimer(timerId);
  
  try {
    const result = await fn();
    logger.endTimer(timerId, operationName, meta);
    return result;
  } catch (error) {
    logger.endTimer(timerId, `${operationName}_failed`, meta);
    logger.error(`Performance measurement failed: ${operationName}`, error);
    throw error;
  }
};