import { EmotionType } from '../types';

export const EMOTIONS: Record<EmotionType, { 
  label: string; 
  colors: [string, string, string, string]; // [主色, 辉光色, 背景氛围色, 底光色]
  speed: number 
}> = {
  neutral: {
    label: "Neutral",
    colors: ["#6B7280", "#A5ADC1", "#1C1F24", "#4B5563"],
    speed: 5
  },
  happy: {
    label: "Happy",
    colors: ["#F2CE77", "#FFE8B2", "#3A2E13", "#D3A74F"],
    speed: 3.5
  },
  shy: {
    label: "Shy",
    colors: ["#F3B8C8", "#FFD8E3", "#3F1B29", "#E58AA7"],
    speed: 4
  },
  angry: {
    label: "Angry",
    colors: ["#E86A73", "#FFC1C4", "#3D0E14", "#C1444E"],
    speed: 2.5
  },
  jealous: {
    label: "Jealous",
    colors: ["#A58AF8", "#D3C6FF", "#2C2453", "#7E6AD9"],
    speed: 3
  },
  wronged: {
    label: "Grievance",
    colors: ["#8CB2FF", "#CDE0FF", "#1B2A4C", "#5B8AE0"],
    speed: 5.5
  },
  coquetry: {
    label: "Coquetry",
    colors: ["#F6A4C6", "#FFD6EC", "#381C2C", "#CF6D9A"],
    speed: 3.5
  },
  lost: {
    label: "Depressed",
    colors: ["#A3A3AD", "#D8D8E2", "#18181B", "#6E6E78"],
    speed: 6
  },
  excited: {
    label: "Excited",
    colors: ["#5EE3C0", "#C6FFF0", "#0D2E25", "#2FB395"],
    speed: 2
  }
};

export function normalizeEmotion(e: string): EmotionType {
  const map: Record<string, EmotionType> = {
    neutral: 'neutral',
    happy: 'happy',
    angry: 'angry',
    excited: 'excited',
    sad: 'lost',
    upset: 'wronged',
    wronged: 'wronged',
    lost: 'lost',
    shy: 'shy',
    jealous: 'jealous',
    coquetry: 'coquetry',
    tsundere: 'coquetry',
    coquette: 'coquetry'
  };
  const k = String(e || '').toLowerCase();
  if (map[k]) return map[k];
  return (EMOTIONS[k as EmotionType] ? (k as EmotionType) : 'neutral');
}

export function inferEmotionFromText(t: string): EmotionType {
  const s = String(t || '').toLowerCase();
  if (/开心|喜欢|愉快|高兴|满足|喜悦/.test(s)) return 'happy';
  if (/生气|愤怒|火大|糟糕|讨厌|不爽|暴躁/.test(s)) return 'angry';
  if (/兴奋|激动|期待|迫不及待|心跳|颤|热|发热|酥/.test(s)) return 'excited';
  if (/委屈|难过|伤心|失落|难受|低落|沮丧/.test(s)) return 'lost';
  if (/害羞|脸红|不好意思|羞涩/.test(s)) return 'shy';
  if (/吃醋|嫉妒/.test(s)) return 'jealous';
  if (/撒娇|粘人|傲娇|靠近|贴着|拥抱|亲吻|吻|抚|摸|触|靠过来|看着我|靠在|抱紧/.test(s)) return 'coquetry';
  return 'neutral';
}

export function resolveEmotionFromLabel(s: string): EmotionType {
  const t = String(s || '').toLowerCase();
  if (/傲娇|撒娇|轻微傲娇|轻微撒娇|娇|粘人/.test(t)) return 'coquetry';
  if (/害羞|羞涩|脸红|不好意思/.test(t)) return 'shy';
  if (/开心|愉快|高兴|满足|喜悦/.test(t)) return 'happy';
  if (/生气|愤怒|火大|暴躁|烦|不爽/.test(t)) return 'angry';
  if (/兴奋|激动|期待|热情|亢奋/.test(t)) return 'excited';
  if (/委屈/.test(t)) return 'wronged';
  if (/难过|伤心|失落|沮丧|低落/.test(t)) return 'lost';
  if (/嫉妒|吃醋/.test(t)) return 'jealous';
  if (/平静|中性|冷淡|冷静/.test(t)) return 'neutral';
  return normalizeEmotion(t);
}

export function stripEmotionMarkers(text: string): string {
  let s = String(text || '');
  
  // 1. 移除 [EMO:xxx] 格式（包括所有变体）
  s = s.replace(/\[EMO:\s*[^\]]*\]/gi, '');
  
  // 2. 移除 {xxx} 格式的标签（情绪、动作等）
  s = s.replace(/\{[^}]+\}/g, '');
  
  // 3. 移除 *xxx* 格式的动作描写
  s = s.replace(/\*[^*]+\*/g, '');
  
  // 4. 移除 「xxx」 和 『xxx』 格式的旁白
  s = s.replace(/[「『][^」』]+[」』]/g, '');
  
  // 5. 移除 【xxx】 格式的系统提示
  s = s.replace(/【[^】]+】/g, '');
  
  // 6. 移除 [key=value] 格式
  s = s.replace(/\[[a-zA-Z_]+\s*=\s*[^\]]+\]/g, '');
  
  // 7. 移除单独的 [ 或 ] 字符（可能是残留的标签）
  s = s.replace(/[\[\]]/g, '');
  
  // 8. 移除 (xxx) 和 （xxx） 格式的标签（情绪词、动作描写等）
  // 但保留颜文字和表情符号
  const kaomojis = [
    '(^_^)', '(^_-)', '(*^▽^*)', '(≧◡≦)', '(o^▽^o)',
    '(⌒▽⌒)☆', '(￣▽￣)', '(¬_¬ )', '(＃＞＜)', '(;¬_¬)',
    '(￣ω￣;)', '(T_T)', '(; ω ; )', '(._.)', '(///_///)',
    '(o´∀`o)', '(>_<)', '(o_O)', '(._.)?',
    '(¬‿¬)', '(￣▽￣)b', '(ง•̀_•́)ง', '(=^･ω･^=)', '(^._.^)',
    '(◕‿◕)', '(・∀・)', '(´∀｀)',
    '(￣^￣)', '(°ロ°)', '(⊙_⊙)',
  ];
  
  // 先保护颜文字
  const kaomoji_placeholders: string[] = [];
  kaomojis.forEach((kao, idx) => {
    const placeholder = `__KAOMOJI_${idx}__`;
    if (s.includes(kao)) {
      // 使用简单的字符串替换，避免正则表达式转义问题
      while (s.includes(kao)) {
        s = s.replace(kao, placeholder);
      }
      kaomoji_placeholders.push(kao);
    }
  });
  
  // 移除普通括号内容（1-20个字符，避免误伤长句）
  // 暂时注释掉，因为括号内容需要显示为撤回样式，而不是被移除
  // s = s.replace(/[\(（]([^\)）]{1,20})[\)）]/g, '');
  
  // 恢复颜文字
  kaomoji_placeholders.forEach((kao, idx) => {
    const placeholder = `__KAOMOJI_${idx}__`;
    while (s.includes(placeholder)) {
      s = s.replace(placeholder, kao);
    }
  });
  
  // 9. 清理多余空格和标点
  s = s.trim().replace(/\s{2,}/g, ' ');
  
  return s;
}

/**
 * 仅移除系统标签 ([EMO:...], [key=val], {tag})，但保留用于 TTS 的语气指导 ((开心), (angry))
 * 用于发送给 TTS 引擎的文本处理
 */
export function stripSystemTags(text: string): string {
  let s = String(text || '');
  
  // 1. 移除 [EMO:{...}] 或 [EMO: ...] 格式
  s = s.replace(/^\[EMO:\s*\{?.*\}?\]\s*/, '');
  
  // 2. 移除 {happy} {excited} 或 {开心} 格式的纯标签 (通常是系统/动作指令)
  s = s.replace(/\s*\{[^}]+\}\s*/g, ' ');
  
  // 3. 移除 [key=value] 格式
  s = s.replace(/\s*\[[a-zA-Z_]+\s*=\s*[^\]]+\]\s*/g, ' ');
  
  // 4. 注意：我们刻意保留 (...) 和 （...） 以及 [happy] 这种可能被 TTS 模型理解的提示
  // 但为了避免系统指令混入，我们可以移除明确的系统关键词，但保留情绪词
  // 这里简化处理：只移除明确的系统协议，保留所有括号内容给后端 TTS 决定
  
  // 5. 清理多余空格
  s = s.trim().replace(/\s{2,}/g, ' ');
  
  return s;
}

export const ttsParamsForEmotion = (e: EmotionType) => {
  const tone = (e === 'shy' || e === 'coquetry') ? 'shy' : ((e === 'neutral' || e === 'happy' || e === 'wronged') ? 'calm' : 'dark');
  if (tone === 'dark') return { style: 3, speed: 1.02, pitch: 1.0, emotion: 0.6 };
  if (tone === 'shy') return { style: 3, speed: 0.98, pitch: 1.02, emotion: 0.65 };
  return { style: 3, speed: 1.0, pitch: 1.0, emotion: 0.5 };
};

// --- 颜色处理工具函数 ---

// 1. Hex 转 RGB
export const hexToRgb = (hex: string) => {
  if (!hex) return { r: 0, g: 0, b: 0 };
  
  // Handle 3-digit hex
  const shorthandRegex = /^#?([a-f\d])([a-f\d])([a-f\d])$/i;
  hex = hex.replace(shorthandRegex, function(m, r, g, b) {
    return r + r + g + g + b + b;
  });

  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result ? {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16)
  } : { r: 0, g: 0, b: 0 };
};

// 2. RGB 转 Hex
export const rgbToHex = (r: number, g: number, b: number) => {
  // Ensure values are within 0-255
  r = Math.max(0, Math.min(255, Math.round(r)));
  g = Math.max(0, Math.min(255, Math.round(g)));
  b = Math.max(0, Math.min(255, Math.round(b)));
  
  return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1).toUpperCase();
};

// 3. 核心：混合颜色算法
export const calculateMixedColors = (weights: Record<string, number>): [string, string, string, string] => {
  // 初始化4层颜色的累加器 [r, g, b]
  let mixed = Array(4).fill(null).map(() => ({ r: 0, g: 0, b: 0 }));
  let totalWeight = 0;

  Object.entries(weights).forEach(([key, weight]) => {
    const emoKey = key as EmotionType;
    if (EMOTIONS[emoKey] && weight > 0) {
      EMOTIONS[emoKey].colors.forEach((hex, index) => {
        const rgb = hexToRgb(hex);
        mixed[index].r += rgb.r * weight;
        mixed[index].g += rgb.g * weight;
        mixed[index].b += rgb.b * weight;
      });
      totalWeight += weight;
    }
  });

  // 防呆：如果没有权重，返回默认 Neutral
  if (totalWeight === 0) return EMOTIONS.neutral.colors;

  // 计算平均值并转回 Hex
  return mixed.map(rgb => rgbToHex(
    rgb.r / totalWeight,
    rgb.g / totalWeight,
    rgb.b / totalWeight
  )) as [string, string, string, string];
};

// 4. 获取主导情绪（用于 TTS 和 动画速度）
export const getDominantEmotion = (weights: Record<string, number>): EmotionType => {
  let max = 0;
  let dom: EmotionType = 'neutral';
  Object.entries(weights).forEach(([key, w]) => {
    if (w > max) { max = w; dom = key as EmotionType; }
  });
  return dom;
};
