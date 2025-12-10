import { useState, useEffect } from 'react';
import { api } from '../api/apiService';
import { EmotionType } from '../types';

export function useStatus() {
  const [stats, setStats] = useState({ cpu: 0, gpu: 0, memory: 0 });
  const [connected, setConnected] = useState(true);
  const [clock, setClock] = useState('');
  const [emotion, setEmotion] = useState<EmotionType>('neutral');
  const [emotionLockUntil, setEmotionLockUntil] = useState(0);

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

        if (res?.metrics) {
          setStats({
            cpu: Math.round(res.metrics.cpu_usage || 0),
            gpu: Math.round(res.metrics.gpu_usage || 0),
            memory: Math.round(res.metrics.memory_usage || 0)
          });
        } else if (res?.data) {
          setStats({
            cpu: Math.round(res.data.cpu_usage || 0),
            gpu: Math.round(res.data.gpu_usage || 0),
            memory: Math.round(res.data.memory_usage || 0)
          });
        } else if (res?.system) {
          setStats({
            cpu: Math.round(res.system.cpu_percent || 0),
            gpu: Math.round(res.system.gpu_percent || 0),
            memory: Math.round(res.system.memory?.percent || 0)
          });
        }
        
        timeoutId = setTimeout(fetchStats, 1000);
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
  }, []);

  return { 
    stats, 
    connected,
    clock, 
    emotion, 
    setEmotion, 
    emotionLockUntil,
    setEmotionLockUntil 
  };
}
