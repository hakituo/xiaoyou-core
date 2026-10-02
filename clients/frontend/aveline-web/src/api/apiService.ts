// API服务封装
import config from './config';
import { handleApiError, withRetry, ApiError } from './errorHandler';
import logger, { logApiError, measurePerformance } from '../utils/logger';
import { ErrorType, createErrorFromResponse } from './errorHandler';

// API基础URL
export const getBaseUrl = () => {
  try {
    const stored = localStorage.getItem('AVELINE_API_URL');
    if (stored) return stored.replace(/\/$/, '');
  } catch {}
  return config.apiBaseUrl;
};

// 请求超时时间
const REQUEST_TIMEOUT = config.timeout;

// 请求头配置
const getHeaders = (): HeadersInit => {
  let token = '';
  try {
    token = (localStorage.getItem('XIAOYOU_ACCESS_TOKEN') || '').trim();
  } catch {}

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  return {
    ...headers,
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
  timeoutMs?: number;
}

// 基础请求方法
const request = async (
  endpoint: string,
  options: CustomRequestInit = {}
): Promise<any> => {
  try {
    const url = `${getBaseUrl()}${endpoint}`;
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
    const timeoutMs = typeof options.timeoutMs === 'number' ? options.timeoutMs : REQUEST_TIMEOUT;
    delete (requestConfig as any).timeoutMs;

    // 添加超时处理
    const response = await timeoutPromise(timeoutMs, fetch(url, requestConfig));

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

const ensureWavBlob = async (audioBlob: Blob): Promise<Blob> => {
  if (!audioBlob) return audioBlob;
  if (audioBlob.type === 'audio/wav') return audioBlob;
  if (typeof window === 'undefined') return audioBlob;

  const AudioContextCtor = (window as any).AudioContext || (window as any).webkitAudioContext;
  if (!AudioContextCtor) return audioBlob;

  const audioContext = new AudioContextCtor();
  try {
    const ab = await audioBlob.arrayBuffer();
    const audioBuffer: AudioBuffer = await audioContext.decodeAudioData(ab.slice(0));

    const channelCount = audioBuffer.numberOfChannels || 1;
    const length = audioBuffer.length;

    let mono: Float32Array;
    if (channelCount === 1) {
      mono = audioBuffer.getChannelData(0);
    } else {
      mono = new Float32Array(length);
      for (let ch = 0; ch < channelCount; ch++) {
        const data = audioBuffer.getChannelData(ch);
        for (let i = 0; i < length; i++) mono[i] += data[i] / channelCount;
      }
    }

    const sampleRate = audioBuffer.sampleRate;
    const bytesPerSample = 2;
    const blockAlign = 1 * bytesPerSample;
    const byteRate = sampleRate * blockAlign;
    const dataSize = mono.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    const writeString = (offset: number, s: string) => {
      for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
    };

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, 16, true);
    writeString(36, 'data');
    view.setUint32(40, dataSize, true);

    let offset = 44;
    for (let i = 0; i < mono.length; i++) {
      const s = Math.max(-1, Math.min(1, mono[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }

    return new Blob([buffer], { type: 'audio/wav' });
  } catch {
    return audioBlob;
  } finally {
    try {
      await audioContext.close();
    } catch {}
  }
};

// 请求重试/静默/超时选项
interface RetryOptions {
  retries?: number;
  delay?: number;
  silent?: boolean;
  timeoutMs?: number;
}

// GET请求
const get = (endpoint: string, params?: Record<string, any>, retryOptions?: RetryOptions): Promise<any> => {
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
    ...(retryOptions?.timeoutMs ? { timeoutMs: retryOptions.timeoutMs } : {}),
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
const post = (endpoint: string, data?: any, retryOptions?: RetryOptions): Promise<any> => {
  const requestFn = () => request(endpoint, {
    method: 'POST',
    body: data instanceof FormData ? data : JSON.stringify(data),
    silent: retryOptions?.silent,
    ...(retryOptions?.timeoutMs ? { timeoutMs: retryOptions.timeoutMs } : {}),
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
const put = (endpoint: string, data?: any, retryOptions?: RetryOptions): Promise<any> => {
  const requestFn = () => request(endpoint, {
    method: 'PUT',
    body: data instanceof FormData ? data : JSON.stringify(data),
    silent: retryOptions?.silent,
    ...(retryOptions?.timeoutMs ? { timeoutMs: retryOptions.timeoutMs } : {}),
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
const del = (endpoint: string, retryOptions?: RetryOptions): Promise<any> => {
  const requestFn = () => request(endpoint, {
    method: 'DELETE',
    silent: retryOptions?.silent,
    ...(retryOptions?.timeoutMs ? { timeoutMs: retryOptions.timeoutMs } : {}),
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
  retryOptions?: RetryOptions
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
      ...(retryOptions?.timeoutMs ? { timeoutMs: retryOptions.timeoutMs } : {}),
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
  // 基础方法
  get,
  post,
  put,
  delete: del,

  // 系统状态
  getHealthMetrics: (options?: { silent?: boolean }) => get('/api/v1/system/resources', undefined, { ...options, retries: 0 }),
  getSystemStats: () => get('/api/v1/system/stats', undefined, { retries: 0, delay: 1000 }),
  getHealth: (options?: { silent?: boolean }) => get('/api/v1/health', undefined, { ...options, retries: 0 }),
  getPreferences: () => get('/api/v1/system/preferences'),
  updatePreferences: (prefs: Record<string, any>) => post('/api/v1/system/preferences', prefs),
  getActiveCareStatus: (options?: { silent?: boolean }) => get('/api/v1/system/active-care/status', undefined, { ...options, retries: 0 }),
  triggerActiveCareCheck: (payload?: { is_startup?: boolean }, options?: { silent?: boolean }) => post('/api/v1/system/active-care/check', payload || {}, { ...options, retries: 0 }),
  forceSendActiveCare: (payload?: { prompt_type?: string; thought?: string; user_input_mock?: string; client_type?: string }, options?: { silent?: boolean }) =>
    post('/api/v1/system/active-care/force-send', payload || {}, { ...options, retries: 0 }),

  // 人设管理
  listPersonas: () => get('/api/v1/personas'),
  switchPersona: (filename: string) => post('/api/v1/personas/switch', { filename }),
  getCurrentPersona: () => get('/api/v1/personas/current'),

  // 模型管理
  getModels: (options?: { silent?: boolean }) => get('/api/v1/models', undefined, options),
  switchModel: (modelName: string, provider: string) => post('/api/v1/models/switch', { model_name: modelName, provider }),

  // 插件与功能
  getSensitiveStatus: () => get('/api/v1/plugins/sensitive/status'),
  toggleSensitive: (enabled: boolean) => post('/api/v1/plugins/sensitive/toggle', { enabled }),

  dailyDataList: async (options?: { path?: string; limit?: number; silent?: boolean }) => {
    const res = await get('/api/v1/context/daily/list', { path: options?.path, limit: options?.limit }, { ...options, retries: 0 });
    return res;
  },

  dailyDataRead: async (options: { path: string; maxChars?: number; silent?: boolean }) => {
    const res = await get('/api/v1/context/daily/read', { path: options.path, max_chars: options.maxChars }, { ...options, retries: 0 });
    return res;
  },

  dailyDataRecent: async (options?: { limit?: number; silent?: boolean }) => {
    const res = await get('/api/v1/context/daily/recent', { limit: options?.limit }, { ...options, retries: 0 });
    return res;
  },

  dailyDataPortraitToday: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/context/daily/portrait/today', undefined, { ...options, retries: 0 });
    return res;
  },

  dailyDataRecordDrink: async (payload: { units?: number; amount_ml?: number; beverage?: string }, options?: { silent?: boolean }) => {
    const res = await post('/api/v1/context/daily/record/drink', payload, { ...options, retries: 0 });
    return res;
  },

  dailyDataRecordBodyMetrics: async (payload: { weight_kg?: number }, options?: { silent?: boolean }) => {
    const res = await post('/api/v1/context/daily/record/body-metrics', payload, { ...options, retries: 0 });
    return res;
  },

  dailyDataRecordStudy: async (
    payload: {
      subject: string;
      duration_minutes?: number;
      note?: string;
      enter_low_disturbance?: boolean;
      switch_mode_to_study?: boolean;
    },
    options?: { silent?: boolean },
  ) => {
    const res = await post('/api/v1/context/daily/record/study', payload, { ...options, retries: 0 });
    return res;
  },

  dailyDataFinishStudy: async (options?: { silent?: boolean }) => {
    const res = await post('/api/v1/context/daily/study/finish', {}, { ...options, retries: 0 });
    return res;
  },

  workspaceStudyOverview: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/workspace/study/overview', undefined, { ...options, retries: 0 });
    return res;
  },

  workspaceStudyPanel: async (
    options?: { conversationId?: string; date?: string; historyLimit?: number; silent?: boolean },
  ) => {
    const res = await get(
      '/api/v1/workspace/study/panel',
      {
        conversation_id: options?.conversationId,
        date: options?.date,
        history_limit: options?.historyLimit,
      },
      { ...options, retries: 0 },
    );
    return res;
  },

  workspaceStudyRecord: async (
    payload: { topic: string; content: string; path?: string },
    options?: { silent?: boolean },
  ) => {
    const res = await post('/api/v1/workspace/study/record', payload, { ...options, retries: 0 });
    return res;
  },

  // 设备上下文
  uploadDeviceContext: (context: any) => post('/api/v1/context/device', context, { retries: 1, silent: true }),

  // 获取角色配置
  getPersona: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/chat/persona', undefined, options);
    return res;
  },

  // 获取主动问候
  getGreeting: async (conversationId?: string, options?: { silent?: boolean }) => {
    const params = conversationId ? { conversation_id: conversationId } : undefined;
    const res = await get('/api/v1/chat/greeting', params, options);
    return res;
  },
  
  // 获取生活状态
  getLifeStatus: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/life/status', undefined, options);
    return res;
  },

  // 获取参考音频列表
  getReferenceAudio: async () => {
    const res = await get('/api/v1/media/voice/reference-audio', undefined, { retries: 2 });
    return res;
  },

  // 学习模块
  getDailyVocabulary: async (limit: number = 20) => {
    const res = await get(`/api/v1/vocab/daily?count=${limit}`);
    return res;
  },

  searchDictionary: async (query: string) => {
    const res = await get('/api/v1/vocab/dictionary/search', { query });
    return res;
  },

  getDictList: async (page: number, pageSize: number) => {
    const res = await get(`/api/v1/vocab/dictionary/list?page=${page}&page_size=${pageSize}`);
    return res;
  },
  
  getStudyTools: async () => {
    const res = await get('/api/v1/vocab/tools');
    return res;
  },

  runStudyTool: async (category: string, toolId: string, params: any) => {
    const res = await post(`/api/v1/vocab/tools/${category}/${toolId}/run`, params);
    return res;
  },

  getDictStats: async () => {
    const res = await get('/api/v1/vocab/dictionary/stats');
    return res;
  },

  getMemoryCurve: async () => {
    const res = await get('/api/v1/vocab/curve');
    return res;
  },

  getMistakes: async () => {
    const res = await get('/api/v1/vocab/mistakes');
    return res;
  },

  switchVocabulary: async (filename: string, isSentence: boolean = false) => {
    const res = await post('/api/v1/vocab/vocabulary/switch', { filename, is_sentence: isSentence });
    return res;
  },

  addToLearning: async (word: string) => {
    const res = await post('/api/v1/vocab/vocabulary/add', { word });
    return res;
  },

  submitReview: async (word: string, quality: number) => {
    const res = await post('/api/v1/vocab/review', { word, quality });
    return res;
  },

  getSessionStats: async () => {
    const res = await get('/api/v1/vocab/sessions/stats');
    return res;
  },

  startSession: async () => {
        const res = await post('/api/v1/vocab/sessions', {});
        return res;
    },
    endSession: async () => {
        const res = await post('/api/v1/vocab/sessions/current', {});
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
    conversationId?: string;
    voiceId?: string;
    length?: string;
  }) => {
    const requestId = Date.now().toString(36) + Math.random().toString(36).substring(2, 9);
    const retryCount = options?.retryCount || 2; // 默认重试2次
    const controller = new AbortController();
    const signal = options?.signal || controller.signal;
    
    // 监听外部取消信号
    if (options?.signal) {
      options.signal.addEventListener('abort', () => controller.abort());
    }
    
    logger.logApiRequest('/api/v1/chat/message', 'POST', requestId, {
      messagePreview: message.substring(0, 50) + (message.length > 50 ? '...' : '')
    });
    
    // 准备请求参数 - 适配后端/api/v1/chat/message端点的格式要求
    const requestParams: any = {
        content: message,
        request_id: requestId,
        conversation_id: options?.conversationId,
        length: options?.length
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
        if (options?.voiceId) qs.append('voice_id', options.voiceId);
        const endpoint = qs.toString() ? `/api/v1/chat/message?${qs.toString()}` : '/api/v1/chat/message';
        const response = await post(endpoint, requestParams);

        let processedResponse: any;
        if (response && typeof response === 'object') {
          if (response.status === 'success' && (response as any).data) {
            processedResponse = (response as any).data;
          } else {
            processedResponse = response;
          }
        } else {
          processedResponse = response;
        }
        
        const endTime = performance.now();
    const duration = endTime - startTime;
        logger.logApiResponse('/api/v1/chat/message', 'POST', requestId, 200, duration, {
          hasReply:
            !!(processedResponse && (processedResponse as any).reply) ||
            !!(processedResponse && (processedResponse as any).response) ||
            !!(processedResponse && (processedResponse as any).detail),
          hasConversationId: !!(processedResponse && (processedResponse as any).conversation_id)
        });

        const baseReply =
          typeof processedResponse === 'string'
            ? processedResponse
            : (processedResponse?.reply as string) ||
              (processedResponse?.response as string) ||
              (processedResponse?.detail as string) ||
              (processedResponse?.message as string) ||
              '';

        const safeReply = baseReply && typeof baseReply === 'string' ? baseReply : '';

        const refAudioPath = sessionStorage.getItem('selected_ref_audio') || undefined;

        return {
          reply: safeReply || '（无回复内容）',
          conversation_id: processedResponse?.conversation_id,
          message_id: processedResponse?.message_id,
          request_id: processedResponse?.request_id || requestId,
          status: processedResponse?.status || 'success',
          emotion: processedResponse?.emotion,
          emotion_internal: processedResponse?.emotion_internal,
          emotion_confidence: processedResponse?.emotion_confidence,
          tts_suggest: processedResponse?.tts_suggest,
          ref_audio_path: refAudioPath,
          voice_id: processedResponse?.voice_id,
          image_base64: processedResponse?.image_base64,
          image_url: processedResponse?.image_url,
          audio_base64: processedResponse?.audio_base64,
          audio_path: processedResponse?.audio_path
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
              endpoint: '/api/v1/chat/message',
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
          logApiError('/api/v1/chat/message', 'POST', apiError, requestId);
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
        apiError.message = '服务器响应超时（后端可能正在高负载计算或资源调度中），请稍后再试';
      } else if (apiError.type === ErrorType.RATE_LIMIT_ERROR) {
        apiError.message = '请求过于频繁，请稍等片刻后再试';
      }
      
      throw apiError;
    }
  },

  // 语音转文字
  transcribeAudio: async (audioBlob: Blob, modelSize: string = 'base') => {
    const wavBlob = await ensureWavBlob(audioBlob);
    const formData = new FormData();
    const filename = wavBlob.type === 'audio/wav' ? 'recording.wav' : 'recording.webm';
    formData.append('file', wavBlob, filename);
    return post(`/api/v1/media/stt?model_size=${modelSize}`, formData);
  },

  listModels: async (type?: string, options?: { silent?: boolean }) => {
    const res = await get('/api/v1/models', type ? { type } : undefined, options);
    return res;
  },
  // TODO: 后端 models/load 不存在，暂用 models/switch
  loadModel: async (payload: { model_name?: string; id?: string; type?: string; model_type?: string; path?: string; model_path?: string; options?: any; }) => {
    const res = await post('/api/v1/models/switch', payload);
    return res;
  },
  // TODO: 后端 models/status 不存在，暂用 models 列表
  getModelStatus: async (model_name?: string, options?: { silent?: boolean }) => {
    const res = await get('/api/v1/models', model_name ? { model_name } : undefined, options);
    return res;
  },

  visionDescribe: async (payload: { model_name: string; image_base64?: string; image_path?: string; prompt?: string; }) => {
    return request('/api/v1/vision/describe', {
      method: 'POST',
      body: JSON.stringify(payload),
      timeoutMs: 30000, // 5070 应该在30秒内搞定，如果超过说明后端挂了
    });
  },
  // Image Generation
  getImageModels: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/vision/image/models', undefined, options);
    return res;
  },
  generateImage: (prompt: string, modelPath?: string, loraPath?: string, loraWeight?: number, numImages: number = 1) => 
    post('/api/v1/vision/image/generate', { prompt, modelPath, loraPath, loraWeight, numImages }, { retries: 0 }),
  uploadFile: async (endpoint: string, file: File, additionalData?: Record<string, any>, retryOptions?: { retries?: number, delay?: number }) => {
    return uploadFile(endpoint, file, additionalData, retryOptions);
  },
  // TTS
  tts: (data: any) => post('/api/v1/media/tts', data),
  listVoices: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/media/voices', undefined, options);
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
    const res = await post('/api/v1/vision/analyze-screen', payload);
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
    const res = await post('/api/v1/system/search/web', body);
    return res;
  },
  clearMemory: async (mode: 'all' | 'short' = 'all') => {
    const res = await post('/api/v1/memories/clear', { mode });
    return res;
  },
  
  clearWeightedMemories: async (userId: string = "default") => {
    const res = await del(`/api/v1/memories?user_id=${userId}`);
    return res;
  },

  getWeightedMemories: async (limit: number = 100, minWeight: number = 1.0) => {
    const res = await get('/api/v1/memories', { limit, min_weight: minWeight });
    return res;
  },

  deleteWeightedMemory: async (memoryId: string) => {
    if (!memoryId) {
        throw new Error("Invalid memory ID");
    }
    const res = await del(`/api/v1/memories/${memoryId}`);
    return res;
  },

  // Session Management
  getSessions: async () => {
    const res = await get('/api/v1/sessions', undefined, { retries: 0 }); // No retries to fail fast
    return res;
  },
  createSession: async (title?: string) => {
    // Retry once for creation if needed, but usually we want immediate feedback
    const res = await post('/api/v1/sessions', { title });
    return res;
  },
  deleteSession: async (sessionId: string) => {
    if (!sessionId || sessionId === 'null') {
        throw new Error("Invalid session ID");
    }
    const res = await del(`/api/v1/sessions/${sessionId}`);
    return res;
  },
  deleteMessage: async (sessionId: string, messageId: string) => {
    if (!sessionId || sessionId === 'null') {
        throw new Error("Invalid session ID");
    }
    if (!messageId) {
        throw new Error("Invalid message ID");
    }
    const res = await del(`/api/v1/sessions/${sessionId}/messages/${messageId}`);
    return res;
  },

  // 清除会话历史
  clearHistory: async (sessionId: string, mode: 'all' | 'short' = 'all') => {
    const res = await post('/api/v1/memories/clear', { user_id: sessionId, mode });
    return res;
  },

  // 重新生成最后一条AI回复
  regenerateMessage: async (options?: {
    conversationId?: string;
    modelName?: string;
    maxTokens?: number;
    retryCount?: number;
    onRetry?: (attempt: number, totalAttempts: number, error: any) => void;
    signal?: AbortSignal;
  }) => {
    const requestId = Date.now().toString(36) + Math.random().toString(36).substring(2, 9);
    const retryCount = options?.retryCount || 2;
    const controller = new AbortController();
    const signal = options?.signal || controller.signal;
    
    if (options?.signal) {
      options.signal.addEventListener('abort', () => controller.abort());
    }
    
    const requestParams: any = {
      request_id: requestId,
      conversation_id: options?.conversationId,
    };
    
    if (options?.maxTokens) {
      requestParams.max_tokens = options.maxTokens;
    }
    
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
      ]
    };
    
    try {
      const startTime = performance.now();
      
      const executeRequest = async () => {
        if (signal.aborted) {
          throw new ApiError('请求已取消', ErrorType.CLIENT_ERROR);
        }
        
        const qs = new URLSearchParams();
        if (options?.modelName) qs.append('model', options.modelName);
        const endpoint = qs.toString() ? `/api/v1/chat/regenerate?${qs.toString()}` : '/api/v1/chat/regenerate';
        const response = await post(endpoint, requestParams);

        let processedResponse: any;
        if (response && typeof response === 'object') {
          if (response.status === 'success' && (response as any).data) {
            processedResponse = (response as any).data;
          } else {
            processedResponse = response;
          }
        } else {
          processedResponse = response;
        }
        
        const endTime = performance.now();
        const duration = endTime - startTime;
        logger.logApiResponse('/api/v1/chat/regenerate', 'POST', requestId, 200, duration, {
          hasReply: !!(processedResponse && (processedResponse as any).response),
          regenerated: !!(processedResponse && (processedResponse as any).regenerated)
        });

        const baseReply =
          typeof processedResponse === 'string'
            ? processedResponse
            : (processedResponse?.response as string) ||
              (processedResponse?.reply as string) ||
              '';

        const safeReply = baseReply && typeof baseReply === 'string' ? baseReply : '';

        return {
          reply: safeReply || '（无回复内容）',
          conversation_id: processedResponse?.conversation_id,
          message_id: processedResponse?.message_id,
          request_id: processedResponse?.request_id || requestId,
          status: processedResponse?.status || 'success',
          regenerated: processedResponse?.regenerated || true,
          deleted_message_id: processedResponse?.deleted_message_id,
        };
      };
      
      const executeWithRetryCallbacks = async (attempt = 0): Promise<any> => {
        try {
          return await executeRequest();
        } catch (error: any) {
          const apiError = error instanceof ApiError ? error : createErrorFromResponse(error);
          
          if (attempt < retryOptions.retries && retryOptions.retryableErrors.includes(apiError.type)) {
            attempt++;
            
            if (options?.onRetry) {
              try {
                options.onRetry(attempt, retryOptions.retries, apiError);
              } catch (callbackError) {
                logger.error('Retry callback error', callbackError);
              }
            }
            
            let delay = retryOptions.initialDelay;
            if (retryOptions.exponentialBackoff) {
              delay = Math.min(retryOptions.maxDelay, retryOptions.initialDelay * Math.pow(2, attempt - 1));
            }
            
            if (retryOptions.jitter) {
              const jitterFactor = 0.1;
              const jitterAmount = delay * jitterFactor;
              delay = delay - jitterAmount / 2 + Math.random() * jitterAmount;
            }
            
            await new Promise<void>((resolve, reject) => {
              const timeoutId = setTimeout(() => resolve(), delay);
              signal.addEventListener('abort', () => {
                clearTimeout(timeoutId);
                reject(new ApiError('请求已取消', ErrorType.CLIENT_ERROR));
              }, { once: true });
            });
            
            return executeWithRetryCallbacks(attempt);
          }
          
          logApiError('/api/v1/chat/regenerate', 'POST', apiError, requestId);
          throw apiError;
        }
      };
      
      const result = await executeWithRetryCallbacks();
      logger.info('API重新生成消息完成', { requestId });
      return result;
    } catch (error: any) {
      const apiError = error instanceof ApiError ? error : createErrorFromResponse(error);
      (apiError as any).requestId = requestId;
      throw apiError;
    }
  },

  updateSession: async (sessionId: string, title: string) => {
    const res = await put(`/api/v1/sessions/${sessionId}`, { title });
    return res;
  },
  getSessionHistory: async (sessionId: string, params?: { limit?: number; before?: number }) => {
    const res = await get(`/api/v1/sessions/${sessionId}/history`, params);
    return res;
  },
  
  // 文件上传
  upload: (file: File) => uploadFile('/api/v1/media/upload', file),

  // ===== 专注番茄钟（阶段1+2 MVP）=====
  focusStart: async (payload: { subject: string; planned_minutes: number; mode: string; monitoring: boolean }, options?: { silent?: boolean }) => {
    const res = await post('/api/v1/study/focus-sessions', payload, { ...options, retries: 0 });
    return res;
  },
  focusCurrent: async (options?: { silent?: boolean }) => {
    const res = await get('/api/v1/study/focus-sessions/current', undefined, { ...options, retries: 0 });
    return res;
  },
  focusObservations: async (sessionId: string, observations: any[], options?: { silent?: boolean }) => {
    const res = await post(
      `/api/v1/study/focus-sessions/${sessionId}/observations`,
      { observations },
      { ...options, retries: 0, timeoutMs: 8000 },
    );
    return res;
  },
  focusPause: async (sessionId: string, options?: { silent?: boolean }) => {
    const res = await post(`/api/v1/study/focus-sessions/${sessionId}/pause`, {}, { ...options, retries: 0 });
    return res;
  },
  focusResume: async (sessionId: string, options?: { silent?: boolean }) => {
    const res = await post(`/api/v1/study/focus-sessions/${sessionId}/resume`, {}, { ...options, retries: 0 });
    return res;
  },
  focusFinish: async (sessionId: string, payload?: { self_rating?: number; note?: string }, options?: { silent?: boolean }) => {
    const res = await post(`/api/v1/study/focus-sessions/${sessionId}/finish`, payload || {}, { ...options, retries: 0 });
    return res;
  },
  focusNudge: async (sessionId: string, options?: { silent?: boolean }) => {
    const res = await post(`/api/v1/study/focus-sessions/${sessionId}/nudge`, {}, { ...options, retries: 0 });
    return res;
  },
  focusSummary: async (sessionId: string, options?: { silent?: boolean }) => {
    const res = await get(`/api/v1/study/focus-sessions/${sessionId}/summary`, undefined, { ...options, retries: 0 });
    return res;
  },
  focusHistory: async (limit?: number, options?: { silent?: boolean }) => {
    const res = await get('/api/v1/study/focus-sessions/history', { limit }, { ...options, retries: 0 });
    return res;
  },

  // 可以根据需要添加更多API端点
};

export {};
