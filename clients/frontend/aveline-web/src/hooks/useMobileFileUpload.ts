import { useCallback } from 'react';
import { api } from '../api/apiService';
import { Message } from '../types';

type MobileFileUploadOptions = {
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
};

export function useMobileFileUpload({ setMessages }: MobileFileUploadOptions) {
  const readFileAsDataUrl = useCallback((file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.onload = () => resolve(String(reader.result || ''));
      reader.readAsDataURL(file);
    });
  }, []);

  const handleUpload = useCallback(async (file: File) => {
    const isImage = String(file.type || '').toLowerCase().startsWith('image/');
    const msgId = Date.now();
    let preview = '';
    if (isImage) {
      try {
        preview = await readFileAsDataUrl(file);
      } catch {
        preview = '';
      }
    }

    setMessages(prev => [...prev, {
      id: msgId,
      isUser: true,
      text: isImage ? `[已选择图片: ${file.name}，上传中...]` : `[正在上传文件: ${file.name}...]`,
      ...(isImage && preview ? { imageBase64: preview } : {})
    }]);

    let res: any;
    try {
      res = await api.upload(file);
    } catch (e: any) {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        isUser: false,
        text: `上传失败: ${e?.message || e}`
      }]);
      return;
    }

    const filePath = String(res?.data?.file_path || '');
    if (!(res && res.status === 'success' && filePath)) {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        isUser: false,
        text: `上传失败: ${res?.detail || res?.message || 'Upload failed'}`
      }]);
      return;
    }

    setMessages(prev => {
      const idx = prev.findIndex(m => String(m.id) === String(msgId));
      if (idx < 0) return prev;
      const next = [...prev];
      next[idx] = {
        ...next[idx],
        text: isImage ? `[图片已上传: ${file.name}]` : `文件上传成功: ${file.name}`,
        fileUrl: filePath
      } as Message;
      return next;
    });
  }, [readFileAsDataUrl, setMessages]);

  return { handleUpload };
}
