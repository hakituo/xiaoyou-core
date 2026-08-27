import { useState, useEffect, useRef, useCallback } from 'react';
import { getBaseUrl } from '../api/apiService';

interface WebSocketMessage {
  type: string;
  content?: any;
  timestamp?: string;
  [key: string]: any;
}

interface UseWebSocketOptions {
  onMessage?: (message: WebSocketMessage) => void;
  reconnectInterval?: number;
  onAuthError?: () => void;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { onMessage, reconnectInterval = 3000 } = options;
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | undefined>(undefined);
  const isUnmountingRef = useRef(false);
  const reconnectAttemptRef = useRef(0);
  const currentReconnectIntervalRef = useRef(reconnectInterval);
  const onAuthErrorRef = useRef(options.onAuthError);
  const isMountedRef = useRef(false);
  
  // Keep the latest onMessage handler in a ref to avoid reconnecting when it changes
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    onAuthErrorRef.current = options.onAuthError;
  }, [options.onAuthError]);

  useEffect(() => {
    currentReconnectIntervalRef.current = reconnectInterval;
  }, [reconnectInterval]);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = undefined;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (isUnmountingRef.current) return;
    if (reconnectTimeoutRef.current) return;

    const base = Math.max(500, currentReconnectIntervalRef.current || 3000);
    const attempt = reconnectAttemptRef.current;
    const cappedAttempt = Math.min(8, attempt);
    const backoff = base * Math.pow(1.5, cappedAttempt);
    const jitter = backoff * (0.15 * Math.random());
    const delay = Math.min(30000, Math.floor(backoff + jitter));

    reconnectTimeoutRef.current = window.setTimeout(() => {
      reconnectTimeoutRef.current = undefined;
      reconnectAttemptRef.current += 1;
      connect();
    }, delay);
  }, []);

  const connect = useCallback(() => {
    if (isUnmountingRef.current) return;

    if (wsRef.current) {
      const state = wsRef.current.readyState;
      if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) {
        console.log('[WebSocket] Already connected or connecting, skipping...');
        return;
      }
      try {
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }
    
    // Construct WebSocket URL from API base URL
    // The API base URL is like http://localhost:8000 or http://localhost:8000/api/v1
    // We need to convert it to ws://localhost:8000/api/v1/ws
    // Ensure we handle trailing slashes correctly and don't duplicate /api/v1 if it's already in apiBaseUrl
    const baseUrl = getBaseUrl().replace(/\/$/, '');
    let wsBaseUrl = baseUrl.replace(/^http/, 'ws').replace(/^https/, 'wss');
    
    // [FRP 适配] 如果检测到是远程穿透端口 18000，则 WebSocket 强制转向 18999
    if (wsBaseUrl.includes(':18000')) {
        wsBaseUrl = wsBaseUrl.replace(':18000', ':18999');
        console.log('[FRP Mode] Redirecting WS port to 18999');
    }
    
    // If apiBaseUrl already includes /api/v1, don't append it again
    let wsUrl = '';
    if (wsBaseUrl.includes('/api/v1')) {
        wsUrl = `${wsBaseUrl}/ws`;
    } else {
        wsUrl = `${wsBaseUrl}/api/v1/ws`;
    }

    // 从 localStorage 获取访问令牌
    const token = localStorage.getItem('XIAOYOU_ACCESS_TOKEN');
    if (token) {
      wsUrl += `?token=${encodeURIComponent(token)}`;
    }

    // 添加 user_id (用于多用户隔离)
    let userId = localStorage.getItem('XIAOYOU_USER_ID');
    if (!userId) {
        userId = 'user_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('XIAOYOU_USER_ID', userId);
    }
    // 如果 URL 已经有参数，用 & 连接
    wsUrl += (wsUrl.includes('?') ? '&' : '?') + `user_id=${encodeURIComponent(userId)}`;

    // 添加 user_name (用于动态称呼)
    const userName = localStorage.getItem('XIAOYOU_USER_NAME');
    if (userName) {
        wsUrl += `&user_name=${encodeURIComponent(userName)}`;
    }
    
    // [FIX] Ensure it connects to /ws if the backend expects it, or handle both.
    // The backend router mounts at /api/v1/ws.
    // However, FastAPIWebSocketAdapter expects connection at /api/v1/ws
    // Let's force it to match the backend expectation.
    
    console.log('[WebSocket] Connecting to WebSocket:', wsUrl);
    console.log('[WebSocket] Base URL:', baseUrl);
    console.log('[WebSocket] WS Base URL:', wsBaseUrl);
    
    try {
      let opened = false;
      const ws = new WebSocket(wsUrl);
      
      ws.onopen = () => {
        opened = true;
        console.log('[WebSocket] ✅ Connected successfully');
        setIsConnected(true);
        reconnectAttemptRef.current = 0;
        // Clear any pending reconnect timeout
        clearReconnectTimer();
      };

      ws.onclose = (event) => {
        console.log('[WebSocket] 🔌 Disconnected', event.code, event.reason);
        setIsConnected(false);
        wsRef.current = null;
        
        const hasToken = !!(token && token.trim());
        const likelyAuthHandshakeFail = !opened && event.code === 1006;
        if (event.code === 1008 || likelyAuthHandshakeFail) {
          console.error('[WebSocket] 鉴权失败: Token 无效或缺失');
          // 触发鉴权失败回调
          if (onAuthErrorRef.current) {
            onAuthErrorRef.current();
          }
          clearReconnectTimer();
          return;
        }

        if (!hasToken && onAuthErrorRef.current) {
          onAuthErrorRef.current();
          clearReconnectTimer();
          return;
        }
        
        // Attempt reconnect
        scheduleReconnect();
      };

      ws.onerror = (error) => {
        console.error('[WebSocket] ❌ Error:', error);
        console.error('[WebSocket] URL:', wsUrl);
        console.error('[WebSocket] readyState:', ws.readyState);
        setIsConnected(false);
        // Don't schedule reconnect here, onclose will handle it
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          // Handle ping from server
          if (data.type === 'ping') {
            // console.log('Received ping, sending pong');
            ws.send(JSON.stringify({
              type: 'pong',
              timestamp: data.timestamp
            }));
            return;
          }

          // [Mobile] Handle proactive notifications
          if (data.notification && (data.subtype === 'proactive_notification' || data.is_proactive)) {
             import('../utils/nativeService').then(({ NativeService }) => {
                const notif = data.notification;
                const title = notif.title || 'Aveline';
                const body = notif.body || (typeof data.content === 'string' ? data.content : '收到一条新消息');
                // Only send notification if NativeService is available
                NativeService.sendNotification(title, body).catch(err => {
                   console.warn('Failed to trigger native notification:', err);
                });
             }).catch(err => {
                console.warn('Failed to load NativeService:', err);
             });
          }

          if (onMessageRef.current) {
            onMessageRef.current(data);
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };
      
      wsRef.current = ws;

    } catch (error) {
      console.error('[WebSocket] Connection failed:', error);
      setIsConnected(false);
      scheduleReconnect();
    }
  }, [clearReconnectTimer, scheduleReconnect]);

  useEffect(() => {
    // 防止 React Strict Mode 导致的重复挂载
    if (isMountedRef.current) {
      console.log('[WebSocket] Already mounted, skipping initialization');
      return;
    }
    
    isMountedRef.current = true;
    console.log('[WebSocket] Component mounted, initializing connection');
    
    connect();

    const handleOnline = () => {
      reconnectAttemptRef.current = 0;
      clearReconnectTimer();
      connect();
    };

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        reconnectAttemptRef.current = 0;
        clearReconnectTimer();
        connect();
      }
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('focus', handleOnline);
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      console.log('[WebSocket] Component unmounting, cleaning up');
      isUnmountingRef.current = true;
      isMountedRef.current = false;
      if (wsRef.current) {
        wsRef.current.close();
      }

      window.removeEventListener('online', handleOnline);
      window.removeEventListener('focus', handleOnline);
      document.removeEventListener('visibilitychange', handleVisibility);
      clearReconnectTimer();
    };
  }, []); // 移除依赖，只在组件挂载时运行一次

  const sendMessage = useCallback((data: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
      return true;
    }
    console.warn('WebSocket is not connected');
    return false;
  }, []);

  return { isConnected, sendMessage };
}
