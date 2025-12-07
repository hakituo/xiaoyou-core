import { useState, useEffect, useRef } from 'react';
import { api } from '../api/apiService';
import { EmotionType } from '../types';
import { calculateMixedColors, getDominantEmotion, EMOTIONS, hexToRgb, rgbToHex } from '../utils/emotion';

// Helper for linear interpolation
const lerp = (start: number, end: number, factor: number) => start + (end - start) * factor;

export function useStatus() {
  const [stats, setStats] = useState({ cpu: 0, gpu: 0, memory: 0 });
  const [connected, setConnected] = useState(true);
  const [clock, setClock] = useState('');
  const [emotion, setEmotion] = useState<EmotionType>('neutral');
  const [currentColors, setCurrentColors] = useState<[string, string, string, string]>(EMOTIONS.neutral.colors);
  const [emotionLockUntil, setEmotionLockUntil] = useState(0);
  
  // Store high-precision RGB values to avoid rounding errors causing "stuck" colors
  const colorValuesRef = useRef(EMOTIONS.neutral.colors.map(hexToRgb));

  // Refs for animation loop to access latest state without dependencies
  const stateRef = useRef({
    stats,
    emotion,
    emotionLockUntil
  });
  
  useEffect(() => {
    stateRef.current = { stats, emotion, emotionLockUntil };
  }, [stats, emotion, emotionLockUntil]);

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
        
        timeoutId = setTimeout(fetchStats, 2000);
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

  // Animation Loop for Color Transition
  useEffect(() => {
    let animationFrameId: number;

    const animate = () => {
      const { stats, emotion, emotionLockUntil } = stateRef.current;
      let targetColors: [string, string, string, string];

      // 1. Determine Target Colors
      if (Date.now() < emotionLockUntil) {
        // Locked: Use current emotion's colors
        targetColors = EMOTIONS[emotion]?.colors || EMOTIONS.neutral.colors;
      } else {
        // Unlocked: Calculate based on system stats (Ambient Mode)
        const c = Math.max(0, Math.min(100, stats.cpu));
        const g = Math.max(0, Math.min(100, stats.gpu));
        const m = Math.max(0, Math.min(100, stats.memory));
        const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
        
        // Adjust weights for more dynamic response
        const w_excited = clamp01((g - 30) / 70) * 0.6 + clamp01((c - 40) / 60) * 0.4;
        const w_angry = clamp01((m - 70) / 30) * 0.8 + clamp01((c - 85) / 15) * 0.2;
        const w_lost = clamp01((m - 85) / 15) * 0.8;
        
        // Happy if balanced load
        const load = (c + g + m) / 3;
        const w_happy = (load > 20 && load < 60) ? 0.5 : 0;
        
        const base = 0.3; // Always some neutral base
        
        const weights: Record<string, number> = {
          neutral: base,
          excited: w_excited,
          angry: w_angry,
          lost: w_lost,
          happy: w_happy,
          shy: 0,
          jealous: 0,
          wronged: 0,
          coquetry: 0
        };
        
        targetColors = calculateMixedColors(weights);
      }

      // 2. Smoothly Interpolate Current -> Target (using float values)
      const factor = 0.01; 
      const currentRGBs = colorValuesRef.current;
      const targetRGBs = targetColors.map(hexToRgb);
      
      const nextRGBs = currentRGBs.map((curr, i) => ({
        r: lerp(curr.r, targetRGBs[i].r, factor),
        g: lerp(curr.g, targetRGBs[i].g, factor),
        b: lerp(curr.b, targetRGBs[i].b, factor)
      }));
      
      // Update ref with new float values
      colorValuesRef.current = nextRGBs;

      // Convert to Hex for UI
      const nextColorsHex = nextRGBs.map(c => rgbToHex(Math.round(c.r), Math.round(c.g), Math.round(c.b))) as [string, string, string, string];
      
      setCurrentColors(nextColorsHex);
      
      animationFrameId = requestAnimationFrame(animate);
    };

    animationFrameId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationFrameId);
  }, []); // Run once

  return { 
    stats, 
    connected,
    clock, 
    emotion, 
    setEmotion, 
    currentColors, 
    setCurrentColors,
    setEmotionLockUntil 
  };
}
