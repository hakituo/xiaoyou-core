import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Message } from '../../types';
import MemoryPanel from '../MemoryPanel';
import PluginsPanel from '../PluginsPanel';
import PersonaPanel from '../PersonaPanel';
import EmotionWidget from '../EmotionWidget';
import StudyPanel from '../StudyPanel';
import ShopPanel from '../ShopPanel';
import DailyDataPanel from '../DailyDataPanel';
import { MobileStatusPanel } from './MobileStatusPanel';
import { MobileChatTab } from './MobileChatTab';

type MobileMainContentProps = {
  activeTab: string;
  messages: Message[];
  isTyping: boolean;
  showTypingIndicator: boolean;
  playingMsgId: number | string | null;
  loadingAudio: boolean;
  currentColors: [string, string, string, string];
  replyDisplayMode?: 'text_and_tts' | 'tts_only';
  onToggleTTS: (id: number | string) => void;
  onDeleteMessage: (id: number | string) => void;
  onSuggestionClick: (text: string) => void;
  input: string;
  setInput: (value: string) => void;
  onSend: () => void;
  voices: any[];
  selectedVoiceId: string;
  setSelectedVoiceId: (value: string) => void;
  onUpload?: (file: File) => void;
  onClearHistory: () => void;
  persona: any;
  onPersonaChange: (value: any) => void;
  models: any[];
  selectedModel: any;
  setSelectedModel: (value: any) => void;
  responseLength: string;
  setResponseLength: (value: string) => void;
  imageModel: any;
  breathingRate: number;
  setBreathingRate: (value: number) => void;
  setEmotion: (value: any) => void;
  setEmotionMix: (value: any) => void;
  emotion: any;
  currentModel: string;
  onSwitchModel: (value: 'cloud' | 'local') => void;
  studyMode: boolean;
  onToggleStudyMode: () => void;
  connected: boolean;
  clock: any;
  stats: any;
  lifeStatus: any;
  breathingSpeed: number;
  breathingPattern: any;
};

export function MobileMainContent({
  activeTab,
  messages,
  isTyping,
  showTypingIndicator,
  playingMsgId,
  loadingAudio,
  currentColors,
  replyDisplayMode,
  onToggleTTS,
  onDeleteMessage,
  onSuggestionClick,
  input,
  setInput,
  onSend,
  voices,
  selectedVoiceId,
  setSelectedVoiceId,
  onUpload,
  onClearHistory,
  persona,
  onPersonaChange,
  models,
  selectedModel,
  setSelectedModel,
  responseLength,
  setResponseLength,
  imageModel,
  breathingRate,
  setBreathingRate,
  setEmotion,
  setEmotionMix,
  emotion,
  currentModel,
  onSwitchModel,
  studyMode,
  onToggleStudyMode,
  connected,
  clock,
  stats,
  lifeStatus,
  breathingSpeed,
  breathingPattern,
}: MobileMainContentProps) {
  return (
    <div className="flex-1 overflow-hidden relative z-10 flex flex-col pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.2 }}
          className="flex-1 w-full h-full flex flex-col overflow-hidden"
        >
          {activeTab === 'Chat' && (
            <MobileChatTab
              messages={messages}
              isTyping={isTyping}
              showTypingIndicator={showTypingIndicator}
              playingMsgId={playingMsgId}
              loadingAudio={loadingAudio}
              currentColors={currentColors}
              replyDisplayMode={replyDisplayMode}
              onToggleTTS={onToggleTTS}
              onDeleteMessage={onDeleteMessage}
              onSuggestionClick={onSuggestionClick}
              input={input}
              setInput={setInput}
              onSend={onSend}
              voices={voices}
              selectedVoiceId={selectedVoiceId}
              setSelectedVoiceId={setSelectedVoiceId}
              onUpload={onUpload}
            />
          )}

          {activeTab === 'Memory' && (
            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
              <MemoryPanel
                memoryData={messages}
                onClearHistory={onClearHistory}
              />
            </div>
          )}

          {activeTab === 'DailyData' && (
            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
              <DailyDataPanel />
            </div>
          )}

          {activeTab === 'Study' && (
            <div className="flex-1 overflow-hidden relative flex flex-col p-2">
              <StudyPanel />
            </div>
          )}

          {activeTab === 'Persona' && (
            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
              <PersonaPanel
                persona={persona}
                onPersonaChange={onPersonaChange}
              />
            </div>
          )}

          {activeTab === 'Plugins' && (
            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
              <PluginsPanel
                models={models}
                selectedModel={selectedModel}
                setSelectedModel={setSelectedModel}
                responseLength={responseLength}
                setResponseLength={setResponseLength}
                imageModel={imageModel}
                breathingRate={breathingRate}
                setBreathingRate={setBreathingRate}
                setEmotion={setEmotion}
                setEmotionMix={setEmotionMix}
                emotion={emotion}
                currentModel={currentModel}
                onSwitchModel={onSwitchModel}
              />
            </div>
          )}

          {activeTab === 'Status' && (
            <div className="flex-1 overflow-y-auto px-4 pt-4 pb-6 space-y-4 custom-scrollbar">
              <EmotionWidget
                emotion={emotion}
                sidebarOpen={true}
                lifeStatus={lifeStatus}
                colors={currentColors}
                speed={breathingSpeed}
                pattern={breathingPattern}
              />
              <MobileStatusPanel
                connected={connected}
                clock={clock}
                stats={stats}
                lifeStatus={lifeStatus}
                colors={currentColors}
                emotion={emotion}
              />
            </div>
          )}

          {activeTab === 'Shop' && (
            <div className="flex-1 overflow-hidden relative flex flex-col p-2 pt-16">
              <ShopPanel platform="mobile" />
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
