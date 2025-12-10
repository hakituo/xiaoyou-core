import { useState, useEffect, useRef, useCallback } from 'react';
import config from '../api/config';

interface WebSocketMessage {
  type: string;
  content?: any;
  timestamp?: string;
  [key: string]: any;
}

interface UseWebSocketOptions {
  onMessage?: (message: WebSocketMessage) => void;
  reconnectInterval?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { onMessage, reconnectInterval = 3000 } = options;
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | undefined>(undefined);
  const isUnmountingRef = useRef(false);
  
  // Keep the latest onMessage handler in a ref to avoid reconnecting when it changes
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    if (isUnmountingRef.current) return;
    
    // Construct WebSocket URL from API base URL
    // The API base URL is like http://localhost:8000 or http://localhost:8000/api/v1
    // We need to convert it to ws://localhost:8000/api/v1/ws
    // Ensure we handle trailing slashes correctly and don't duplicate /api/v1 if it's already in apiBaseUrl
    const baseUrl = config.apiBaseUrl.replace(/\/$/, '');
    const wsBaseUrl = baseUrl.replace(/^http/, 'ws');
    
    // If apiBaseUrl already includes /api/v1, don't append it again
    let wsUrl = '';
    if (wsBaseUrl.includes('/api/v1')) {
        wsUrl = `${wsBaseUrl}/ws`;
    } else {
        wsUrl = `${wsBaseUrl}/api/v1/ws`;
    }
    
    console.log('Connecting to WebSocket:', wsUrl);
    
    try {
      const ws = new WebSocket(wsUrl);
      
      ws.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
        // Clear any pending reconnect timeout
        if (reconnectTimeoutRef.current) {
            window.clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = undefined;
        }
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected');
        setIsConnected(false);
        wsRef.current = null;
        
        // Attempt reconnect
        if (!isUnmountingRef.current) {
          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, reconnectInterval);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        // onclose will be called after onerror
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

          if (onMessageRef.current) {
            onMessageRef.current(data);
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      wsRef.current = ws;
    } catch (e) {
      console.error('Failed to create WebSocket connection:', e);
      // Retry connection
      if (!isUnmountingRef.current) {
          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, reconnectInterval);
      }
    }
  }, [reconnectInterval]);

  useEffect(() => {
    isUnmountingRef.current = false;
    connect();

    return () => {
      isUnmountingRef.current = true;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback((data: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    } else {
      console.warn('WebSocket is not connected, cannot send message');
    }
  }, []);

  return { isConnected, sendMessage };
}
