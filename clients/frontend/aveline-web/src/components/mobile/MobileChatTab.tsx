import React from 'react';
import { Message } from '../../types';
import ChatPanel from '../ChatPanel';
import InputArea from '../InputArea';

type MobileChatTabProps = {
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
};

export function MobileChatTab({
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
}: MobileChatTabProps) {
  return (
    <>
      <div className="flex-1 overflow-hidden relative flex flex-col">
        <ChatPanel
          messages={messages}
          isTyping={isTyping}
          showTypingIndicator={showTypingIndicator}
          playingMsgId={playingMsgId}
          loadingAudio={loadingAudio}
          currentColors={currentColors}
          replyDisplayMode={replyDisplayMode}
          onToggleTTS={onToggleTTS}
          onDelete={onDeleteMessage}
          onSuggestionClick={onSuggestionClick}
        />
      </div>
      <div className="flex-none pb-safe-bottom bg-zinc-950/50 backdrop-blur-xl border-t border-white/5">
        <InputArea
          input={input}
          setInput={setInput}
          onSend={onSend}
          isTyping={isTyping}
          voices={voices}
          selectedVoiceId={selectedVoiceId}
          setSelectedVoiceId={setSelectedVoiceId}
          onUpload={onUpload}
          isMobile={true}
        />
      </div>
    </>
  );
}
