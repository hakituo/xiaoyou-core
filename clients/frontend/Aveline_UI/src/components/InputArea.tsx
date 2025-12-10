import React, { useRef, useState } from 'react';
import { Mic, Send, Image as ImageIcon, Paperclip, Loader2 } from 'lucide-react';
import { api } from '../api/apiService';

interface InputAreaProps {
  input: string;
  setInput: (s: string) => void;
  onSend: () => void;
  isTyping: boolean;
  voices: any[];
  selectedVoiceId: string;
  setSelectedVoiceId: (id: string) => void;
  onUpload?: (file: File) => void;
}

const InputArea = ({ input, setInput, onSend, isTyping, voices, selectedVoiceId, setSelectedVoiceId, onUpload }: InputAreaProps) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        setIsProcessing(true);
        try {
          const response = await api.transcribeAudio(audioBlob);
          if (response && response.text) {
            setInput(input + (input ? ' ' : '') + response.text);
          }
        } catch (error) {
          console.error('Failed to transcribe audio', error);
        } finally {
          setIsProcessing(false);
          setIsRecording(false);
          stream.getTracks().forEach(track => track.stop());
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error('Error accessing microphone:', err);
      alert('无法访问麦克风，请检查权限设置');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  };

  const handleMicClick = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      onUpload?.(e.target.files[0]);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <div className="p-3 pt-0">
      <input 
        type="file" 
        ref={fileInputRef} 
        className="hidden" 
        onChange={handleFileChange} 
      />
      <div className="relative bg-[#18181b]/90 backdrop-blur-md border border-white/10 rounded-[20px] p-1.5 flex items-center gap-2 shadow-lg transition-all focus-within:border-white/20 focus-within:ring-1 focus-within:ring-white/10">
        <button 
          className="p-1.5 ml-1 rounded-full text-white/40 hover:text-white hover:bg-white/10 transition-colors"
          title="上传图片/文件"
          onClick={handleUploadClick}
        >
          <Paperclip size={18} />
        </button>
        
        <div className="w-[1px] h-5 bg-white/10 mx-1" />

        <button 
          className={`p-1.5 mr-1 rounded-full transition-colors ${isRecording ? 'text-red-500 hover:text-red-400 bg-white/10' : 'text-white/40 hover:text-white hover:bg-white/10'} ${isProcessing ? 'opacity-50 cursor-not-allowed' : ''}`}
          title={isRecording ? "停止录音" : "语音输入"}
          onClick={handleMicClick}
          disabled={isProcessing}
        >
          {isProcessing ? <Loader2 className="animate-spin" size={18} /> : <Mic size={18} />}
        </button>

        <input 
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isTyping ? "Aveline is thinking..." : "Ask Aveline..."}
          disabled={isTyping}
          autoComplete="off"
          className="flex-1 bg-transparent border-none outline-none text-white h-9 text-sm placeholder:text-white/20 disabled:opacity-50 min-w-0"
        />

        <button 
          onClick={onSend}
          disabled={!input.trim() || isTyping}
          className="p-2 rounded-full bg-white text-black hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-[0_0_10px_rgba(255,255,255,0.2)] flex-none"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
};

export default InputArea;
