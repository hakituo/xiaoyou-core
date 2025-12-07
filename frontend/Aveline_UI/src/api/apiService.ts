// API服务封装
import config from './config';
import { handleApiError, withRetry, ApiError } from './errorHandler';
import logger, { logApiError, measurePerformance } from '../utils/logger';
import { ErrorType, createErrorFromResponse } from './errorHandler';

// API基础URL
const API_BASE_URL = config.apiBaseUrl;

// 请求超时时间
const REQUEST_TIMEOUT = config.timeout;

// 请求头配置
const getHeaders = (): HeadersInit => {
  return {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    // 可以在这里添加认证令牌等
  };
};

// 超时处理函数
const timeoutPromise = (ms: number, promise: Promise<any>): Promise<any> => {
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      reject(new Error(`请求超时: ${ms}ms`));
    }, ms);
    promise.then(
      (res) => {
        clearTimeout(timeoutId);
        resolve(res);
      },
      (err) => {
        clearTimeout(timeoutId);
        reject(err);
      }
    );
  });
};

// 扩展RequestInit以支持silent选项
interface CustomRequestInit extends RequestInit {
  silent?: boolean;
}

// 基础请求方法
const request = async (
  endpoint: string,
  options: CustomRequestInit = {}
): Promise<any> => {
  try {
    const url = `${API_BASE_URL}${endpoint}`;
    // 记录API请求
    if (!options.silent) {
      logger.logApiRequest(endpoint, options.method || 'GET', undefined, {
        ...options.body ? { hasBody: true } : {},
        ...options.headers ? { hasHeaders: Object.keys(options.headers).length } : {}
      });
    }
    
    const headers = {
      ...getHeaders(),
      ...options.headers,
    };
    
    // 如果是FormData，删除Content-Type以便浏览器自动设置（包含boundary）
    if (options.body instanceof FormData) {
      delete (headers as any)['Content-Type'];
    }

    const requestConfig: RequestInit = {
      ...options,
      headers,
    };
    // 删除自定义属性以免传给fetch
    delete (requestConfig as any).silent;

    // 添加超时处理
    const response = await timeoutPromise(REQUEST_TIMEOUT, fetch(url, requestConfig));

    // 检查响应状态
    if (!response.ok) {
      // 创建响应对象，以便错误处理器可以正确处理
      const errorData = await response.json().catch(() => ({}));
      const error = new Error(
        errorData.message || `请求失败: ${response.status} ${response.statusText}`
      );
      // 正确设置响应属性
      Object.defineProperty(error, 'response', {
        value: {
          status: response.status,
          data: errorData
        },
        writable: true,
        enumerable: true
      });
      throw error;
    }

    // 处理空响应
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      return await response.json();
    }
    return await response.text();
  } catch (error: any) {
    // 使用统一的错误处理，并重新抛出以便调用者能捕获
    // handleApiError已经会抛出异常，这里不需要额外的throw
    // 过滤掉轮询请求的连接拒绝错误
    if (endpoint.includes('models') || endpoint.includes('health')) {
      if (error.message && (error.message.includes('Failed to fetch') || error.message.includes('CONNECTION_REFUSED'))) {
        // 仅记录调试日志，不上报错误
        // logger.debug('Polling failed (expected if backend is down)', { endpoint, error: error.message });
        throw error;
      }
    }
    return handleApiError(error, { silent: options.silent });
  }
};

// GET请求
const get = (endpoint: string, params?: Record<string, any>, retryOptions?: { retries?: number, delay?: number, silent?: boolean }): Promise<any> => {
  let queryString = '';
  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        searchParams.append(key, String(value));
      }
    });
    const paramString = searchParams.toString();
    if (paramString) {
      queryString = `?${paramString}`;
    }
  }

  const requestFn = () => request(`${endpoint}${queryString}`, {
    method: 'GET',
    silent: retryOptions?.silent,
  });

  // 如果需要重试机制
  if (retryOptions?.retries && retryOptions.retries > 0) {
    return withRetry(requestFn, { 
      retries: retryOptions.retries, 
      initialDelay: retryOptions.delay 
    });
  }

  return requestFn();
};

// POST请求
const post = (endpoint: string, data?: any, retryOptions?: { retries?: number, delay?: number, silent?: boolean }): Promise<any> => {
  const requestFn = () => request(endpoint, {
    method: 'POST',
    body: data instanceof FormData ? data : JSON.stringify(data),
    silent: retryOptions?.silent,
  });

  // 如果需要重试机制
  if (retryOptions?.retries && retryOptions.retries > 0) {
    return withRetry(requestFn, { 
      retries: retryOptions.retries, 
      initialDelay: retryOptions.delay 
    });
  }

  return requestFn();
};

// PUT请求
const put = (endpoint: string, data?: any, retryOptions?: { retries?: number, delay?: number, silent?: boolean }): Promise<any> => {
  const requestFn = () => request(endpoint, {
    method: 'PUT',
    body: data instanceof FormData ? data : JSON.stringify(data),
    silent: retryOptions?.silent,
  });

  // 如果需要重试机制
  if (retryOptions?.retries && retryOptions.retries > 0) {
    return withRetry(requestFn, { 
      retries: retryOptions.retries, 
      initialDelay: retryOptions.delay 
    });
  }

  return requestFn();
};

// DELETE请求
const del = (endpoint: string, retryOptions?: { retries?: number, delay?: number, silent?: boolean }): Promise<any> => {
  const requestFn = () => request(endpoint, {
    method: 'DELETE',
    silent: retryOptions?.silent,
  });

  // 如果需要重试机制
  if (retryOptions?.retries && retryOptions.retries > 0) {
    return withRetry(requestFn, { 
      retries: retryOptions.retries, 
      initialDelay: retryOptions.delay 
    });
  }

  return requestFn();
};

// 上传文件
const uploadFile = async (
  endpoint: string,
  file: File,
  additionalData?: Record<string, any>,
  retryOptions?: { retries?: number, delay?: number, silent?: boolean }
): Promise<any> => {
  const requestFn = () => {
    const formData = new FormData();
    formData.append('file', file);

    // 添加其他数据
    if (additionalData) {
      Object.entries(additionalData).forEach(([key, value]) => {
        formData.append(key, String(value));
      });
    }

    return request(endpoint, {
      method: 'POST',
      headers: {}, // 文件上传不需要设置Content-Type，浏览器会自动处理
      body: formData,
      silent: retryOptions?.silent,
    });
  };

  // 如果需要重试机制
  if (retryOptions?.retries && retryOptions.retries > 0) {
    return withRetry(requestFn, { 
      retries: retryOptions.retries, 
      initialDelay: retryOptions.delay 
    });
  }

  return requestFn();
};

// 导出API方法
export default {
  get,
  post,
  put,
  delete: del,
  uploadFile,
  withRetry,
  ApiError,
  createErrorFromResponse // 导出错误创建方法供组件使用
};

// 添加请求取消管理器，用于取消进行中的请求
export class RequestCancellationManager {
  private controllers: Map<string, AbortController> = new Map();
  
  // 创建并存储新的AbortController
  createController(requestId: string): AbortController {
    // 如果已有相同ID的控制器，先取消它
    this.cancelRequest(requestId);
    
    const controller = new AbortController();
    this.controllers.set(requestId, controller);
    return controller;
  }
  
  // 取消指定ID的请求
  cancelRequest(requestId: string): void {
    const controller = this.controllers.get(requestId);
    if (controller) {
      controller.abort();
      this.controllers.delete(requestId);
    }
  }
  
  // 取消所有未完成的请求
  cancelAll(): void {
    for (const controller of this.controllers.values()) {
      controller.abort();
    }
    this.controllers.clear();
  }
}

// 创建全局取消管理器实例
export const requestManager = new RequestCancellationManager();

// 导出具体的API端点函数
export const api = {
  // 系统状态
  getHealthMetrics: (options?: { silent?: boolean }) => get('/api/v1/system/resources', undefined, { ...options, retries: 0 }),
  getSystemStats: () => get('/api/v1/system/resources', undefined, { retries: 0, delay: 1000 }),

  // 获取角色配置
  getPersona: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/persona', undefined, options);
    return res;
  },

  // 获取主动问候
  getGreeting: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/greeting', undefined, options);
    return res;
  },
  
  // 聊天消息 - 优化实现，添加请求标识避免重复处理，增强错误处理和重试机制
  sendMessage: async (message: string, options?: {
    retryCount?: number;
    onRetry?: (attempt: number, totalAttempts: number, error: any) => void;
    signal?: AbortSignal;
    modelName?: string;
    quant?: string;
    maxTokens?: number;
  }) => {
    const requestId = Date.now().toString(36) + Math.random().toString(36).substring(2, 9);
    const retryCount = options?.retryCount || 2; // 默认重试2次
    const controller = new AbortController();
    const signal = options?.signal || controller.signal;
    
    // 监听外部取消信号
    if (options?.signal) {
      options.signal.addEventListener('abort', () => controller.abort());
    }
    
    logger.logApiRequest('/api/v1/message', 'POST', requestId, {
      messagePreview: message.substring(0, 50) + (message.length > 50 ? '...' : '')
    });
    
    // 准备请求参数 - 适配后端/api/v1/message端点的格式要求
    const requestParams: any = {
        content: message,
        request_id: requestId
    };
    
    if (options?.maxTokens) {
        requestParams.max_tokens = options.maxTokens;
    }
    
    // 定义重试配置
    const retryOptions = {
      retries: retryCount,
      initialDelay: 1500,
      maxDelay: 8000,
      exponentialBackoff: true,
      jitter: true,
      retryableErrors: [
        ErrorType.NETWORK_ERROR,
        ErrorType.TIMEOUT_ERROR,
        ErrorType.SERVER_ERROR,
        ErrorType.SERVICE_UNAVAILABLE,
        ErrorType.BAD_GATEWAY,
        ErrorType.RATE_LIMIT_ERROR
      ]
    };
    
    try {
      const startTime = performance.now();
      
      // 包装POST请求以便添加重试逻辑
      const executeRequest = async () => {
        // 检查是否已取消
        if (signal.aborted) {
          throw new ApiError('请求已取消', ErrorType.CLIENT_ERROR);
        }
        
        const qs = new URLSearchParams();
        if (options?.modelName) qs.append('model', options.modelName);
        const endpoint = qs.toString() ? `/api/v1/message?${qs.toString()}` : '/api/v1/message';
        const response = await post(endpoint, requestParams);
        
        // 处理后端统一响应格式
        let processedResponse;
        if (response && typeof response === 'object') {
          // 适配后端的统一响应格式
          if (response.status === 'success' && response.data) {
            // 后端返回标准格式
            processedResponse = response.data;
          } else if (response.response) {
            // 兼容旧格式
            processedResponse = response.response;
          } else {
            // 直接返回响应
            processedResponse = response;
          }
        } else {
          processedResponse = response;
        }
        
        const endTime = performance.now();
    const duration = endTime - startTime;
    logger.logApiResponse('/api/v1/message', 'POST', requestId, 200, duration, {
      hasReply: !!processedResponse.reply || !!processedResponse.response,
      hasConversationId: !!processedResponse.conversation_id
    });
        
        // 确保返回的数据结构一致，并透传情绪与TTS建议
        return {
          reply: processedResponse.reply || processedResponse.response || processedResponse,
          conversation_id: processedResponse.conversation_id,
          request_id: requestId,
          status: processedResponse.status || 'success',
          emotion: processedResponse.emotion,
          emotion_internal: processedResponse.emotion_internal,
          emotion_confidence: processedResponse.emotion_confidence,
          tts_suggest: processedResponse.tts_suggest
        };
      };
      
      // 带重试的请求执行器，增加重试回调
      const executeWithRetryCallbacks = async (attempt = 0): Promise<any> => {
        try {
          return await executeRequest();
        } catch (error: any) {
          const apiError = error instanceof ApiError ? error : createErrorFromResponse(error);
          
          // 检查是否应该重试
          if (attempt < retryOptions.retries && retryOptions.retryableErrors.includes(apiError.type)) {
            attempt++;
            
            // 通知重试回调
            if (options?.onRetry) {
              try {
                options.onRetry(attempt, retryOptions.retries, apiError);
              } catch (callbackError) {
                logger.error('Retry callback error', callbackError);
              }
            }
            
            // 计算延迟时间
            let delay = retryOptions.initialDelay;
            if (retryOptions.exponentialBackoff) {
              delay = Math.min(retryOptions.maxDelay, retryOptions.initialDelay * Math.pow(2, attempt - 1));
            }
            
            // 对429错误使用后端建议的重试时间
            if (apiError.type === ErrorType.RATE_LIMIT_ERROR && apiError.details?.retryAfter) {
              delay = apiError.details.retryAfter * 1000;
            }
            
            // 添加抖动
            if (retryOptions.jitter) {
              const jitterFactor = 0.1;
              const jitterAmount = delay * jitterFactor;
              delay = delay - jitterAmount / 2 + Math.random() * jitterAmount;
            }
            
            logger.warn(`API请求重试`, {
              endpoint: '/api/v1/message',
              method: 'POST',
              requestId,
              attempt,
              totalRetries: retryOptions.retries,
              delay: `${delay.toFixed(0)}ms`,
              errorType: apiError.type
            });
            
            // 等待延迟时间，同时支持取消
            await new Promise<void>((resolve, reject) => {
              const timeoutId = setTimeout(() => resolve(), delay);
              signal.addEventListener('abort', () => {
                clearTimeout(timeoutId);
                reject(new ApiError('请求已取消', ErrorType.CLIENT_ERROR));
              }, { once: true });
            });
            
            // 递归重试
            return executeWithRetryCallbacks(attempt);
          }
          
          // 达到最大重试次数或错误不可重试，抛出错误
          logApiError('/api/v1/message', 'POST', apiError, requestId);
          throw apiError;
        }
      };
      
      const result = await executeWithRetryCallbacks();
    logger.info('API消息发送完成', { requestId });
      return result;
    } catch (error: any) {
      // 确保错误被正确转换为ApiError并添加请求ID
      const apiError = error instanceof ApiError ? error : createErrorFromResponse(error);
      (apiError as any).requestId = requestId;
      
      // 根据错误类型提供更具体的错误信息
      if (apiError.type === ErrorType.NETWORK_ERROR) {
        apiError.message = '网络连接问题，请检查您的网络设置后重试';
      } else if (apiError.type === ErrorType.TIMEOUT_ERROR) {
        apiError.message = '服务器响应超时，请稍后再试';
      } else if (apiError.type === ErrorType.RATE_LIMIT_ERROR) {
        apiError.message = '请求过于频繁，请稍等片刻后再试';
      }
      
      throw apiError;
    }
  },

  // 语音转文字
  transcribeAudio: async (audioBlob: Blob, modelSize: string = 'base') => {
    const formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');
    return post(`/api/v1/stt?model_size=${modelSize}`, formData);
  },

  listModels: async (category?: string, options?: { silent?: boolean }) => {
    const res = await get('/api/v1/models', category ? { category } : undefined, options);
    return res;
  },
  loadModel: async (payload: { model_name?: string; id?: string; type?: string; model_type?: string; path?: string; model_path?: string; options?: any; }) => {
    const res = await post('/api/v1/models/load', payload);
    return res;
  },
  getModelStatus: async (model_name?: string, options?: { silent?: boolean }) => {
    const res = await get('/api/v1/models/status', model_name ? { model_name } : undefined, options);
    return res;
  },

  visionDescribe: async (payload: { model_name: string; image_base64?: string; image_path?: string; prompt?: string; }) => {
    const res = await post('/api/v1/vision/describe', payload);
    return res;
  },
  // Image Generation
  generateImage: (prompt: string, modelPath?: string, loraPath?: string, loraWeight?: number) => 
    post('/api/v1/image/generate', { prompt, modelPath, loraPath, loraWeight }, { retries: 0 }),
  uploadFile: async (endpoint: string, file: File, additionalData?: Record<string, any>, retryOptions?: { retries?: number, delay?: number }) => {
    return uploadFile(endpoint, file, additionalData, retryOptions);
  },
  // TTS
  tts: (data: any) => post('/api/v1/tts', data),
  listVoices: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/voices', undefined, options);
    return res;
  },
  getPushPublicKey: async () => {
    const res = await get('/api/v1/push/public_key');
    return res;
  },
  subscribePush: async (payload: { subscription: any }) => {
    const res = await post('/api/v1/push/subscribe', payload);
    return res;
  },
  pushTest: async (payload: { title?: string; body?: string; url?: string }) => {
    const res = await post('/api/v1/push/test', payload);
    return res;
  },
  analyzeScreen: async (payload: { image_base64: string }) => {
    const res = await post('/api/v1/analyze_screen', payload);
    return res;
  },
  searchWeb: async (payload: { query: string; provider?: string; freshness?: string; count?: number; summary?: boolean }) => {
    const body = {
      query: payload.query,
      provider: payload.provider || 'bocha',
      freshness: payload.freshness || 'noLimit',
      count: typeof payload.count === 'number' ? payload.count : 3,
      summary: payload.summary !== false
    };
    const res = await post('/api/v1/search/web', body);
    return res;
  },
  clearMemory: async () => {
    const res = await del('/api/v1/memory/clear');
    return res;
  },
  
  // 文件上传
  upload: (file: File) => uploadFile('/api/v1/upload', file),
  
  // 可以根据需要添加更多API端点
};

export {};
