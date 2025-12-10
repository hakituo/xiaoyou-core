import React, { useRef, useEffect } from 'react';
import { Message } from '../types';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';
import { Sparkles } from 'lucide-react';

interface ChatPanelProps {
  messages: Message[];
  isTyping: boolean;
  playingMsgId: number | null;
  loadingAudio: boolean;
  currentColors: [string, string, string, string];
  onToggleTTS: (id: number) => void;
  onDelete?: (id: number) => void;
  onSuggestionClick?: (text: string) => void;
}

const ChatPanel = ({ messages, isTyping, playingMsgId, loadingAudio, currentColors, onToggleTTS, onDelete, onSuggestionClick }: ChatPanelProps) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  
  // Check if it's a new topic state
  const isNewTopic = messages.length === 0 || (messages.length === 1 && !messages[0].isUser && (messages[0].text === "新话题已开启。" || messages[0].text.includes("系统就绪")));

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  if (isNewTopic) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-white/50 space-y-8">
            <div className="flex flex-col items-center space-y-6 bg-black/20 backdrop-blur-xl border border-white/5 p-12 rounded-3xl shadow-2xl max-w-2xl w-full">
                <div className="w-24 h-24 rounded-full bg-gradient-to-tr from-white/5 to-white/10 flex items-center justify-center border border-white/10 mb-2 animate-pulse shadow-[0_0_30px_rgba(255,255,255,0.05)]">
                    <Sparkles size={40} className="text-white/80" />
                </div>
                
                <div className="text-center space-y-3">
                    <h2 className="text-3xl font-light tracking-[0.2em] text-white/90 font-[Cinzel]">AVELINE OS</h2>
                    <div className="h-px w-24 bg-gradient-to-r from-transparent via-white/20 to-transparent mx-auto"></div>
                    <p className="text-xs font-mono tracking-widest opacity-40 uppercase">System Online • Ready for Input</p>
                </div>

                <div className="grid grid-cols-2 gap-4 w-full mt-8">
                    {["随便聊聊", "今天过得怎么样？", "讲个故事", "你可以做什么？"].map((text, i) => (
                        <div 
                           key={i} 
                           onClick={() => onSuggestionClick?.(text)}
                           className="group relative overflow-hidden p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 hover:border-white/20 cursor-pointer transition-all duration-300 text-sm text-center font-light tracking-wide hover:shadow-[0_0_20px_rgba(255,255,255,0.05)] hover:-translate-y-0.5"
                        >
                            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000" />
                            <span className="relative z-10 text-white/70 group-hover:text-white/90">{text}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
      );
  }

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
