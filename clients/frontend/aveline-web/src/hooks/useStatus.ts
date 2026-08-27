import { useState, useEffect } from 'react';
import { api } from '../api/apiService';
import { useAvelineStore } from '../store/useStore';
import { Capacitor } from '@capacitor/core';

export function useStatus() {
  const [connected, setConnected] = useState(true);
  const [clock, setClock] = useState('');
  const updateStats = useAvelineStore((state) => state.updateStats);

  // Clock
  useEffect(() => {
    const updateClock = () => {
      const d = new Date();
      const pad = (n: number) => (n < 10 ? '0' + n : '' + n);
      const s = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
      setClock(s);
    };
    updateClock();
    const t = setInterval(updateClock, 1000);
    return () => clearInterval(t);
  }, []);

  // Stats polling with backoff
  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout>;
    let isMounted = true;
    let failCount = 0;

    const fetchStats = async () => {
      try {
        // 使用静默模式，避免连接失败时刷屏
        const res = await api.getHealthMetrics({ silent: true });
        if (!isMounted) return;

        // Reset fail count on success
        failCount = 0;
        setConnected(true);

        let newStats: any = { cpu: 0, gpu: 0, memory: 0, temperature: 0, fps: 0 };

        if (res?.metrics) {
          newStats = {
            cpu: Math.round(res.metrics.cpu_usage || 0),
            gpu: Math.round(res.metrics.gpu_usage || 0),
            memory: Math.round(res.metrics.memory_usage || 0),
            temperature: 0, // TODO: add temperature if available
            fps: 0,
            scheduler: res.metrics.scheduler
          };
        } else if (res?.data) {
          newStats = {
            cpu: Math.round(res.data.cpu_usage || 0),
            gpu: Math.round(res.data.gpu_usage || 0),
            memory: Math.round(res.data.memory_usage || 0),
            temperature: 0,
            fps: 0,
            scheduler: res.data.scheduler
          };
        } else if (res?.system) {
          newStats = {
            cpu: Math.round(res.system.cpu_percent || 0),
            gpu: Math.round(res.system.gpu_percent || 0),
            memory: Math.round(res.system.memory?.percent || 0),
            temperature: 0,
            fps: 0
          };
        }
        
        updateStats(newStats);
        
        // 移动端优化：默认降低频率
        // 如果是在 Status 页面，组件应该自己负责高频刷新，或者调用这里的 refresh 方法（如果有的话）
        // 这里作为全局监控，保持低功耗
        const isNative = Capacitor.isNativePlatform();
        const nextDelay = isNative ? 30000 : 5000; // 移动端30秒，PC端5秒
        timeoutId = setTimeout(fetchStats, nextDelay);
      } catch (e) {
        if (!isMounted) return;
        failCount++;
        if (failCount > 2) setConnected(false);
        const delay = Math.min(15000, 2000 * Math.pow(1.5, failCount));
        timeoutId = setTimeout(fetchStats, delay);
      }
    };

    fetchStats();
    
    return () => {
      isMounted = false;
      clearTimeout(timeoutId);
    };
  }, [updateStats]);

  return { 
    connected,
    clock
  };
}
