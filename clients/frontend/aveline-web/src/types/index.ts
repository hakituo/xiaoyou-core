export type EmotionType = 'neutral' | 'happy' | 'shy' | 'angry' | 'jealous' | 'wronged' | 'coquetry' | 'lost' | 'excited';

export interface StudyData {
  title: string;
  content: string;
  filePath: string;
  highlightLines?: number[];
  language?: string;
}

export interface Message {
  id: number | string;
  isUser: boolean;
  text: string;
  timestamp?: number;
  messageType?: 'text' | 'reaction' | 'voice' | 'system' | 'retraction';
  file?: File;
  fileName?: string;
  fileType?: string;
  fileSize?: number;
  imageBase64?: string;
  imageUrl?: string;
  imageStatus?: 'generating' | 'done' | 'error';
  imageError?: string;
  audioBase64?: string;
  voiceId?: string;
  studyData?: StudyData;
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
  provider?: string;
  quantized?: boolean;
  category?: string;
}

export interface CircleMember {
  id: string;
  name: string;
  avatar?: string;
  color: string;
  description?: string;
  isActive?: boolean;
  lastActive?: number;
}

export interface ActorLifeState {
  hunger: number;
  energy: number;
  mood_score: number;
  happiness?: number;
  stress?: number;
  social_desire?: number;
}

export interface CircleState {
  members: CircleMember[];
  activeMembers: string[];
  relationships: Record<string, number>;
  actorLifeStates: Record<string, ActorLifeState>;
  groupMode: boolean;
  messageHistory: {
    aveline: Array<{ id: string; text: string; timestamp: number }>;
    ling: Array<{ id: string; text: string; timestamp: number }>;
  };
}
