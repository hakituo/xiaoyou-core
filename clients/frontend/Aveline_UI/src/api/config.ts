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
      
      // 开发环境通常端口为5173或3000等
      // 只要端口匹配开发端口，就认为是开发环境，不限制 hostname (以便支持局域网访问)
      if (['5173', '3000', '3001', '3002'].includes(port)) {
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
const isDevServer = ['5173', '3000', '3001', '3002'].includes(port);

// 动态构建API地址
// 如果是开发服务器，尝试连接到同一主机的8000端口
// 这样在局域网访问(如手机)时，会尝试连接 http://192.168.x.x:8000 而不是 http://127.0.0.1:8000
const apiBase = isDevServer ? `http://${hostname}:8000` : origin;

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
