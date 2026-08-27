import { useState, useRef, useEffect } from 'react';
import { api } from '../../api/apiService';

interface UsePetVoiceProps {
    onTranscription: (text: string) => void;
}

export const usePetVoice = ({ onTranscription }: UsePetVoiceProps) => {
    const [isRecording, setIsRecording] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const audioChunksRef = useRef<Blob[]>([]);

    const startRecording = async () => {
        // 检查是否在安全上下文（HTTPS 或 localhost）
        if (!window.isSecureContext && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
            alert('无法访问麦克风：浏览器要求在安全环境（HTTPS 或 localhost）下才能使用麦克风。如果您正在使用 IP 地址访问，请尝试使用 localhost 或为您的域名配置 HTTPS。');
            return;
        }

        // 检查浏览器是否支持 mediaDevices
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert('您的浏览器不支持麦克风访问，请更换现代浏览器（如 Chrome, Edge, Firefox）。');
            return;
        }

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
                        onTranscription(response.text);
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
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
            mediaRecorderRef.current.stop();
        }
    };

    const toggleRecording = () => {
        if (isRecording) {
            stopRecording();
        } else {
            startRecording();
        }
    };

    return {
        isRecording,
        isProcessing,
        startRecording,
        stopRecording,
        toggleRecording
    };
};
