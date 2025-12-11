import os
import torch
try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    AutoModelForCausalLM = None
    AutoTokenizer = None

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

import gc
import asyncio
from config.integrated_config import get_settings
from core.utils.logger import get_logger

# 配置日志
logger = get_logger("LLM_MODULE")

class LLMModule:
    """
    LLM模块，负责处理文本生成任务。
    封装了大语言模型的加载和推理逻辑。
    """
    def __init__(self, config=None):
        """
        初始化LLM模块
        
        Args:
            config: 模块配置字典，可覆盖全局配置
        """
        self.settings = get_settings()
        self.config = config or {}
        
        # 优先使用传入的 config，其次是全局 settings
        self.text_model_path = self.config.get("text_model_path") or self.settings.model.text_path or "./models/qwen"
        
        # Device 处理：优先 config，其次 settings
        self.device = self.config.get("device") or self.settings.model.device
        
        if self.device == "auto" or not self.device:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            
        self.model = None
        self.tokenizer = None
        self.llama_model = None
        self.is_loaded = False
        self.is_gguf = False
        self._lock = asyncio.Lock()
        
    async def _load_model(self):
        """
        加载文本模型 (异步包装)
        """
        return await asyncio.to_thread(self._load_model_sync)

    def _load_model_sync(self):
        """
        加载文本模型 (同步实现)
        """
        try:
            logger.info(f"正在加载文本模型: {self.text_model_path}")
            
            if not os.path.exists(self.text_model_path):
                logger.error(f"模型路径不存在: {self.text_model_path}")
                return False
                
            # Check for GGUF model
            if self.text_model_path.lower().endswith(".gguf"):
                if Llama is None:
                    logger.error("检测到GGUF模型，但未安装 llama_cpp_python。请运行 pip install llama-cpp-python")
                    return False
                
                logger.info("检测到GGUF模型，使用llama_cpp加载...")
                self.is_gguf = True
                
                # Configure Llama
                n_gpu_layers = self.config.get('n_gpu_layers', -1) # Default to all layers on GPU if available
                # 优先使用配置的 n_ctx，如果没有则尝试从 settings 获取，最后默认为 4096
                n_ctx = self.config.get('n_ctx') or getattr(self.settings.model, 'n_ctx', None) or 4096
                # n_batch 应该是 n_ctx 的一部分，或者是独立配置。增加默认值以提高性能
                n_batch = self.config.get('n_batch', 4096)
                
                logger.info(f"Initializing Llama model with n_ctx={n_ctx}, n_batch={n_batch}, n_gpu_layers={n_gpu_layers}")

                self.llama_model = Llama(
                    model_path=self.text_model_path,
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,
                    n_batch=n_batch, 
                    verbose=True
                )
                
                self.is_loaded = True
                logger.info("GGUF模型加载成功")
                return True
            
            # Fallback to transformers for non-GGUF models
            if AutoModelForCausalLM is None:
                 logger.error("未安装 transformers 库")
                 return False

            model_kwargs = {
                "low_cpu_mem_usage": True,
                "torch_dtype": torch.float16 if self.device == "cuda" else torch.float32,
                "local_files_only": True
            }
            
            if self.device == "cuda":
                model_kwargs["device_map"] = "auto"
                
            self.tokenizer = AutoTokenizer.from_pretrained(self.text_model_path, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(self.text_model_path, **model_kwargs)
            
            if self.device != "cuda" or not model_kwargs.get("device_map"):
                self.model = self.model.to(self.device)
                
            self.is_loaded = True
            logger.info("文本模型加载成功")
            return True
            
        except Exception as e:
            logger.error(f"加载文本模型失败: {str(e)}")
            return False

    def get_current_model_name(self):
        """获取当前加载的模型名称或路径"""
        return self.text_model_path

    async def unload_model(self):
        """卸载模型释放资源"""
        async with self._lock:
            if self.model:
                del self.model
                self.model = None
            if self.tokenizer:
                del self.tokenizer
                self.tokenizer = None
            
            if self.llama_model:
                del self.llama_model
                self.llama_model = None
                
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            self.is_loaded = False
            logger.info("文本模型已卸载")

    async def chat(self, prompt, max_tokens=None, temperature=None):
        """
        生成文本回复
        
        Args:
            prompt: 提示词 (str) 或 消息列表 (list)
            max_tokens: 最大生成token数
            temperature: 温度参数
            
        Returns:
            包含状态和回复的字典
        """
        async with self._lock:
            try:
                if not self.is_loaded:
                    success = await self._load_model()
                    if not success:
                        return {"status": "error", "error": "模型加载失败"}
                
                # 从配置获取默认值
                max_tokens = max_tokens or self.settings.model.max_new_tokens or 512
                temperature = temperature or self.settings.model.temperature or 0.7
                min_p = self.settings.model.min_p
                repetition_penalty = self.settings.model.repetition_penalty or 1.1
                top_p = self.settings.model.top_p or 0.9
                
                return await asyncio.to_thread(self._chat_sync, prompt, max_tokens, temperature, min_p, repetition_penalty, top_p)
                
            except Exception as e:
                logger.error(f"生成文本时出错: {str(e)}")
                return {"status": "error", "error": str(e)}

    def _chat_sync(self, prompt, max_tokens, temperature, min_p, repetition_penalty, top_p):
        """同步推理逻辑"""
        
        if self.is_gguf:
            return self._chat_sync_gguf(prompt, max_tokens, temperature, repetition_penalty, top_p)
            
        # Transformers logic
        # 处理消息列表，应用 Chat Template
        if isinstance(prompt, list):
            try:
                # 使用 apply_chat_template 自动格式化为 Llama-3 格式
                # 假设 prompt 是 [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
                prompt_text = self.tokenizer.apply_chat_template(
                    prompt, 
                    tokenize=False, 
                    add_generation_prompt=True
                )
            except Exception as e:
                logger.warning(f"应用Chat Template失败，回退到原始文本: {e}")
                prompt_text = str(prompt)
        else:
            prompt_text = str(prompt)

        inputs = self.tokenizer(prompt_text, return_tensors="pt")
        if self.device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}
            
        with torch.no_grad():
            # 构建生成参数
            gen_kwargs = {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "do_sample": True,
                "repetition_penalty": repetition_penalty,
                "pad_token_id": self.tokenizer.eos_token_id
            }
            
            # 支持 Min-P (如果 transformers 版本支持或手动实现，这里假设直接传递给 generate)
            if min_p is not None:
                gen_kwargs["min_p"] = min_p
            
            if top_p is not None:
                gen_kwargs["top_p"] = top_p

            output = self.model.generate(
                **inputs,
                **gen_kwargs
            )
            
        response = self.tokenizer.decode(
            output[0][len(inputs["input_ids"][0]):],
            skip_special_tokens=True
        )
        
        return {
            "status": "success",
            "response": response
        }

    def _chat_sync_gguf(self, prompt, max_tokens, temperature, repetition_penalty, top_p):
        """GGUF (llama_cpp) 同步推理逻辑"""
        try:
            # Prepare messages
            messages = []
            if isinstance(prompt, str):
                messages = [{"role": "user", "content": prompt}]
            elif isinstance(prompt, list):
                messages = prompt
            
            # Use chat completion API
            try:
                response = self.llama_model.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    repeat_penalty=repetition_penalty,
                )
            except Exception as e:
                if "index" in str(e) and "out of bounds" in str(e):
                    logger.warning(f"GGUF推理遇到索引错误，尝试重置模型并重试: {e}")
                    self.llama_model.reset()
                    response = self.llama_model.create_chat_completion(
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        repeat_penalty=repetition_penalty,
                    )
                else:
                    raise e
            
            content = response['choices'][0]['message']['content']
            return {
                "status": "success",
                "response": content
            }
        except Exception as e:
            logger.error(f"GGUF推理失败: {e}")
            # 如果是 token 超限，提示用户
            if "exceed context window" in str(e):
                return {"status": "error", "error": f"请求长度超过上下文窗口限制 ({self.llama_model.n_ctx()})，请缩短输入或增加 n_ctx 配置。"}
            return {"status": "error", "error": str(e)}

