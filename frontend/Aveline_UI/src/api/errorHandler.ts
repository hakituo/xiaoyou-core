// API错误处理服务
import logger from '../utils/logger';

// 错误类型定义
export enum ErrorType {
  NETWORK_ERROR = 'NETWORK_ERROR',
  TIMEOUT_ERROR = 'TIMEOUT_ERROR',
  SERVER_ERROR = 'SERVER_ERROR',
  CLIENT_ERROR = 'CLIENT_ERROR',
  AUTH_ERROR = 'AUTH_ERROR',
  NOT_FOUND = 'NOT_FOUND',
  VALIDATION_ERROR = 'VALIDATION_ERROR',
  UNKNOWN_ERROR = 'UNKNOWN_ERROR',
  SERVICE_UNAVAILABLE = 'SERVICE_UNAVAILABLE',
  BAD_GATEWAY = 'BAD_GATEWAY',
  RATE_LIMIT_ERROR = 'RATE_LIMIT_ERROR',
}

// 可重试的错误类型
const RETRIABLE_ERROR_TYPES = [
  ErrorType.NETWORK_ERROR,
  ErrorType.SERVER_ERROR,
  ErrorType.TIMEOUT_ERROR,
  ErrorType.SERVICE_UNAVAILABLE,
  ErrorType.BAD_GATEWAY,
  ErrorType.RATE_LIMIT_ERROR
];

// 自定义错误类
export class ApiError extends Error {
  type: ErrorType;
  statusCode?: number;
  details?: any;
  originalError?: any;
  timestamp: number;

  constructor(
    message: string,
    type: ErrorType,
    statusCode?: number,
    details?: any,
    originalError?: any
  ) {
    super(message);
    this.name = 'ApiError';
    this.type = type;
    this.statusCode = statusCode;
    this.details = details;
    this.originalError = originalError;
    this.timestamp = Date.now();
    // 为了正确继承Error类的堆栈
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  // 检查错误是否可重试
  isRetriable(): boolean {
    return RETRIABLE_ERROR_TYPES.includes(this.type);
  }
}

// 全局错误通知系统
class ErrorNotifier {
  private errorListeners: ((error: ApiError) => void)[] = [];

  addListener(listener: (error: ApiError) => void): () => void {
    this.errorListeners.push(listener);
    // 返回移除监听器的函数
    return () => {
      this.errorListeners = this.errorListeners.filter(l => l !== listener);
    };
  }

  notify(error: ApiError): void {
    this.errorListeners.forEach(listener => {
      try {
        listener(error);
      } catch (e) {
        logger.error('错误通知监听器失败', e);
      }
    });
  }
}

// 创建全局错误通知器实例
const errorNotifier = new ErrorNotifier();

// 错误处理器
class ErrorHandler {
  // 从HTTP响应创建错误
  createErrorFromResponse(error: any): ApiError {
    try {
      if (error instanceof ApiError) {
        return error;
      }

      // 安全检查error对象
      if (!error || typeof error !== 'object') {
        return new ApiError(
          '发生未知错误',
          ErrorType.UNKNOWN_ERROR,
          undefined,
          { error },
          error
        );
      }

      // 处理网络错误
      if (!error.response) {
        // 更详细地区分网络错误类型
        const errorMessage = String(error.message || '');
        
        if (errorMessage.includes('timeout') || errorMessage.includes('超时')) {
          return new ApiError(
            '请求超时，请检查网络连接或稍后重试',
            ErrorType.TIMEOUT_ERROR,
            undefined,
            { message: errorMessage },
            error
          );
        }
        
        if (errorMessage.includes('Network Error') || errorMessage.includes('网络错误')) {
          return new ApiError(
            '网络连接失败，请检查您的网络设置',
            ErrorType.NETWORK_ERROR,
            undefined,
            { message: errorMessage },
            error
          );
        }
        
        if (errorMessage.includes('Connection refused')) {
          return new ApiError(
            '无法连接到服务器，请检查服务器是否运行',
            ErrorType.SERVICE_UNAVAILABLE,
            undefined,
            { message: errorMessage },
            error
          );
        }
        
        return new ApiError(
          errorMessage || '网络连接失败，请检查您的网络设置',
          ErrorType.NETWORK_ERROR,
          undefined,
          { message: errorMessage },
          error
        );
      }

      const { response } = error;
      const statusCode = response?.status;
      // 安全地获取错误数据，防止访问undefined属性
      let errorData = {};
      try {
        errorData = response?.data || {};
        if (typeof errorData !== 'object') {
          errorData = { rawResponse: String(errorData) };
        }
      } catch (e) {
        errorData = { parseError: String(e) };
      }

      // 根据状态码创建相应的错误
      switch (statusCode) {
        case 401:
          return new ApiError(
            (errorData as any)?.message || '未授权访问，请重新登录',
            ErrorType.AUTH_ERROR,
            statusCode,
            errorData,
            error
          );
        case 403:
          return new ApiError(
            (errorData as any)?.message || '没有权限执行此操作',
            ErrorType.AUTH_ERROR,
            statusCode,
            errorData,
            error
          );
        case 404:
          return new ApiError(
            (errorData as any)?.message || '请求的资源不存在',
            ErrorType.NOT_FOUND,
            statusCode,
            errorData,
            error
          );
        case 422:
          return new ApiError(
            '数据验证失败',
            ErrorType.VALIDATION_ERROR,
            statusCode,
            errorData,
            error
          );
        case 429:
          // 专门处理429限流错误，提取重试信息
          const retryAfter = this.getRetryAfterValue(errorData);
          const retryMessage = retryAfter
            ? `请求过于频繁，请在${retryAfter}秒后重试`
            : '请求过于频繁，请稍后再试';
          return new ApiError(
            retryMessage,
            ErrorType.RATE_LIMIT_ERROR,
            statusCode,
            {
              ...errorData,
              retryAfter,
              retryHint: (errorData as any)?.error?.retry_hint || {}  // 适配后端新格式
            },
            error
          );
        case 500:
          return new ApiError(
            (errorData as any)?.message || '服务器内部错误，请稍后重试',
            ErrorType.SERVER_ERROR,
            statusCode,
            errorData,
            error
          );
        case 502:
          return new ApiError(
            '网关错误，请稍后重试',
            ErrorType.BAD_GATEWAY,
            statusCode,
            errorData,
            error
          );
        case 503:
          return new ApiError(
            '服务暂时不可用，请稍后重试',
            ErrorType.SERVICE_UNAVAILABLE,
            statusCode,
            errorData,
            error
          );
        case statusCode >= 400 && statusCode < 500:
          return new ApiError(
            (errorData as any)?.message || '请求参数错误',
            ErrorType.CLIENT_ERROR,
            statusCode,
            errorData,
            error
          );
        case statusCode >= 500:
          return new ApiError(
            (errorData as any)?.message || '服务器错误，请稍后重试',
            ErrorType.SERVER_ERROR,
            statusCode,
            errorData,
            error
          );
        default:
          return new ApiError(
            (errorData as any)?.message || '未知错误',
            ErrorType.UNKNOWN_ERROR,
            statusCode,
            errorData,
            error
          );
      }
    } catch (e) {
      // 确保即使在错误处理过程中出错也能返回有效的ApiError
      logger.error('创建ApiError失败', e);
      return new ApiError(
        '处理错误时发生异常',
        ErrorType.UNKNOWN_ERROR,
        undefined,
        { originalError: String(error), creationError: String(e) },
        error
      );
    }
  }

  // 处理特定类型的错误
  handleError(error: ApiError, options: { silent?: boolean } = {}): void {
    try {
      // 如果设置为静默模式，直接返回不通知用户
      if (options.silent) return;

      // 记录详细错误信息
      logger.error('API错误', undefined, {
        type: error.type,
        message: error.message,
        statusCode: error.statusCode,
        details: error.details,
        timestamp: new Date(error.timestamp).toISOString()
      });

      // 通知所有错误监听器
      errorNotifier.notify(error);

      // 根据错误类型执行特定的处理逻辑
      switch (error.type) {
        case ErrorType.NETWORK_ERROR:
        case ErrorType.TIMEOUT_ERROR:
          // 网络错误和超时的特殊处理
          this.notifyUser(error.message, 'error');
          break;
          
        case ErrorType.AUTH_ERROR:
          // 认证错误，可能需要处理登出
          this.notifyUser(error.message, 'warning');
          // 可以在这里触发登出逻辑或重定向到登录页
          // 例如: authService.logout();
          break;
          
        case ErrorType.NOT_FOUND:
          // 资源未找到，可能需要重定向到404页面
          this.notifyUser(error.message, 'info');
          break;
          
        case ErrorType.VALIDATION_ERROR:
          // 验证错误，显示详细的字段错误
          const validationMessage = this.formatValidationErrors(error.details);
          this.notifyUser(validationMessage || error.message, 'warning');
          break;
          
        case ErrorType.RATE_LIMIT_ERROR:
          // 特殊处理限流错误，可能需要显示倒计时
          this.notifyUser(error.message, 'warning');
          // 可以在这里实现更复杂的限流处理，比如自动倒计时重试
          break;
        case ErrorType.SERVER_ERROR:
        case ErrorType.SERVICE_UNAVAILABLE:
        case ErrorType.BAD_GATEWAY:
          // 服务器错误，显示友好的提示
          this.notifyUser('服务器暂时无法响应，请稍后重试', 'error');
          break;
          
        default:
          // 其他错误
          this.notifyUser(error.message, 'error');
      }
    } catch (e) {
      logger.error('处理错误失败', e);
      // 最后的保障，确保错误处理不会崩溃应用
      try {
        this.notifyUser('处理错误时发生异常', 'error');
      } catch {}
    }
  }

  // 显示用户通知
  private notifyUser(message: string, type: 'error' | 'warning' | 'info' | 'success'): void {
    try {
      // 这里可以集成到应用的通知系统
      // 例如使用toast库或自定义通知组件
      // toast[type](message);
      
      // 记录通知消息
      switch (type) {
        case 'error':
          logger.error('用户通知', undefined, { message });
          break;
        case 'warning':
          logger.warn('用户通知', { message });
          break;
        case 'info':
        case 'success':
          logger.info('用户通知', { message });
          break;
      }
      
      // 注意：在生产环境中应避免使用alert，这里只是一个后备方案
      // if (process.env.NODE_ENV !== 'production') {
      //   alert(message);
      // }
    } catch (e) {
      logger.error('通知用户失败', e);
    }
  }

  // 获取重试时间（秒）
  private getRetryAfterValue(errorData: any): number | undefined {
    try {
      // 尝试多种可能的格式获取重试时间
      if (errorData?.error?.retry_hint?.retry_after_seconds) {
        return errorData.error.retry_hint.retry_after_seconds;
      }
      if (errorData?.error?.details?.retry_after) {
        return errorData.error.details.retry_after;
      }
      if (errorData?.error?.details?.reset_after) {
        return Math.ceil(errorData.error.details.reset_after);
      }
      if (errorData?.retry_after) {
        return errorData.retry_after;
      }
      if (errorData?.reset_after) {
        return Math.ceil(errorData.reset_after);
      }
      return undefined;
    } catch {
      return undefined;
    }
  }

  // 格式化验证错误信息
  formatValidationErrors(errorData: any): string {
    try {
      if (!errorData || typeof errorData !== 'object') {
        return '';
      }

      // 处理常见的错误格式
      if (errorData.errors && typeof errorData.errors === 'object') {
        return Object.entries(errorData.errors)
          .map(([field, msgs]) => {
            if (Array.isArray(msgs)) {
              return `${field}: ${msgs.join(', ')}`;
            }
            return `${field}: ${String(msgs)}`;
          })
          .join('\n');
      }
      
      // 处理message字段
      if (errorData.message) {
        return String(errorData.message);
      }
      
      return '';
    } catch (e) {
      logger.error('格式化验证错误失败', e);
      return '';
    }
  }
}

// 创建错误处理器实例
const errorHandler = new ErrorHandler();

// 导出错误处理方法
export const createErrorFromResponse = (error: any): ApiError => 
  errorHandler.createErrorFromResponse(error);

export const handleError = (error: ApiError, options: { silent?: boolean } = {}): void => 
  errorHandler.handleError(error, options);

// 错误处理函数
export const handleApiError = (error: any, options: { silent?: boolean } = {}): never => {
  try {
    const apiError = createErrorFromResponse(error);
    handleError(apiError, options);
    throw apiError;
  } catch (e) {
    // 确保即使在错误处理过程中出错也能抛出错误
    if (e instanceof ApiError) {
      throw e;
    }
    // 创建一个新的错误作为后备
    throw new ApiError(
      '处理API错误时发生异常',
      ErrorType.UNKNOWN_ERROR,
      undefined,
      { originalError: String(error) },
      error
    );
  }
};

// 带智能重试的异步函数执行器
export const withRetry = async <T>(
  fn: () => Promise<T>,
  options?: {
    retries?: number;
    initialDelay?: number;
    maxDelay?: number;
    exponentialBackoff?: boolean;
    jitter?: boolean;
    retryableErrors?: ErrorType[];
  }
): Promise<T> => {
  const {
    retries = 3,
    initialDelay = 1000,
    maxDelay = 10000,
    exponentialBackoff = true,
    jitter = true,
    retryableErrors = RETRIABLE_ERROR_TYPES,
  } = options || {};

  let attempts = 0;
  
  const executeWithRetry = async (): Promise<T> => {
    try {
      return await fn();
    } catch (error: any) {
      attempts++;
      
      // 如果达到最大重试次数，抛出错误
      if (attempts > retries) {
        // 如果是ApiError，直接抛出；否则创建一个新的ApiError
        const apiError = error instanceof ApiError ? error : createErrorFromResponse(error);
        throw apiError;
      }

      // 检查错误是否可以重试
      let shouldRetry = false;
      let apiError: ApiError;
      
      if (error instanceof ApiError) {
        apiError = error;
        shouldRetry = retryableErrors.includes(apiError.type);
      } else {
        // 创建ApiError并检查是否可以重试
        apiError = createErrorFromResponse(error);
        shouldRetry = retryableErrors.includes(apiError.type);
      }

      // 如果错误不可重试，直接抛出
      if (!shouldRetry) {
        throw apiError;
      }

      // 对于429错误，优先使用后端返回的重试时间
      let delay = initialDelay;
      if (apiError.type === ErrorType.RATE_LIMIT_ERROR) {
        const retryAfterSeconds = apiError.details?.retryAfter;
        if (retryAfterSeconds && retryAfterSeconds > 0) {
          // 使用后端建议的重试时间，转换为毫秒
          delay = retryAfterSeconds * 1000;
          logger.info('使用后端建议的重试时间', { delayMs: Math.floor(delay) });
        } else if (exponentialBackoff) {
          delay = Math.min(maxDelay, initialDelay * Math.pow(2, attempts - 1));
        }
      } else if (exponentialBackoff) {
        delay = Math.min(maxDelay, initialDelay * Math.pow(2, attempts - 1));
      }

      // 添加抖动以避免请求风暴
      if (jitter) {
        const jitterFactor = 0.1; // 10%的抖动
        const jitterAmount = delay * jitterFactor;
        delay = delay - jitterAmount / 2 + Math.random() * jitterAmount;
      }

      logger.info('请求失败，准备重试', { delayMs: Math.floor(delay), attempts, retries });
      
      // 等待指定的延迟时间
      await new Promise(resolve => setTimeout(resolve, delay));
      
      // 递归重试
      return executeWithRetry();
    }
  };

  return executeWithRetry();
};

// 导出错误通知器
export { errorNotifier };