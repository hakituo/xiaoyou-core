import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

// 性能和内存优化配置
export const MAX_MESSAGES = 50; // 消息上限，防止内存占用过高
export const MESSAGE_BATCH_SIZE = 20; // 消息批处理大小，用于虚拟滚动

// --- 工具函数 --- 
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
