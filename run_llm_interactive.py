#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
优化的LLM模型交互脚本
用于直接与已下载的Qwen2.5-7B-Instruct模型进行对话
支持GPU优化、人设系统和进度显示
"""

import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextStreamer
import logging
import time
import gc
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("LLM运行器")

# 模型路径配置 - 使用已下载的模型路径
MODEL_PATH = "d:\\AI\\xiaoyou-core\\models\\Qwen2.5-7B-Instruct\\Qwen\\Qwen2___5-7B-Instruct"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# 检查CUDA可用性和详细信息
if torch.cuda.is_available():
    logger.info(f"使用设备: CUDA ({torch.cuda.get_device_name(0)})")
    logger.info(f"CUDA内存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
else:
    logger.info(f"使用设备: CPU")
    logger.warning("未检测到可用的GPU，将使用CPU运行（速度会很慢）")

# 全局模型实例
model = None
tokenizer = None

# 人设配置
PERSONALITIES = {
    "default": "你是一个有用的AI助手，会用自然、友好的语言回答用户的问题。",
    "专业": "你是一位专业的AI顾问，擅长提供详细、准确的信息和建议。回答要简洁明了，重点突出。",
    "活泼": "你是一个活泼可爱的AI助手，喜欢用轻松愉快的方式与用户交流。可以适当使用表情符号和口语化表达。",
    "学术": "你是一位严谨的学术顾问，擅长深入分析问题并提供有深度的见解。回答要逻辑清晰，论据充分。",
    "创意": "你是一个富有创造力的AI助手，喜欢提出新颖的想法和解决方案。思维可以更加开放和独特。"
}
current_personality = "default"

def load_model():
    """加载Qwen2.5-7B-Instruct语言模型"""
    global model, tokenizer
    
    try:
        logger.info(f"开始加载语言模型: Qwen2.5-7B-Instruct 从路径: {MODEL_PATH}")
        
        # 加载分词器
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_PATH,
            trust_remote_code=True
        )
        logger.info("语言模型分词器加载完成")
        
        # 加载模型
        print("正在加载模型... (这可能需要几分钟)")
        
        # GPU优化配置
        model_kwargs = {
            "trust_remote_code": True,
            "use_safetensors": True
        }
        
        if DEVICE == "cuda":
            model_kwargs["device_map"] = "auto"
            model_kwargs["torch_dtype"] = torch.float16
            model_kwargs["low_cpu_mem_usage"] = True
            # 启用Flash Attention (如果支持)
            model_kwargs["attn_implementation"] = "flash_attention_2" if torch.cuda.is_available() else "sdpa"
        else:
            model_kwargs["device_map"] = "cpu"
            model_kwargs["torch_dtype"] = torch.float32
            # CPU优化
            model_kwargs["low_cpu_mem_usage"] = True
        
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            **model_kwargs
        )
        
        # 优化模型性能
        if DEVICE == "cuda":
            model = model.eval()
            # 启用推理优化
            try:
                model = torch.compile(model)  # 启用PyTorch编译优化
                logger.info("已启用PyTorch编译优化")
            except Exception as e:
                logger.warning(f"无法启用PyTorch编译: {str(e)}")
        
        logger.info("语言模型加载完成")
        return True
    except Exception as e:
        logger.error(f"语言模型加载失败: {str(e)}")
        return False

def generate_response(prompt, max_new_tokens=500, temperature=0.7, history=None):
    """生成LLM响应
    
    Args:
        prompt: 用户输入的提示词
        max_new_tokens: 最大生成token数
        temperature: 生成温度，控制输出的随机性
        history: 对话历史列表，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    
    Returns:
        str: 模型生成的响应
    """
    global model, tokenizer, current_personality
    
    if model is None or tokenizer is None:
        logger.warning("模型未加载，正在尝试加载...")
        if not load_model():
            return "❌ 模型加载失败，请检查模型路径和环境配置"
    
    try:
        # 构建对话历史
        if history is None:
            history = []
        
        # 添加当前用户输入
        history.append({"role": "user", "content": prompt})
        
        # 构建输入文本
        input_text = ""
        for msg in history:
            if msg["role"] == "user":
                input_text += f"<|im_start|>user\n{msg['content']}<|im_end|>\n"
            elif msg["role"] == "assistant":
                input_text += f"<|im_start|>assistant\n{msg['content']}<|im_end|>\n"
        
        # 添加当前人设和开始助手回复的标记
        system_prompt = f"<|im_start|>system\n{PERSONALITIES[current_personality]}<|im_end|>\n"
        full_prompt = system_prompt + input_text + "<|im_start|>assistant\n"
        
        # 模型生成
        start_time = time.time()
        
        # 编码输入
        inputs = tokenizer(full_prompt, return_tensors="pt")
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
        
        # 显示内存使用情况
        if DEVICE == "cuda":
            logger.info(f"GPU内存使用: {torch.cuda.memory_allocated() / 1024**3:.2f} GB / {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
        
        # 创建流式生成器
        streamer = TextStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
        
        # 生成响应
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                repetition_penalty=1.1,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.convert_tokens_to_ids("<|im_end|>"),
                streamer=streamer  # 启用流式输出
            )
        
        # 解码完整输出
        response = tokenizer.decode(output[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
        
        end_time = time.time()
        logger.info(f"生成响应耗时: {end_time - start_time:.2f} 秒")
        
        # 添加模型回复到历史记录
        history.append({"role": "assistant", "content": response})
        
        # 如果历史记录太长，保留最近的对话
        if len(history) > 20:  # 保留10轮对话
            history = history[-20:]
        
        return response
    except Exception as e:
        logger.error(f"生成响应失败: {str(e)}")
        return f"❌ 生成响应时出错: {str(e)}"

def set_personality(persona_name):
    """设置AI助手的人设"""
    global current_personality
    if persona_name in PERSONALITIES:
        current_personality = persona_name
        print(f"✅ 人设已切换为: {persona_name}")
        print(f"当前人设描述: {PERSONALITIES[persona_name]}")
        return True
    else:
        print(f"❌ 未知的人设: {persona_name}")
        print(f"可用的人设: {', '.join(PERSONALITIES.keys())}")
        return False

def show_help():
    """显示帮助信息"""
    print("\n📚 可用命令:")
    print("  exit/quit/退出 - 退出程序")
    print("  clear - 清空对话历史")
    print("  restart - 重启模型")
    print("  help - 显示此帮助信息")
    print("  personality [人设名] - 切换AI助手的人设")
    print("  list_personas - 列出所有可用的人设")
    print("  current_persona - 显示当前人设")
    print()

def list_personas():
    """列出所有可用的人设"""
    print("\n🤖 可用人设列表:")
    for name, desc in PERSONALITIES.items():
        status = " ✅" if name == current_personality else ""
        print(f"  • {name}{status}: {desc[:50]}...")
    print()

def main():
    """主函数，交互式对话"""
    print("\n========================================")
    print("      LLM模型交互式对话")
    print("========================================")
    print(f"模型: Qwen2.5-7B-Instruct")
    print(f"设备: {DEVICE}")
    print("提示: 输入 'help' 查看可用命令")
    print("      输入 'exit' 或 'quit' 退出程序")
    print("      输入 'personality 活泼' 切换人设")
    print("========================================")
    
    # 初始化时加载模型
    logger.info("正在加载模型...")
    if not load_model():
        print("❌ 模型加载失败，程序退出")
        return
    
    # 对话历史
    history = []
    
    try:
        while True:
            # 获取用户输入
            prompt = input("\n你: ")
            
            # 处理特殊命令
            if prompt.lower() in ['exit', 'quit', '退出']:
                print("\n感谢使用！再见！")
                break
            elif prompt.lower() == 'clear':
                history = []
                print("✅ 对话历史已清空")
                continue
            elif prompt.lower() == 'restart':
                print("🔄 正在重启模型...")
                # 释放内存
                global model, tokenizer
                model = None
                tokenizer = None
                gc.collect()
                torch.cuda.empty_cache() if torch.cuda.is_available() else None
                # 重新加载模型
                load_model()
                history = []
                print("✅ 模型已重启")
                continue
            elif prompt.lower() == 'help':
                show_help()
                continue
            elif prompt.lower() == 'list_personas':
                list_personas()
                continue
            elif prompt.lower() == 'current_persona':
                print(f"\n当前人设: {current_personality}")
                print(f"人设描述: {PERSONALITIES[current_personality]}")
                print()
                continue
            elif prompt.lower().startswith('personality '):
                parts = prompt.lower().split(' ', 1)
                if len(parts) > 1:
                    set_personality(parts[1])
                else:
                    print("❌ 请指定人设名称")
                    print(f"可用的人设: {', '.join(PERSONALITIES.keys())}")
                continue
            
            # 生成响应
            print("\n模型正在生成响应...")
            print("模型:", end=" ")
            sys.stdout.flush()
            response = generate_response(prompt, history=history)
            
            # 显示完成标记
            print("\n" + "-"*50)
            print(f"当前人设: {current_personality} | 输入 'personality 帮助' 查看人设切换命令")
            print("-"*50)
    
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
    finally:
        # 清理资源
        print("正在清理资源...")
        # 删除全局引用，允许垃圾回收
        model = None
        tokenizer = None
        gc.collect()
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
        print("✅ 资源已清理")

if __name__ == "__main__":
    main()