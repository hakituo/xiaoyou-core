// API配置文件

// 环境类型定义
export type Environment = 'development' | 'production' | 'staging';

// 获取当前环境 - 使用Vite推荐的方式
const getCurrentEnvironment = (): Environment => {
  // 在浏览器环境中，我们通过检测URL或其他方式来判断环境
  try {
    // 检查是否在开发服务器环境
    if (typeof window !== 'undefined' && window.location) {
      const port = window.location.port;
      
      // 开发环境通常端口为5173等
      // 只要端口匹配开发端口，就认为是开发环境，不限制 hostname (以便支持局域网访问)
      if (['5173'].includes(port)) {
        return 'development';
      }
    }
  } catch (e) {
    // 忽略错误，默认返回开发环境
  }
  
  // 默认返回开发环境
  return 'development';
};

// 环境配置
const hostname = (typeof window !== 'undefined' && window.location) ? window.location.hostname : '127.0.0.1';
const origin = (typeof window !== 'undefined' && window.location) ? window.location.origin : 'http://localhost:5000';
const port = (typeof window !== 'undefined' && window.location) ? window.location.port : '';
const isDevServer = ['5173'].includes(port);

// 动态构建API地址
// 优先尝试 8000，如果当前页面就在 800x 端口运行，则尝试连接到对应端口
let apiBase = origin;

// 1. 优先读取 LocalStorage 配置 (Android/用户自定义)
try {
  if (typeof window !== 'undefined') {
    const customUrl = localStorage.getItem('AVELINE_API_URL');
    if (customUrl && customUrl.trim() !== '') {
      apiBase = customUrl.trim();
      // 如果自定义了 URL，我们直接使用它，不再进行后续的自动探测
      // 但我们需要标记这是一个 overrides，以便调试
      console.log('[Config] Using custom API URL:', apiBase);
    } else {
        // Fallback to auto-detection logic
        performAutoDetection();
    }
  } else {
    performAutoDetection();
  }
} catch (e) {
  performAutoDetection();
}

function performAutoDetection() {
  // [新增] 如果是通过 Cloudflare Tunnel 访问，自动配置 API 地址和令牌
  if (typeof window !== 'undefined' && window.location) {
    const currentHost = window.location.hostname;
    const currentOrigin = window.location.origin;
    
    // 检测到 Cloudflare Tunnel 域名
    if (currentHost.includes('trycloudflare.com') || currentHost === 'ai.qishihao.icu') {
      // 通过 Cloudflare Tunnel 访问，API 也指向同一个域名
      apiBase = currentOrigin;
      console.log('[Config] Detected Cloudflare Tunnel, using API:', apiBase);
      
      // 自动配置访问令牌（如果 LocalStorage 中没有）
      // 注意：生产环境应该从环境变量或配置接口获取，不应该硬编码
      try {
        const existingToken = localStorage.getItem('XIAOYOU_ACCESS_TOKEN');
        if (!existingToken || existingToken.trim() === '') {
          // 尝试从环境变量读取 (需要在构建时注入)
          const defaultToken = (import.meta as any).env?.VITE_DEFAULT_ACCESS_TOKEN;
          if (defaultToken && defaultToken.trim() !== '') {
            localStorage.setItem('XIAOYOU_ACCESS_TOKEN', defaultToken);
            console.log('[Config] Auto-configured access token from env');
          } else {
            // 如果没有环境变量，提示用户手动配置
            console.warn('[Config] No access token configured. Please set XIAOYOU_ACCESS_TOKEN in LocalStorage manually.');
          }
        }
      } catch (e) {
        console.warn('[Config] Failed to auto-configure token:', e);
      }
      
      return; // 直接返回，不执行后续逻辑
    }
  }
  
  if (isDevServer) {
    // 开发环境下，默认连接 8000
    // [OPTIMIZE] 强制将 localhost 转换为 127.0.0.1 以规避 Windows IPv6 优先级导致的连接失败问题
    let effectiveHostname = hostname;
    if (hostname === 'localhost') {
      effectiveHostname = '127.0.0.1';
    }
    apiBase = `http://${effectiveHostname}:8000`; 
  }

  // 自动适配：如果当前前端就在 8000-8005 端口运行（比如打包后的预览），API 应该指向自己
  if (port >= '8000' && port <= '8005') {
    apiBase = `http://${hostname}:${port}`;
  }

  // Electron 环境下的特殊处理
  if (typeof window !== 'undefined' && navigator.userAgent.toLowerCase().includes('electron') && origin.startsWith('file://')) {
    apiBase = 'http://127.0.0.1:8000';
  }
}

const environments = {
  development: {
    apiBaseUrl: apiBase,
    debug: true,
    timeout: 120000,
  },
  production: {
    apiBaseUrl: apiBase,
    debug: false,
    timeout: 120000,
  },
  staging: {
    apiBaseUrl: apiBase,
    debug: true,
    timeout: 45000,
  },
};

// 当前环境配置
const currentEnv = getCurrentEnvironment();
const config = environments[currentEnv];

// 导出配置
export default {
  ...config,
  environment: currentEnv,
};
