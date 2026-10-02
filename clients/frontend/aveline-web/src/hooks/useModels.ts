import { useState, useEffect, useCallback } from 'react';
import { Capacitor } from '@capacitor/core';
import { api } from '../api/apiService';
import { Model } from '../types';

export function useModels() {
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModel, setSelectedModel] = useState<Model | null>(null);

  const fetchModels = useCallback(async () => {
    try {
      // 使用静默模式，避免连接失败时刷屏
      const res = await api.getModels({ silent: true });
      // 优先检查 available 字段 (新版后端API)，然后是 data (可能被axios包装)，然后是旧版字段
      const list = Array.isArray(res?.available) ? res.available : 
                   (Array.isArray(res?.data?.available) ? res.data.available : 
                   (Array.isArray(res?.data) ? res.data : 
                   (Array.isArray(res?.data?.models) ? res.data.models : 
                   (Array.isArray(res?.models) ? res.models : []))));
      
      let items: Model[] = list.map((x: any) => {
        let name = x.name || x.id;
        
        // 移除各种前缀
        name = name.replace(/^(local|cloud|dashscope|siliconflow|openai):/i, '');
        // 移除 .gguf 后缀
        name = name.replace(/\.gguf$/i, '');
        // 格式化名称：将下划线和连字符替换为空格，并尝试首字母大写
        name = name.replace(/[_-]/g, ' ')
                   .split(' ')
                   .map((word: string) => word.charAt(0).toUpperCase() + word.slice(1))
                   .join(' ');
        
        return { 
          id: x.id, 
          name: name, 
          type: x.type, 
          path: x.path,
          provider: x.provider,
          quantized: x.quantized,
          category: x.category
        };
      });
      
      // Deduplicate items by id
      items = Array.from(new Map(items.map((item) => [item.id, item])).values());
      
      // Only update if there are actual changes in content
      setModels(prev => {
        if (prev.length !== items.length) return items;
        const isSame = prev.every((p, i) => 
          p.id === items[i].id && 
          p.name === items[i].name && 
          p.type === items[i].type && 
          p.path === items[i].path &&
          p.provider === items[i].provider &&
          p.quantized === items[i].quantized
        );
        return isSame ? prev : items;
      });
    } catch (e) {
      // Silent fail for polling
    }
  }, []);

  // Initial fetch and polling
  useEffect(() => {
    fetchModels();

    // 移动端优化：保留轮询以确保模型列表加载成功，但使用较长间隔
    const intervalTime = Capacitor.isNativePlatform() ? 120000 : 60000;

    const timer = setInterval(fetchModels, intervalTime);
    return () => clearInterval(timer);
  }, [fetchModels]);

  // Load saved selection from localStorage
  useEffect(() => {
    try {
      const savedId = localStorage.getItem('selected_model_id');
      if (savedId && models.length > 0 && !selectedModel) {
        const found = models.find(m => m.id === savedId);
        if (found) {
          setSelectedModel(found);
          return;
        }
      }
    } catch {}
    
    // Auto-select default model if no saved selection found
    if (models.length > 0 && !selectedModel) {
      const preferL3 = models.find(x => x.type === 'llm' && /l3/i.test(String(x.id) + String(x.name))) || null;
      const def = preferL3 || models.find(x => x.type === 'llm') || models[0];
      if (def) setSelectedModel(def);
    }
  }, [models, selectedModel]);

  // Persist selection
  useEffect(() => {
    if (selectedModel) {
      localStorage.setItem('selected_model_id', selectedModel.id);
    }
  }, [selectedModel]);

  return { models, selectedModel, setSelectedModel };
}
