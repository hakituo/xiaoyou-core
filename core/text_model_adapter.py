#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文本模型适配器
专注于文本生成任务的适配器
"""

import os
import logging
import json
import time
import asyncio
import torch
import threading
import re
from typing import Dict, Optional, Any, Union, List
from .core_engine.model_manager import get_model_manager
from .utils.base_adapter import BaseAdapter
from .llm.dashscope_client import get_dashscope_client

logger = logging.getLogger(__name__)


class TextModelAdapter(BaseAdapter):
    """
    文本模型适配器
    处理文本生成、对话等任务
    """
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # 默认配置
        default_config = {
            'model_type': 'transformers',  # transformers, ollama, vllm, infer_service
            'text_model_path': '',
            'device': 'auto',
            'quantization': {
                'enabled': False,
                'load_in_8bit': False,
                'load_in_4bit': False,
                'torch_dtype': torch.float16 if torch.cuda.is_available() else torch.float32
            },
            'ollama_base_url': 'http://localhost:11434',
            'ollama_model': 'llama3',
            'vllm_base_url': 'http://localhost:8000/generate',
            'vllm_model': 'facebook/opt-125m',
            'timeout': 60,
            'max_retries': 3
        }
        
        # 合并配置
        self.config = default_config.copy()
        if config:
            self.config.update(config)
        
        # 设置模型类型
        self._model_type = self.config['model_type']
        
        # 设置模型名称
        model_name = f"text_{self._model_type}_{hash(self.config['text_model_path'])}" if self.config['text_model_path'] else f"text_{self._model_type}"
        
        # 调用父类初始化
        super().__init__(get_model_manager(), 'text', model_name)
        
        # 注册模型到管理器
        self._register_model()
        self._llama = None

    def _register_model(self):
        """注册模型到模型管理器"""
        try:
            # 即使text_model_path为空，也注册模型，使用默认路径或占位符
            model_path = self.config['text_model_path'] if self.config['text_model_path'] else 'default_model'
            success = self.model_manager.register_model(
                model_name=self._model_name,
                model_type='llm',
                model_path=model_path
            )
            if success:
                logger.info(f"文本模型已注册: {self._model_name}")
            else:
                logger.warning(f"文本模型注册失败或已存在: {self._model_name}")
                # 如果模型已存在，确保锁已创建
                if self._model_name not in self.model_manager._model_locks:
                    self.model_manager._model_locks[self._model_name] = threading.Lock()
        except Exception as e:
            logger.error(f"注册文本模型失败: {str(e)}")
            # 即使出错也要确保锁已创建
            if not hasattr(self.model_manager, '_model_locks'):
                self.model_manager._model_locks = {}
            if self._model_name not in self.model_manager._model_locks:
                self.model_manager._model_locks[self._model_name] = threading.Lock()

    def _prepare_model_load_params(self) -> Dict[str, Any]:
        """
        准备模型加载参数
        
        Returns:
            Dict: 模型加载参数
        """
        if self._model_type != 'transformers':
            return {}
            
        load_kwargs = {
            'device': self.config['device'],
            'torch_dtype': self.config['quantization']['torch_dtype'],
            'quantized': self.config['quantization']['enabled'],
            'model_kwargs': {}
        }
        
        # 添加量化参数到model_kwargs中，避免与quantization_config冲突
        if self.config['quantization']['load_in_8bit']:
            load_kwargs['model_kwargs']['load_in_8bit'] = True
        elif self.config['quantization']['load_in_4bit']:
            load_kwargs['model_kwargs']['load_in_4bit'] = True
        q = self.config['quantization']
        load_kwargs['quantization_config'] = {
            'enabled': q.get('enabled', False),
            'load_in_4bit': q.get('load_in_4bit', False),
            'load_in_8bit': q.get('load_in_8bit', False),
            'bnb_4bit_quant_type': q.get('bnb_4bit_quant_type', 'nf4'),
            'bnb_4bit_compute_dtype': q.get('torch_dtype', q.get('bnb_4bit_compute_dtype', None)),
            'bnb_4bit_use_double_quant': q.get('bnb_4bit_use_double_quant', True),
            'bitsandbytes': True
        }
        
        return load_kwargs
        
    def load_model(self) -> bool:
        """
        加载文本模型
        
        Returns:
            bool: 是否加载成功
        """
        try:
            if self._model_type != 'transformers':
                self._is_loaded = True
                return True
            
            # 使用基类的加载方法
            return super().load_model()
        except Exception as e:
            logger.error(f"加载文本模型时出错: {str(e)}")
            return False

    def _process_vision_inputs(self, messages):
        """
        处理视觉输入，提取图像和视频
        """
        image_inputs = []
        video_inputs = []
        
        if not messages:
            return image_inputs, video_inputs
            
        for message in messages:
            if message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "image":
                                image_inputs.append(item.get("image"))
                            elif item.get("type") == "image_url":
                                # 处理 image_url 格式 (OpenAI兼容)
                                url = item.get("image_url", {}).get("url", "") if isinstance(item.get("image_url"), dict) else item.get("image_url", "")
                                if url.startswith("data:image"):
                                    # base64 handling could be added here if processor supports it directly
                                    # or convert to PIL Image
                                    pass
                                image_inputs.append(url) # AutoProcessor usually handles URLs
        return image_inputs, video_inputs

    def _chat_with_vision_model(self, model, processor, messages, prompt, max_tokens, temperature, top_p):
        """
        使用视觉模型生成响应
        """
        try:
            logger.info("👁️ 使用视觉模型生成响应")
            
            # 构造 Qwen2-VL 格式的消息
            # 确保 prompt 是字符串 (如果不是，说明已经在 messages 里处理了)
            
            qwen_messages = []
            
            if messages:
                # 转换 messages 格式
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content")
                    
                    new_content = []
                    if isinstance(content, str):
                        new_content.append({"type": "text", "text": content})
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                if item.get("type") == "text":
                                    new_content.append({"type": "text", "text": item.get("text", "")})
                                elif item.get("type") in ["image", "image_url"]:
                                    # 假设 processor 能处理 url 或 PIL Image
                                    # 这里我们需要确保 image 是正确的格式
                                    img_val = item.get("image") or item.get("image_url")
                                    if isinstance(img_val, dict) and "url" in img_val:
                                        img_val = img_val["url"]
                                    new_content.append({"type": "image", "image": img_val})
                    
                    qwen_messages.append({"role": role, "content": new_content})
            else:
                # 如果只有 prompt
                qwen_messages.append({
                    "role": "user", 
                    "content": [{"type": "text", "text": str(prompt)}]
                })

            # 准备输入
            text = processor.apply_chat_template(
                qwen_messages, tokenize=False, add_generation_prompt=True
            )
            
            # 提取图像输入
            image_inputs, video_inputs = self._process_vision_inputs(qwen_messages)
            
            # 处理输入
            inputs = processor(
                text=[text],
                images=image_inputs if image_inputs else None,
                videos=video_inputs if video_inputs else None,
                padding=True,
                return_tensors="pt"
            )
            
            # 移至设备
            device = next(model.parameters()).device
            inputs = inputs.to(device)
            
            # 生成
            generated_ids = model.generate(
                **inputs, 
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p
            )
            
            # 解码
            generated_ids_trimmed = [
                out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )
            
            return output_text[0] if output_text else ""
            
        except Exception as e:
            logger.error(f"视觉模型生成失败: {e}", exc_info=True)
            raise e

    def _clear_memory(self):
        """清理显存"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        import gc
        gc.collect()

    def stream_chat(self, 
                    messages: Optional[List[Dict[str, Any]]] = None,
                    prompt: Optional[Union[str, List, Dict]] = None,
                    max_tokens: int = 512, 
                    temperature: float = 0.7, 
                    top_p: float = 0.9,
                    stop_phrases: Optional[List[str]] = None,
                    **kwargs) -> Any:
        """
        流式生成对话响应
        Returns:
            Generator yielding response chunks
        """
        try:
            # 兼容messages和prompt两种参数格式
            if messages is not None and isinstance(messages, list) and len(messages) > 0:
                user_messages = [msg['content'] for msg in messages if msg.get('role') == 'user']
                if user_messages:
                    prompt = user_messages[-1]
                else:
                    prompt = messages[-1]['content']
            elif prompt is None:
                yield {"status": "error", "error": "必须提供messages或prompt参数"}
                return
            
            if not prompt and not messages:
                 yield {"status": "error", "error": "必须提供messages或prompt参数"}
                 return
            
            if not self._ensure_model_loaded():
                if not self.load_model():
                    yield {"status": "error", "error": "模型加载失败"}
                    return
            
            actual_max = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else 1024
            
            if self._model_type == 'transformers':
                for chunk in self._stream_chat_with_transformers(prompt, actual_max, temperature, top_p, messages, stop_phrases):
                    yield chunk
            elif self._model_type == 'ollama':
                for chunk in self._stream_chat_with_ollama(prompt, actual_max, temperature, top_p):
                    yield chunk
            elif self._model_type == 'vllm':
                for chunk in self._stream_chat_with_vllm(prompt, actual_max, temperature, top_p):
                    yield chunk
            elif self._model_type == 'dashscope':
                response = self._chat_with_dashscope(prompt, actual_max, temperature, top_p, messages)
                yield response
            elif self._model_type == 'infer_service':
                # 推理服务暂不支持流式
                response = self._chat_with_infer_service(prompt, actual_max, temperature, top_p)
                yield response
            elif self._model_type == 'llama_cpp':
                for chunk in self._stream_chat_with_llama_cpp(prompt, actual_max, temperature, top_p, messages):
                    yield chunk
            else:
                yield {"status": "error", "error": f"不支持的模型类型: {self._model_type}"}
                
        except Exception as e:
            logger.error(f"流式生成文本时出错: {str(e)}")
            yield {"status": "error", "error": f"生成错误: {str(e)}"}

    def _stream_chat_with_transformers(self, 
                              prompt: str, 
                              max_tokens: int, 
                              temperature: float, 
                              top_p: float,
                              messages: Optional[List[Dict[str, str]]] = None,
                              stop_phrases: Optional[List[str]] = None):
        """
        使用Transformers模型流式生成响应
        """
        from transformers import TextIteratorStreamer
        from threading import Thread
        
        model = self.model_manager.get_model(self._model_name)
        tokenizer = self.model_manager.get_tokenizer(self._model_name)
        
        if not model or not tokenizer:
            yield "模型或分词器未加载"
            return

        device = next(model.parameters()).device
        
        # 构造输入
        chat_messages = messages
        if chat_messages is None and hasattr(tokenizer, 'apply_chat_template'):
             # 简单的 prompt 转 message 逻辑 (省略复杂解析)
             chat_messages = [{"role": "user", "content": prompt}]
             
        if chat_messages is not None and hasattr(tokenizer, 'apply_chat_template'):
            try:
                input_ids = tokenizer.apply_chat_template(chat_messages, add_generation_prompt=True, return_tensors='pt')
                input_ids = input_ids.to(device)
            except Exception:
                inputs = tokenizer(prompt, return_tensors='pt')
                input_ids = inputs.input_ids.to(device)
        else:
            inputs = tokenizer(prompt, return_tensors='pt')
            input_ids = inputs.input_ids.to(device)
            
        streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
        
        generation_kwargs = dict(
            input_ids=input_ids,
            streamer=streamer,
            max_new_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id
        )
        
        thread = Thread(target=model.generate, kwargs=generation_kwargs)
        thread.start()
        
        for new_text in streamer:
            yield new_text

    def _stream_chat_with_llama_cpp(self,
                             prompt: str,
                             max_tokens: int,
                             temperature: float,
                             top_p: float,
                             messages: Optional[List[Dict[str, str]]] = None):
        """
        使用llama_cpp流式生成响应
        """
        if self._llama is None:
            # 尝试初始化 (复用 _chat_with_llama_cpp 的逻辑，这里简化)
            try:
                self._chat_with_llama_cpp(prompt, max_tokens, temperature, top_p, messages) # 触发初始化
            except Exception:
                yield "模型初始化失败"
                return

        # 优先使用 chat completion 接口
        if messages and hasattr(self._llama, 'create_chat_completion'):
            stop_tokens = ["User:", "user:", "\nUser", "<|user|>", "<|end|>", "<|endoftext|>", "\n\n\n"]
            valid_messages = [m for m in messages if isinstance(m, dict) and 'role' in m and 'content' in m]
            
            stream = self._llama.create_chat_completion(
                messages=valid_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop_tokens,
                stream=True
            )
            
            for chunk in stream:
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    delta = chunk['choices'][0].get('delta', {})
                    if 'content' in delta:
                        yield delta['content']
        else:
            # 回退到 text completion
            stop_tokens = ["User:", "user:", "\nUser", "<|user|>", "<|end|>", "<|endoftext|>"]
            stream = self._llama.create_completion(
                prompt=prompt, 
                max_tokens=max_tokens, 
                temperature=temperature, 
                top_p=top_p,
                stop=stop_tokens,
                stream=True
            )
            for chunk in stream:
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    text = chunk['choices'][0].get('text', '')
                    yield text

    def _stream_chat_with_ollama(self, 
                         prompt: str, 
                         max_tokens: int, 
                         temperature: float, 
                         top_p: float) -> str:
        """
        使用Ollama API流式生成响应
        """
        try:
            import requests
            import json
            
            url = f"{self.config['ollama_base_url']}/generate"
            model_name = self.config.get("ollama_model", "llama3")
            
            payload = {
                "model": model_name,
                "prompt": prompt,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p
                },
                "stream": True
            }
            
            headers = {"Content-Type": "application/json"}
            
            with requests.post(url, json=payload, headers=headers, stream=True) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            data = json.loads(line)
                            if 'response' in data:
                                yield data['response']
                            if data.get('done', False):
                                break
                else:
                    yield f"Ollama API调用失败: {response.status_code}"
        except Exception as e:
             yield f"Ollama处理错误: {str(e)}"

    def _stream_chat_with_vllm(self, 
                        prompt: str, 
                        max_tokens: int, 
                        temperature: float, 
                        top_p: float) -> str:
        """
        使用vLLM API流式生成响应
        """
        try:
            import requests
            import json
            
            url = self.config["vllm_base_url"]
            model_name = self.config.get("vllm_model", "facebook/opt-125m")
            
            payload = {
                "prompt": prompt,
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": True
            }
            
            headers = {"Content-Type": "application/json"}
            
            with requests.post(url, json=payload, headers=headers, stream=True) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            # vLLM SSE format: data: {...}
                            decoded_line = line.decode('utf-8')
                            if decoded_line.startswith("data: "):
                                data_str = decoded_line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    # vLLM returns full text in each chunk usually? No, depends on config.
                                    # Usually choices[0].text or delta
                                    if 'choices' in data:
                                        choice = data['choices'][0]
                                        if 'text' in choice:
                                            # vLLM might return accumulated text, need to check docs.
                                            # Assuming standard OpenAI compatible or vLLM native which might be accumulated.
                                            # For simplicity, let's assume it returns diff or handle it.
                                            # Actually vLLM native /generate returns list of strings.
                                            # Let's assume standard OpenAI compatible /v1/completions if using vLLM as server.
                                            # But url defaults to /generate.
                                            # vLLM /generate stream returns: {"text": ["..."], ...}
                                            text = choice['text']
                                            # This might be full text. 
                                            # TODO: Handle vLLM streaming correctly. For now yield text.
                                            yield text
                                except:
                                    pass
                else:
                     yield f"vLLM API调用失败: {response.status_code}"
        except Exception as e:
             yield f"vLLM处理错误: {str(e)}"

    def chat(self, 
             messages: Optional[List[Dict[str, Any]]] = None,
             prompt: Optional[Union[str, List, Dict]] = None,
             max_tokens: int = 512, 
             temperature: float = 0.7, 
             top_p: float = 0.9,
             stop_phrases: Optional[List[str]] = None,
             **kwargs) -> Dict[str, Any]:
        """
        使用文本模型生成对话响应 (带重试机制)
        """
        try:
            # 兼容messages和prompt两种参数格式
            if messages is not None and isinstance(messages, list) and len(messages) > 0:
                user_messages = [msg['content'] for msg in messages if msg.get('role') == 'user']
                if user_messages:
                    prompt = user_messages[-1]
                else:
                    prompt = messages[-1]['content']
            elif prompt is None:
                return {"status": "error", "error": "必须提供messages或prompt参数"}
            
            if not prompt and not messages:
                 return {"status": "error", "error": "必须提供messages或prompt参数"}
            
            self._performance_tracker.start_tracking()
            
            if not self._ensure_model_loaded():
                if not self.load_model():
                    return {"status": "error", "error": "模型加载失败"}
            
            actual_max = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else 1024
            
            # 重试逻辑
            max_retries = self.config.get('max_retries', 3)
            retry_count = 0
            last_error = None
            
            while retry_count <= max_retries:
                try:
                    if self._model_type == 'transformers':
                        response = self._chat_with_transformers(prompt, actual_max, temperature, top_p, messages, stop_phrases)
                    elif self._model_type == 'ollama':
                        response = self._chat_with_ollama(prompt, actual_max, temperature, top_p)
                    elif self._model_type == 'vllm':
                        response = self._chat_with_vllm(prompt, actual_max, temperature, top_p)
                    elif self._model_type == 'infer_service':
                        response = self._chat_with_infer_service(prompt, actual_max, temperature, top_p)
                    elif self._model_type == 'dashscope':
                        response = self._chat_with_dashscope(prompt, actual_max, temperature, top_p, messages)
                    elif self._model_type == 'llama_cpp':
                        response = self._chat_with_llama_cpp(prompt, actual_max, temperature, top_p, messages)
                    else:
                        return {"status": "error", "error": f"不支持的模型类型: {self._model_type}"}
                    
                    self._performance_tracker.end_tracking()
                    return {"status": "success", "response": response}
                    
                except (RuntimeError, Exception) as e:
                    last_error = e
                    error_str = str(e)
                    
                    # 检查是否是内存错误 (OOM)
                    is_oom = "out of memory" in error_str.lower() or "allocate" in error_str.lower() or isinstance(e, MemoryError)
                    
                    if is_oom:
                        logger.warning(f"检测到OOM错误 (尝试 {retry_count+1}/{max_retries+1}): {error_str}")
                        self._clear_memory()
                        # 尝试减少max_tokens
                        if actual_max > 128:
                            actual_max = int(actual_max * 0.7)
                            logger.info(f"减少max_tokens至: {actual_max}")
                    else:
                        logger.warning(f"生成出错 (尝试 {retry_count+1}/{max_retries+1}): {error_str}")
                    
                    retry_count += 1
                    if retry_count <= max_retries:
                        time.sleep(1 * retry_count)  # 指数退避
                    else:
                        break

            # 所有重试都失败
            self._performance_tracker.end_tracking(error_occurred=True)
            logger.error(f"生成文本失败，已重试{max_retries}次: {str(last_error)}")
            return {"status": "error", "error": f"生成失败: {str(last_error)}"}
            
        except Exception as e:
            self._performance_tracker.end_tracking(error_occurred=True)
            logger.error(f"生成文本时出错: {str(e)}")
            return {"status": "error", "error": f"生成错误: {str(e)}"}

    def generate(self,
                 prompt: Optional[str] = None,
                 messages: Optional[List[Dict[str, str]]] = None,
                 max_tokens: int = 512,
                 temperature: float = 0.7,
                 top_p: float = 0.9) -> Dict[str, Any]:
        try:
            res = self.chat(messages=messages, prompt=prompt, max_tokens=max_tokens, temperature=temperature, top_p=top_p)
            if res.get("status") == "success":
                return {"status": "success", "data": {"text": res.get("response", "")}}
            return {"status": "error", "error": res.get("error", "生成失败")}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _chat_with_transformers(self, 
                              prompt: str, 
                              max_tokens: int, 
                              temperature: float, 
                              top_p: float,
                              messages: Optional[List[Dict[str, str]]] = None,
                              stop_phrases: Optional[List[str]] = None) -> str:
        """
        使用本地Transformers模型生成响应
        """
        logger.info(f"准备使用transformers模型生成响应，模型名称: {self._model_name}")
        
        # 获取模型和分词器
        model = self.model_manager.get_model(self._model_name)
        tokenizer = self.model_manager.get_tokenizer(self._model_name)
        
        logger.info(f"获取模型结果: model={model is not None}, tokenizer={tokenizer is not None}")
        
        if not model:
            raise Exception(f"模型未加载: {self._model_name}")
        if not tokenizer:
            raise Exception(f"分词器未加载: {self._model_name}")
            
        # 检查是否为 Vision Processor (针对 Qwen2-VL 等)
        if hasattr(tokenizer, 'image_processor') or 'Processor' in str(type(tokenizer)):
             return self._chat_with_vision_model(model, tokenizer, messages, prompt, max_tokens, temperature, top_p)
        
        try:
            device = next(model.parameters()).device
            use_chat = False
            chat_messages = messages if isinstance(messages, list) and messages else None
            if chat_messages is None and hasattr(tokenizer, 'apply_chat_template'):
                try:
                    lines = str(prompt or '').splitlines()
                    sys_buf = []
                    parsed = []
                    name = None
                    for ln in lines:
                        if not ln:
                            continue
                        m_user = re.match(r'^\s*用户\s*:\s*(.*)$', ln)
                        if m_user:
                            if sys_buf:
                                parsed.append({'role': 'system', 'content': '\n'.join(sys_buf).strip()})
                                sys_buf = []
                            parsed.append({'role': 'user', 'content': m_user.group(1).strip()})
                            continue
                        m_asst = re.match(r'^\s*([^:]+)\s*:\s*(.*)$', ln)
                        if m_asst and m_asst.group(1).strip() != '用户':
                            name = m_asst.group(1).strip()
                            content = m_asst.group(2).strip()
                            if content:
                                parsed.append({'role': 'assistant', 'content': content})
                            continue
                        sys_buf.append(ln)
                    if sys_buf:
                        parsed.insert(0, {'role': 'system', 'content': '\n'.join(sys_buf).strip()})
                    parsed = [m for m in parsed if isinstance(m, dict) and m.get('content')]
                    if any(m.get('role') == 'user' for m in parsed):
                        chat_messages = parsed
                except Exception:
                    chat_messages = None
            if chat_messages is not None and hasattr(tokenizer, 'apply_chat_template'):
                try:
                    input_ids = tokenizer.apply_chat_template(chat_messages, add_generation_prompt=True, return_tensors='pt')
                    input_ids = input_ids.to(device)
                    stopping = None
                    if stop_phrases:
                        from transformers import StoppingCriteria, StoppingCriteriaList
                        class PhraseStop(StoppingCriteria):
                            def __init__(self, phrases_ids):
                                super().__init__()
                                self.phrases_ids = phrases_ids
                            def __call__(self, input_ids, scores, **kwargs):
                                seq = input_ids[0].tolist()
                                for p in self.phrases_ids:
                                    L = len(p)
                                    if L > 0 and len(seq) >= L and seq[-L:] == p:
                                        return True
                                return False
                        phrases_ids = []
                        for s in stop_phrases:
                            try:
                                ids = tokenizer(s, add_special_tokens=False, return_tensors='pt').input_ids[0].tolist()
                                if ids:
                                    phrases_ids.append(ids)
                            except Exception:
                                pass
                        if phrases_ids:
                            stopping = StoppingCriteriaList([PhraseStop(phrases_ids)])
                    with torch.no_grad():
                        output = model.generate(
                            input_ids=input_ids,
                            max_new_tokens=max_tokens,
                            temperature=temperature,
                            top_p=top_p,
                            do_sample=True,
                            pad_token_id=tokenizer.eos_token_id,
                            eos_token_id=tokenizer.eos_token_id,
                            stopping_criteria=stopping
                        )
                    gen_ids = output[0][input_ids.shape[-1]:]
                    response = tokenizer.decode(gen_ids, skip_special_tokens=True)
                    return response.strip()
                except Exception:
                    pass
            inputs = tokenizer(prompt, return_tensors='pt')
            inputs = {k: v.to(device) for k, v in inputs.items()}
            stopping = None
            if stop_phrases:
                from transformers import StoppingCriteria, StoppingCriteriaList
                class PhraseStop(StoppingCriteria):
                    def __init__(self, phrases_ids):
                        super().__init__()
                        self.phrases_ids = phrases_ids
                    def __call__(self, input_ids, scores, **kwargs):
                        seq = input_ids[0].tolist()
                        for p in self.phrases_ids:
                            L = len(p)
                            if L > 0 and len(seq) >= L and seq[-L:] == p:
                                return True
                        return False
                phrases_ids = []
                for s in stop_phrases:
                    try:
                        ids = tokenizer(s, add_special_tokens=False, return_tensors='pt').input_ids[0].tolist()
                        if ids:
                            phrases_ids.append(ids)
                    except Exception:
                        pass
                if phrases_ids:
                    stopping = StoppingCriteriaList([PhraseStop(phrases_ids)])
            with torch.no_grad():
                output = model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=True,
                    pad_token_id=tokenizer.eos_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                    stopping_criteria=stopping
                )
            response = tokenizer.decode(output[0], skip_special_tokens=True)
            if response.startswith(prompt):
                response = response[len(prompt):].strip()
            elif prompt in response:
                parts = response.split(prompt)
                if len(parts) > 1:
                    response = parts[-1].strip()
            unwanted_starters = ['吧。', '的。', '了。', '呢。', '啊。', '！', '？', '。', '，', '：', '；']
            for starter in unwanted_starters:
                if response.startswith(starter):
                    response = response[len(starter):].strip()
                    break
            return response
        except Exception as e:
            logger.error(f"生成响应时出错: {str(e)}", exc_info=True)
            raise

    def _chat_with_llama_cpp(self,
                             prompt: str,
                             max_tokens: int,
                             temperature: float,
                             top_p: float,
                             messages: Optional[List[Dict[str, str]]] = None) -> str:
        try:
            from llama_cpp import Llama
        except ImportError:
            raise Exception("未安装 llama_cpp 模块，请运行 pip install llama-cpp-python")
        except Exception as e:
            raise Exception(f"导入 llama_cpp 失败: {str(e)}")

        if self._llama is None:
            model_path = self.config.get('text_model_path') or ''
            if not model_path:
                raise Exception('缺少GGUF模型路径')
            
            # 尝试释放 PyTorch 显存，为 llama_cpp 腾出空间
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            # 获取配置参数
            n_gpu_layers = int(self.config.get('n_gpu_layers', -1))
            n_batch = int(self.config.get('n_batch', 256))  # 降低默认 batch size 以节省显存
            # 降低默认上下文长度，防止 OOM
            n_ctx_default = 2048
            if max_tokens * 4 > n_ctx_default:
                n_ctx_default = max_tokens * 4
            n_ctx = int(self.config.get('n_ctx', n_ctx_default))
            
            logger.info(f"初始化 llama_cpp: n_gpu_layers={n_gpu_layers}, n_ctx={n_ctx}, n_batch={n_batch}")
            
            # 尝试释放显存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            self._llama = Llama(
                model_path=model_path, 
                n_ctx=n_ctx, 
                n_threads=8, 
                n_batch=n_batch, 
                n_gpu_layers=n_gpu_layers,
                verbose=False  # 禁用底层详细日志，防止终端阻塞
            )
        
        # 每次生成前清理显存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        # 优先使用 chat completion 接口
        if messages and hasattr(self._llama, 'create_chat_completion'):
            try:
                # 确保消息格式正确
                valid_messages = []
                for msg in messages:
                    if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                        valid_messages.append(msg)
                
                if valid_messages:
                    logger.info("使用llama_cpp create_chat_completion接口")
                    
                    # 构造停止词列表
                    stop_tokens = ["User:", "user:", "\nUser", "<|user|>", "<|end|>", "<|endoftext|>", "\n\n\n"]
                    
                    out = self._llama.create_chat_completion(
                        messages=valid_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        stop=stop_tokens
                    )
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    return out['choices'][0]['message']['content'].strip()
            except Exception as e:
                error_str = str(e)
                logger.warning(f"llama_cpp chat completion 失败: {error_str}")
                
                # 如果是严重的内存访问错误，不要回退，直接抛出异常并重置模型
                if "access violation" in error_str.lower() or "segmentation fault" in error_str.lower():
                    logger.error("检测到严重模型错误，重置模型实例")
                    self._llama = None
                    raise Exception(f"模型发生严重错误，已重置: {error_str}")
                
                logger.warning("尝试回退到 text completion")
        
        # 回退到 text completion
        stop_tokens = ["User:", "user:", "\nUser", "<|user|>", "<|end|>", "<|endoftext|>"]
        out = self._llama.create_completion(
            prompt=prompt, 
            max_tokens=max_tokens, 
            temperature=temperature, 
            top_p=top_p,
            stop=stop_tokens
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        txt = ''
        ch = out.get('choices')
        if isinstance(ch, list) and ch:
            txt = str(ch[0].get('text', ''))
        return txt.strip()

    def _chat_with_ollama(self, 
                         prompt: str, 
                         max_tokens: int, 
                         temperature: float, 
                         top_p: float) -> str:
        """
        使用Ollama API生成响应
        """
        try:
            import requests
            
            url = f"{self.config['ollama_base_url']}/generate"
            model_name = self.config.get("ollama_model", "llama3")
            
            payload = {
                "model": model_name,
                "prompt": prompt,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p
                },
                "stream": False
            }
            
            headers = {"Content-Type": "application/json"}
            timeout = self.config.get("timeout", 60)
            
            logger.info(f"调用Ollama API: {url}, 模型: {model_name}")
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("response", "")
            else:
                error_msg = f"Ollama API调用失败: HTTP {response.status_code}, {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)
                
        except ImportError:
            raise Exception("需要安装requests库")
        except Exception as e:
            logger.error(f"Ollama处理错误: {str(e)}")
            raise Exception(f"Ollama处理错误: {str(e)}")

    def _chat_with_vllm(self, 
                        prompt: str, 
                        max_tokens: int, 
                        temperature: float, 
                        top_p: float) -> str:
        """
        使用vLLM API生成响应
        """
        try:
            import requests
            
            url = self.config["vllm_base_url"]
            model_name = self.config.get("vllm_model", "facebook/opt-125m")
            
            payload = {
                "prompt": prompt,
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "skip_special_tokens": True
            }
            
            headers = {"Content-Type": "application/json"}
            timeout = self.config.get("timeout", 60)
            
            logger.info(f"调用vLLM API: {url}, 模型: {model_name}")
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("text", "")
            else:
                error_msg = f"vLLM API调用失败: HTTP {response.status_code}, {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)
                
        except ImportError:
            raise Exception("需要安装requests库")
        except Exception as e:
            logger.error(f"vLLM处理错误: {str(e)}")
            raise Exception(f"vLLM处理错误: {str(e)}")

    def _chat_with_dashscope(self,
                            prompt: str,
                            max_tokens: int,
                            temperature: float,
                            top_p: float,
                            messages: Optional[List[Dict[str, str]]] = None) -> str:
        """
        使用DashScope (Qwen) 生成响应
        """
        try:
            client = get_dashscope_client()
            
            # DashScope generate is async, so we need to run it
            # If we are in an async loop, this might fail with "asyncio.run() cannot be called from a running event loop"
            # But TextModelAdapter methods are sync. 
            # If called from async context (like FastAPI), we should ideally use await, but this method is sync.
            # For now, we assume this is called in a thread pool or we use a workaround.
            
            # However, _chat_with_infer_service uses asyncio.run() which implies this adapter 
            # is expected to be run in a way that allows it (e.g. thread pool).
            
            # Check if there is a running loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
                
            if loop and loop.is_running():
                # This is tricky. We are in a sync method called from async context?
                # Or this sync method is called in run_in_threadpool.
                # If run_in_threadpool, there is no loop in that thread usually.
                # So asyncio.run() works.
                # But if called directly from async function without await/executor, it fails.
                # Given FastAPI structure, it's likely run_in_threadpool or blocked.
                
                # For safety, we can try to use the client's sync method if it had one, but it is async only.
                # We'll assume thread pool usage (standard for sync methods in FastAPI).
                future = asyncio.run_coroutine_threadsafe(client.generate(
                    prompt=prompt,
                    history=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p
                ), loop)
                result = future.result()
            else:
                result = asyncio.run(client.generate(
                    prompt=prompt,
                    history=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p
                ))
            
            if result.get("status") == "success":
                return result.get("text", "")
            else:
                raise Exception(result.get("error", "Unknown error"))
                
        except Exception as e:
            logger.error(f"DashScope处理错误: {str(e)}")
            raise Exception(f"DashScope处理错误: {str(e)}")

    def _chat_with_infer_service(self, 
                                prompt: str, 
                                max_tokens: int, 
                                temperature: float, 
                                top_p: float) -> str:
        """
        使用推理服务生成响应
        """
        try:
            # 尝试导入推理服务客户端
            from .llm.infer_service_client import get_infer_client
            INFER_SERVICE_AVAILABLE = True
        except ImportError:
            INFER_SERVICE_AVAILABLE = False
            raise Exception("推理服务客户端不可用")
        
        try:
            # 初始化推理服务客户端
            infer_client = get_infer_client()
            
            # 调用异步方法生成响应
            result = asyncio.run(infer_client.generate(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p
            ))
            
            # 解析结果
            return result.get("text", "")
            
        except Exception as e:
            logger.error(f"推理服务处理错误: {str(e)}")
            raise Exception(f"推理服务处理错误: {str(e)}")

    def unload(self) -> bool:
        """
        卸载模型
        
        Returns:
            bool: 是否卸载成功
        """
        return self.unload_model()

    def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            健康状态信息
        """
        try:
            result = {
                "status": "healthy",
                "model_type": self._model_type,
                "timestamp": time.time()
            }
            
            if self._model_type == 'transformers':
                # 检查本地模型
                result["model_loaded"] = self.is_loaded
                result["model_path"] = self.config["text_model_path"]
                
                if not self.is_loaded:
                    result["status"] = "warning"
                    result["message"] = "模型未加载，但可以按需加载"
                    
            elif self._model_type == 'ollama':
                # 测试Ollama API连接
                try:
                    import requests
                    url = f"{self.config['ollama_base_url']}/tags"
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        result["ollama_connected"] = True
                        result["ollama_models"] = [model["name"] for model in response.json().get("models", [])]
                    else:
                        result["status"] = "unhealthy"
                        result["error"] = f"Ollama API连接失败: HTTP {response.status_code}"
                        result["ollama_connected"] = False
                except Exception as e:
                    result["status"] = "unhealthy"
                    result["error"] = f"Ollama连接错误: {str(e)}"
                    result["ollama_connected"] = False
                    
            elif self._model_type == 'vllm':
                # 测试vLLM API连接
                try:
                    # 使用简单的请求测试vLLM连接
                    test_prompt = "Hello, are you working?"
                    test_response = self._chat_with_vllm(test_prompt, 10, 0.7, 0.9)
                    result["vllm_connected"] = True
                    result["test_response"] = test_response[:50] + "..." if len(test_response) > 50 else test_response
                except Exception as e:
                    result["status"] = "unhealthy"
                    result["error"] = f"vLLM连接错误: {str(e)}"
                    result["vllm_connected"] = False
                    
            elif self._model_type == 'infer_service':
                # 测试推理服务连接
                try:
                    from .llm.infer_service_client import get_infer_client
                    infer_client = get_infer_client()
                    health_result = asyncio.run(infer_client.health_check())
                    result["infer_service_connected"] = True
                    result["health_status"] = health_result.get("status", "unknown")
                except Exception as e:
                    result["status"] = "unhealthy"
                    result["error"] = f"推理服务连接错误: {str(e)}"
                    result["infer_service_connected"] = False
                    
            return result
            
        except Exception as e:
            logger.error(f"健康检查失败: {str(e)}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": time.time()
            }


# 便捷函数
def create_text_adapter(config: Optional[Dict[str, Any]] = None) -> TextModelAdapter:
    """
    创建文本模型适配器实例
    
    Args:
        config: 配置参数
        
    Returns:
        TextModelAdapter实例
    """
    return TextModelAdapter(config)
