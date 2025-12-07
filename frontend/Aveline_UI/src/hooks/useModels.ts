import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/apiService';
import { Model } from '../types';

export function useModels() {
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModel, setSelectedModel] = useState<Model | null>(null);

  const fetchModels = useCallback(async () => {
    try {
      // 使用静默模式，避免连接失败时刷屏
      const res = await api.listModels(undefined, { silent: true });
      const list = Array.isArray(res?.data) ? res.data : (Array.isArray(res?.data?.models) ? res.data.models : (Array.isArray(res?.models) ? res.models : []));
      let items: Model[] = list.map((x: any) => ({ 
        id: x.id, 
        name: x.name || x.id, 
        type: x.type, 
        path: x.path,
        quantized: x.quantized
      }));
      
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
    const timer = setInterval(fetchModels, 10000);
    return () => clearInterval(timer);
  }, [fetchModels]);

  // Auto-select default model
  useEffect(() => {
    if (models.length > 0 && !selectedModel) {
      const preferL3 = models.find(x => x.type === 'llm' && /l3/i.test(String(x.id) + String(x.name))) || null;
      const def = preferL3 || models.find(x => x.type === 'llm') || models[0];
      if (def) setSelectedModel(def);
    }
  }, [models, selectedModel]);

  return { models, selectedModel, setSelectedModel };
}
