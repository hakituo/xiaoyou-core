// API配置文件

// 环境类型定义
export type Environment = 'development' | 'production' | 'staging';

// 获取当前环境 - 使用Vite推荐的方式
const getCurrentEnvironment = (): Environment => {
  // 在浏览器环境中，我们通过检测URL或其他方式来判断环境
  try {
    // 检查是否在开发服务器环境
    if (typeof window !== 'undefined' && window.location) {
      const hostname = window.location.hostname;
      const port = window.location.port;
      
      // 开发环境通常在localhost且端口为5173或3000等
      if ((hostname === 'localhost' || hostname === '127.0.0.1') && 
          (port === '5173' || port === '3000' || port === '3001' || !port)) {
        return 'development';
      }
      
      // 可以根据实际部署情况添加更多环境判断逻辑
    }
  } catch (e) {
    // 忽略错误，默认返回开发环境
  }
  
  // 默认返回开发环境
  return 'development';
};

// 环境配置
const origin = (typeof window !== 'undefined' && window.location) ? window.location.origin : 'http://localhost:5000';
const port = (typeof window !== 'undefined' && window.location) ? window.location.port : '';
const isDevServer = port === '5173' || port === '3000' || port === '3001' || port === '3002';
const apiBase = isDevServer ? 'http://127.0.0.1:8000' : origin;
const environments = {
  development: {
    apiBaseUrl: apiBase,
    debug: true,
    timeout: 120000,
  },
  production: {
    apiBaseUrl: apiBase,
    debug: false,
    timeout: 60000,
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
