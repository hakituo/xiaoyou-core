import os
import torch
import transformers
from transformers import AutoTokenizer, AutoModelForCausalLM
from typing import List, Dict, Optional, Any
import gc
import time
import logging
import traceback
from config.config import Config

# 配置
config = Config()

# 配置日志记录器
logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

# 全局模型和分词器实例
model = None
tokenizer = None


def load_model(model_path=None):
    """
    加载LLM模型和分词器（仅使用本地模型）
    
    Args:
        model_path: 模型路径，如果未提供则使用默认路径
    
    Returns:
        tuple: (model, tokenizer)
    """
    global model, tokenizer
    start_time = time.time()
    
    # 如果模型已加载，则直接返回
    if model is not None and tokenizer is not None:
        logger.info("Model already loaded, returning cached instance")
        return model, tokenizer
    
    # 默认模型路径
    if model_path is None:
        # 尝试不同的可能路径
        possible_paths = [
            "models/Qwen2.5-7B-Instruct",
            "models/mistralai/Mistral-7B-Instruct-v0.2",
            "./Qwen2.5-7B-Instruct",
            "./Mistral-7B",
            "./models/qwen/Qwen2___5-7B-Instruct",
            "models/qwen/Qwen2___5-7B-Instruct",
            "./models/qwen",
            "models/qwen"
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                model_path = path
                logger.info(f"Found model path: {path}")
                break
        
        # 如果所有路径都不存在，使用本地默认路径
        if model_path is None:
            model_path = "./models/qwen"
            logger.info(f"No existing model path found, using default: {model_path}")
    
    logger.info(f"Loading model from: {model_path}")
    
    # 检查模型路径是否存在
    if not os.path.exists(model_path):
        error_msg = f"模型路径不存在: {model_path}，请确保本地已下载模型文件"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    
    try:
        # 配置device_map和量化选项
        load_params = {
            "trust_remote_code": True,
            "local_files_only": True,  # 禁用从Hugging Face下载
            "device_map": "auto",    # 自动设备映射
        }
        
        # 根据设备内存情况设置量化选项
        if torch.cuda.is_available():
            # 检查可用GPU内存
            available_memory = torch.cuda.get_device_properties(0).total_memory
            logger.info(f"GPU available with {available_memory / (1024*1024*1024):.2f}GB total memory")
            
            # 如果可用内存小于10GB，使用量化
            if available_memory < 10 * 1024 * 1024 * 1024:
                logger.info("Using quantization due to limited GPU memory")
                # 优先使用4位量化（更省内存）
                try:
                    load_params["load_in_4bit"] = True
                    logger.info("Attempting to load model with 4-bit quantization")
                except Exception:
                    load_params["load_in_8bit"] = True
                    load_params.pop("load_in_4bit", None)
                    logger.info("Falling back to 8-bit quantization")
        else:
            logger.warning("CUDA not available, will run on CPU")
        
        # 加载分词器，只使用本地文件
        logger.info("Loading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            trust_remote_code=True,
            use_fast=False,
            local_files_only=True
        )
        logger.info("Tokenizer loaded successfully")
        
        # 加载模型
        logger.info(f"Loading model with parameters: {load_params}")
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            **load_params
        )
        
        # 将模型移至适当设备
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)
        logger.info(f"Model moved to device: {device}")
        
        # 设置模型为评估模式
        model.eval()
        logger.info("Model set to evaluation mode")
        
        # 清理未使用的内存
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        end_time = time.time()
        logger.info(f"Model loaded successfully in {end_time - start_time:.2f} seconds")
        return model, tokenizer
    except Exception as e:
        logger.error(f"Failed to load model: {str(e)}")
        logger.debug(traceback.format_exc())
        
        # 清理内存
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # 尝试更保守的加载方式
        try:
            logger.info("Attempting to load model with conservative settings")
            tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
            
            # 只使用CPU加载
            load_params = {
                "device_map": "cpu",
                "low_cpu_mem_usage": True,
                "trust_remote_code": True,
                "local_files_only": True
            }
            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                **load_params
            )
            model.eval()
            logger.warning("Model loaded on CPU. Performance may be degraded.")
            return model, tokenizer
        except Exception as fallback_e:
            logger.error(f"Fallback loading also failed: {str(fallback_e)}")
            logger.debug(traceback.format_exc())
            raise RuntimeError(f"Failed to load model even with fallback: {str(fallback_e)}") from e


def generate_response(history, max_new_tokens=200, temperature=0.7, top_p=0.95):
    """
    根据对话历史生成响应
    
    Args:
        history: 对话历史列表，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        max_new_tokens: 最大生成长度
        temperature: 生成温度
        top_p: 核采样参数
    
    Returns:
        str: 生成的响应文本
    """
    global model, tokenizer
    
    # 确保模型已加载
    if model is None or tokenizer is None:
        load_model()
    
    # 构建输入文本
    input_text = ""
    for msg in history:
        if msg["role"] == "user":
            # 移除前缀 "User says: " 以获得更自然的提示格式
            content = msg["content"].replace("User says: ", "", 1)
            input_text += f"<|im_start|>user\n{content}<|im_end|>\n"
        elif msg["role"] == "assistant":
            input_text += f"<|im_start|>assistant\n{msg['content']}<|im_end|>\n"
        elif msg["role"] == "system":
            # 添加系统消息
            input_text += f"<|im_start|>system\n{msg['content']}<|im_end|>\n"
    
    # 添加当前生成的开始标记
    input_text += "<|im_start|>assistant\n"
    
    # 编码输入
    inputs = tokenizer(input_text, return_tensors="pt").to(model.device)
    
    # 生成响应
    try:
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id
        )
        
        # 解码输出
        response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        
        # 清理响应（移除可能的特殊标记）
        response = response.strip()
        
        return response
    except Exception as e:
        print(f"Error during generation: {e}")
        return "抱歉，我在生成回复时遇到了问题。请稍后再试。"


# 示例使用
def example_inference():
    """
    示例推理函数，用于测试模型加载和生成
    """
    # 加载模型
    model, tokenizer = load_model()
    
    # 测试输入
    history = [
        {"role": "user", "content": "你好，请介绍一下你自己。"}
    ]
    
    # 生成响应
    response = generate_response(history)
    print(f"Response: {response}")


if __name__ == "__main__":
    example_inference()