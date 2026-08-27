export function removeToolUseTags(text: string): string {
  if (!text) return text;
  const tagStart = "[TOOL_USE:";
  let result = "";
  let i = 0;
  
  while (i < text.length) {
    const startIdx = text.indexOf(tagStart, i);
    if (startIdx === -1) {
      result += text.slice(i);
      break;
    }
    
    result += text.slice(i, startIdx);
    
    // Find balanced closing ]
    let balance = 0;
    let endIdx = -1;
    for (let j = startIdx; j < text.length; j++) {
      if (text[j] === '[') {
        balance++;
      } else if (text[j] === ']') {
        balance--;
        if (balance === 0) {
          endIdx = j;
          break;
        }
      }
    }
    
    if (endIdx !== -1) {
      i = endIdx + 1;
    } else {
      // Unbalanced/Unclosed tag (e.g. during streaming), hide it
      i = text.length;
    }
  }
  
  return result;
}

export function smartSegmentText(text: string, isStudyMode: boolean = false): string[] {
  if (!text) return [];

  // 预处理：移除 [TOOL_USE: ...] 标签
  text = removeToolUseTags(text);

  const segments: string[] = [];
  // 优化正则：使用非贪婪匹配，确保能够正确处理多个连续的括号内容
  // 支持中英文括号，支持跨行内容
  const regex = /（[\s\S]*?）|\([\s\S]*?\)/g;
  
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = regex.exec(text)) !== null) {
    const start = match.index;
    const end = regex.lastIndex;
    
    // 处理括号前的内容
    const before = text.slice(lastIndex, start);
    if (before.trim().length > 0) {
      // 恢复按标点断句逻辑，满足用户“遇到句号/感叹号/问号就断句”的需求
      // 同时也满足“问号和感叹号不省略，仅省略句号”的要求
      const parts = before.split(/([。！？.!?]+)/);
      for (let i = 0; i < parts.length; i += 2) {
          const t = parts[i].trim();
          const p = parts[i+1];
          if (t) {
              segments.push((p && /[！？!?]/.test(p)) ? t + p : t);
          } else if (p && /[！？!?]/.test(p)) {
              segments.push(p);
          }
      }
    }
    
    // 放入括号内容（撤回样式）
    segments.push(match[0]);
    
    lastIndex = end;
  }

  // 处理剩余内容
  const tail = text.slice(lastIndex);
  if (tail.trim().length > 0) {
      const parts = tail.split(/([。！？.!?]+)/);
      for (let i = 0; i < parts.length; i += 2) {
          const t = parts[i].trim();
          const p = parts[i+1];
          if (t) {
              segments.push((p && /[！？!?]/.test(p)) ? t + p : t);
          } else if (p && /[！？!?]/.test(p)) {
              segments.push(p);
          }
      }
  }

  return segments;
}

/**
 * 格式化前端显示的标签，将 NSFW 替换为 Local，SFW 替换为 Cloud
 * @param text 原始文本
 * @returns 格式化后的文本
 */
export function isRetractionSegment(value: string): boolean {
  if (!value) return false;
  const trimmed = value.trim();
  // 确保是完整的括号包围
  return /^(\（[\s\S]*\）|\([\s\S]*\))$/.test(trimmed);
}

export function unwrapRetractionText(value: string): string {
  if (!value) return value;
  const trimmed = value.trim();
  if (/^（[\s\S]*）$/.test(trimmed) || /^\([\s\S]*\)$/.test(trimmed)) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

export type StreamTypingToken = {
  type: 'text' | 'retraction';
  value: string;
};

export function tokenizeStreamingText(input: string): { tokens: StreamTypingToken[]; rest: string } {
  if (!input) return { tokens: [], rest: '' };

  // 移除工具调用标签，避免打字机效果显示出来
  input = removeToolUseTags(input);

  const tokens: StreamTypingToken[] = [];
  let i = 0;
  while (i < input.length) {
    const nextOffset = input.slice(i).search(/[（(]/);
    if (nextOffset < 0) {
      // 没有找到括号，剩余所有文本作为普通文本 token
      const remaining = input.slice(i);
      if (remaining) {
        tokens.push({ type: 'text', value: remaining });
        console.log('[tokenizeStreamingText] No brackets found, adding text token:', remaining);
      }
      return { tokens, rest: '' };
    }
    const start = i + nextOffset;
    if (start > i) {
      tokens.push({ type: 'text', value: input.slice(i, start) });
    }
    const openChar = input[start];
    const closeChar = openChar === '（' ? '）' : ')';
    const end = input.indexOf(closeChar, start + 1);
    if (end < 0) {
      // 括号没有闭合，剩余文本作为普通文本 token
      const remaining = input.slice(start);
      if (remaining) {
        tokens.push({ type: 'text', value: remaining });
        console.log('[tokenizeStreamingText] Unclosed bracket, adding text token:', remaining);
      }
      return { tokens, rest: '' };
    }
    tokens.push({ type: 'retraction', value: input.slice(start, end + 1) });
    i = end + 1;
  }
  return { tokens, rest: '' };
}

export function segmentByRetractionOnly(text: string): string[] {
  if (!text) return [];
  
  text = removeToolUseTags(text);

  const regex = /（[\s\S]*?）|\([\s\S]*?\)/g;
  const segments: string[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = regex.exec(text)) !== null) {
    const start = match.index;
    const before = text.slice(lastIndex, start).trim();
    if (before.length > 0) {
      segments.push(before);
    }
    segments.push(match[0]);
    lastIndex = regex.lastIndex;
  }

  const tail = text.slice(lastIndex).trim();
  if (tail.length > 0) {
    segments.push(tail);
  }

  return segments;
}

export function formatDisplayLabel(text: string): string {
  if (!text) return text;
  return text
    .replace(/NSFW/gi, 'Local')
    .replace(/SFW/gi, 'Cloud');
}

export function formatChatTime(input: number | string): string {
  const raw = Number(input);
  if (!Number.isFinite(raw)) return '';
  const ts = raw < 1e12 ? raw * 1000 : raw;
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return '';

  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dateStart = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const diffDays = Math.floor((todayStart - dateStart) / 86400000);
  const timeText = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (diffDays === 0) return timeText;
  if (diffDays === 1) return `昨天 ${timeText}`;
  if (diffDays > 1 && diffDays < 7) {
    const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    return `${week[date.getDay()]} ${timeText}`;
  }
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()} ${timeText}`;
}
