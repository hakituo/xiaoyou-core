export type EmotionType = 'neutral' | 'happy' | 'shy' | 'angry' | 'jealous' | 'wronged' | 'coquetry' | 'lost' | 'excited';

export interface Message {
  id: number;
  isUser: boolean;
  text: string;
  messageType?: 'text' | 'reaction';
  file?: File;
  fileName?: string;
  fileType?: string;
  fileSize?: number;
  imageBase64?: string;
  audioBase64?: string;
}

export interface Model {
  id: string;
  name: string;
  type: string;
  path: string;
  quantized?: boolean;
}
