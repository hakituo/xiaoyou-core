import React, { useRef, useEffect } from 'react';
import { Message } from '../types';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';

interface ChatPanelProps {
  messages: Message[];
  isTyping: boolean;
  playingMsgId: number | null;
  loadingAudio: boolean;
  currentColors: [string, string, string, string];
  onToggleTTS: (id: number) => void;
  onDelete?: (id: number) => void;
}

const ChatPanel = ({ messages, isTyping, playingMsgId, loadingAudio, currentColors, onToggleTTS, onDelete }: ChatPanelProps) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-6 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
       {messages.map((msg) => (
         <div key={msg.id} className={`flex ${msg.isUser ? 'justify-end' : 'justify-start'}`}>
            <MessageBubble 
              message={msg} 
              playingMsgId={playingMsgId} 
              onToggleTTS={onToggleTTS} 
              onDelete={onDelete}
              colors={currentColors}
              loadingAudio={loadingAudio}
            />
         </div>
       ))}
       {isTyping && (
         <div className="flex justify-start">
            <TypingIndicator />
         </div>
       )}
       <div ref={bottomRef} />
    </div>
  );
};

export default ChatPanel;
