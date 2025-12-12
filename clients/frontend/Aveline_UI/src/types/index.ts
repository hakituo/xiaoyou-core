export type EmotionType = 'neutral' | 'happy' | 'shy' | 'angry' | 'jealous' | 'wronged' | 'coquetry' | 'lost' | 'excited';

export interface Message {
  id: number;
  isUser: boolean;
  text: string;
  messageType?: 'text' | 'reaction' | 'voice';
  file?: File;
  fileName?: string;
  fileType?: string;
  fileSize?: number;
  imageBase64?: string;
  imageUrl?: string;
  audioBase64?: string;
  voiceId?: string;
}

export interface WeightedMemory {
  id: string;
  content: string;
  timestamp: number;
  weight: number;
  topics: string[];
  emotions: string[];
  is_important: boolean;
  source: string;
}

export interface Model {
  id: string;
  name: string;
  type: string;
  path: string;
  quantized?: boolean;
}
