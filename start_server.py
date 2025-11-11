#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
小优AI 核心系统启动脚本
集成模型自动加载、显存管理和API接口服务
"""

import os
import sys
import time
import threading
import traceback
import logging
import argparse
import json
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"server_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("xiaoyou_server")

# 全局配置
CONFIG = {
    "device": "cuda" if os.environ.get("USE_CUDA", "0") == "1" else "cpu",
    "model_dir": "./models",
    "api_port": 8000,
    "ws_port": 8765,
    "max_memory": "80%",  # 最大显存占用比例
    "model_cache_size": 2,  # 模型缓存数量
    "auto_reload": True,  # 自动重新加载模型
}

# 全局模型实例
MODELS = {}
MODEL_LOCKS = {}

# 加载环境变量覆盖默认配置
def load_env_config():
    """从环境变量加载配置"""
    env_config = {
        "device": os.environ.get("XIAOYOU_DEVICE"),
        "model_dir": os.environ.get("XIAOYOU_MODEL_DIR"),
        "api_port": os.environ.get("XIAOYOU_API_PORT"),
        "ws_port": os.environ.get("XIAOYOU_WS_PORT"),
        "max_memory": os.environ.get("XIAOYOU_MAX_MEMORY"),
    }
    for key, value in env_config.items():
        if value is not None:
            if key in ["api_port", "ws_port"]:
                try:
                    CONFIG[key] = int(value)
                except ValueError:
                    logger.warning(f"Invalid {key}: {value}, using default")
            else:
                CONFIG[key] = value

# 检查PyTorch和CUDA环境
def check_environment():
    """检查运行环境"""
    logger.info("检查运行环境...")
    
    # 检查Python版本
    if sys.version_info < (3, 8):
        logger.warning("Python版本过低，建议使用Python 3.8+")
    
    # 检查PyTorch
    try:
        import torch
        logger.info(f"PyTorch版本: {torch.__version__}")
        
        # 检查CUDA
        cuda_available = torch.cuda.is_available()
        logger.info(f"CUDA可用: {cuda_available}")
        
        if cuda_available:
            logger.info(f"CUDA设备数: {torch.cuda.device_count()}")
            logger.info(f"当前CUDA设备: {torch.cuda.current_device()}")
            logger.info(f"CUDA设备名称: {torch.cuda.get_device_name(0)}")
            total_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"CUDA总显存: {total_memory:.2f} GB")
        else:
            logger.warning("CUDA不可用，将使用CPU运行")
            CONFIG["device"] = "cpu"
        
        return True
    except ImportError:
        logger.error("未找到PyTorch，请先安装PyTorch")
        return False

# 检查模型文件完整性
def check_model_files(model_id):
    """检查模型文件是否完整"""
    model_path = os.path.join(CONFIG["model_dir"], model_id)
    required_files = {
        "qwen2_5": ["config.json", "model.safetensors"],
        "qwen2_vl": ["config.json", "model.safetensors"],
        "sdxl_turbo": ["model.safetensors"],
    }
    
    if model_id not in required_files:
        logger.warning(f"未知模型ID: {model_id}")
        return False
    
    if not os.path.exists(model_path):
        logger.error(f"模型路径不存在: {model_path}")
        return False
    
    missing_files = []
    for file in required_files[model_id]:
        file_path = os.path.join(model_path, file)
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            missing_files.append(file)
    
    if missing_files:
        logger.error(f"模型 {model_id} 缺失文件: {missing_files}")
        return False
    
    logger.info(f"模型 {model_id} 文件检查通过")
    return True

# 加载语言模型
def load_language_model(model_id="qwen2_5"):
    """加载语言模型"""
    if model_id in MODELS:
        logger.info(f"模型 {model_id} 已加载")
        return MODELS[model_id]
    
    if model_id not in MODEL_LOCKS:
        MODEL_LOCKS[model_id] = threading.Lock()
    
    with MODEL_LOCKS[model_id]:
        # 双重检查，避免锁期间被其他线程加载
        if model_id in MODELS:
            return MODELS[model_id]
        
        logger.info(f"开始加载语言模型: {model_id}")
        start_time = time.time()
        
        try:
            # 先检查文件
            if not check_model_files(model_id):
                return None
            
            # 清理缓存释放内存
            clear_model_cache(except_model=model_id)
            
            from transformers import AutoTokenizer, AutoModelForCausalLM
            
            model_path = os.path.join(CONFIG["model_dir"], model_id)
            logger.info(f"从路径加载模型: {model_path}")
            
            # 配置设备和精度
            device_map = "auto" if CONFIG["device"] == "cuda" else None
            torch_dtype = "auto" if CONFIG["device"] == "cuda" else "float32"
            
            # 加载tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                trust_remote_code=True
            )
            
            # 加载模型
            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                device_map=device_map,
                torch_dtype=torch_dtype,
                trust_remote_code=True,
                low_cpu_mem_usage=True
            )
            
            # 如果是CUDA，移动到指定设备
            if CONFIG["device"] == "cuda":
                model = model.to("cuda")
            
            # 保存模型实例
            MODELS[model_id] = {
                "model": model,
                "tokenizer": tokenizer,
                "loaded_at": time.time(),
                "type": "language"
            }
            
            load_time = time.time() - start_time
            logger.info(f"模型 {model_id} 加载完成，耗时: {load_time:.2f} 秒")
            
            # 打印显存使用情况
            if CONFIG["device"] == "cuda":
                import torch
                used_memory = torch.cuda.memory_allocated(0) / 1024**3
                logger.info(f"当前GPU显存使用: {used_memory:.2f} GB")
            
            return MODELS[model_id]
        except Exception as e:
            logger.error(f"加载模型 {model_id} 失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

# 加载视觉模型
def load_vision_model(model_id="qwen2_vl"):
    """加载视觉模型"""
    if model_id in MODELS:
        logger.info(f"模型 {model_id} 已加载")
        return MODELS[model_id]
    
    if model_id not in MODEL_LOCKS:
        MODEL_LOCKS[model_id] = threading.Lock()
    
    with MODEL_LOCKS[model_id]:
        if model_id in MODELS:
            return MODELS[model_id]
        
        logger.info(f"开始加载视觉模型: {model_id}")
        start_time = time.time()
        
        try:
            if not check_model_files(model_id):
                return None
            
            clear_model_cache(except_model=model_id)
            
            from transformers import AutoProcessor, AutoModelForVision2Seq
            
            model_path = os.path.join(CONFIG["model_dir"], model_id)
            
            processor = AutoProcessor.from_pretrained(
                model_path,
                trust_remote_code=True
            )
            
            device_map = "auto" if CONFIG["device"] == "cuda" else None
            torch_dtype = "auto" if CONFIG["device"] == "cuda" else "float32"
            
            model = AutoModelForVision2Seq.from_pretrained(
                model_path,
                device_map=device_map,
                torch_dtype=torch_dtype,
                trust_remote_code=True,
                low_cpu_mem_usage=True
            )
            
            if CONFIG["device"] == "cuda":
                model = model.to("cuda")
            
            MODELS[model_id] = {
                "model": model,
                "processor": processor,
                "loaded_at": time.time(),
                "type": "vision"
            }
            
            load_time = time.time() - start_time
            logger.info(f"模型 {model_id} 加载完成，耗时: {load_time:.2f} 秒")
            
            if CONFIG["device"] == "cuda":
                import torch
                used_memory = torch.cuda.memory_allocated(0) / 1024**3
                logger.info(f"当前GPU显存使用: {used_memory:.2f} GB")
            
            return MODELS[model_id]
        except Exception as e:
            logger.error(f"加载模型 {model_id} 失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

# 加载图像生成模型
def load_image_model(model_id="sdxl_turbo"):
    """加载图像生成模型"""
    if model_id in MODELS:
        logger.info(f"模型 {model_id} 已加载")
        return MODELS[model_id]
    
    if model_id not in MODEL_LOCKS:
        MODEL_LOCKS[model_id] = threading.Lock()
    
    with MODEL_LOCKS[model_id]:
        if model_id in MODELS:
            return MODELS[model_id]
        
        logger.info(f"开始加载图像生成模型: {model_id}")
        start_time = time.time()
        
        try:
            if not check_model_files(model_id):
                return None
            
            clear_model_cache(except_model=model_id)
            
            from diffusers import AutoPipelineForText2Image
            import torch
            
            model_path = os.path.join(CONFIG["model_dir"], model_id)
            
            torch_dtype = torch.float16 if CONFIG["device"] == "cuda" else torch.float32
            
            pipe = AutoPipelineForText2Image.from_pretrained(
                model_path,
                torch_dtype=torch_dtype,
                use_safetensors=True
            )
            
            if CONFIG["device"] == "cuda":
                pipe = pipe.to("cuda")
            
            MODELS[model_id] = {
                "pipe": pipe,
                "loaded_at": time.time(),
                "type": "image_gen"
            }
            
            load_time = time.time() - start_time
            logger.info(f"模型 {model_id} 加载完成，耗时: {load_time:.2f} 秒")
            
            if CONFIG["device"] == "cuda":
                used_memory = torch.cuda.memory_allocated(0) / 1024**3
                logger.info(f"当前GPU显存使用: {used_memory:.2f} GB")
            
            return MODELS[model_id]
        except Exception as e:
            logger.error(f"加载模型 {model_id} 失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

# 清理模型缓存
def clear_model_cache(except_model=None):
    """清理模型缓存，保留最近使用的模型"""
    if not MODELS:
        return
    
    # 获取需要清理的模型列表（按加载时间排序）
    models_to_clear = sorted(
        [(k, v) for k, v in MODELS.items() if k != except_model],
        key=lambda x: x[1]["loaded_at"]
    )
    
    # 如果超过缓存限制，清理最老的模型
    while len(MODELS) - len([m for m in MODELS if m == except_model]) >= CONFIG["model_cache_size"]:
        if models_to_clear:
            model_id, _ = models_to_clear.pop(0)
            logger.info(f"清理模型缓存: {model_id}")
            del MODELS[model_id]
            
            # 释放内存
            if CONFIG["device"] == "cuda":
                import torch
                torch.cuda.empty_cache()
    
    # 强制垃圾回收
    import gc
    gc.collect()

# 生成文本响应
def generate_text(prompt, model_id="qwen2_5", max_tokens=1024, temperature=0.7):
    """生成文本响应"""
    try:
        # 加载模型
        model_info = load_language_model(model_id)
        if not model_info:
            return {"error": "模型加载失败"}
        
        model = model_info["model"]
        tokenizer = model_info["tokenizer"]
        
        # 更新最后使用时间
        model_info["loaded_at"] = time.time()
        
        # 构建输入
        inputs = tokenizer(prompt, return_tensors="pt")
        if CONFIG["device"] == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}
        
        # 生成回复
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                num_return_sequences=1,
                do_sample=True,
                top_p=0.95,
                repetition_penalty=1.1
            )
        
        # 解码回复
        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # 清理输入张量
        del inputs
        if CONFIG["device"] == "cuda":
            torch.cuda.empty_cache()
        
        return {"response": response, "model": model_id}
    except Exception as e:
        logger.error(f"生成文本失败: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}

# 图像描述
def describe_image(image_path, model_id="qwen2_vl", max_tokens=128):
    """描述图像内容"""
    try:
        # 检查图像文件
        if not os.path.exists(image_path):
            return {"error": "图像文件不存在"}
        
        # 加载模型
        model_info = load_vision_model(model_id)
        if not model_info:
            return {"error": "模型加载失败"}
        
        model = model_info["model"]
        processor = model_info["processor"]
        
        # 更新最后使用时间
        model_info["loaded_at"] = time.time()
        
        # 加载图像
        from PIL import Image
        image = Image.open(image_path).convert("RGB")
        
        # 准备输入
        inputs = processor(
            text="描述这张图：",
            images=image,
            return_tensors="pt"
        )
        
        if CONFIG["device"] == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}
        
        # 生成描述
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                num_beams=1,
                do_sample=True,
                temperature=0.7
            )
        
        # 解码结果
        description = processor.decode(outputs[0], skip_special_tokens=True)
        
        # 清理
        del inputs
        del image
        if CONFIG["device"] == "cuda":
            torch.cuda.empty_cache()
        
        return {"description": description, "model": model_id}
    except Exception as e:
        logger.error(f"图像描述失败: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}

# 生成图像
def generate_image(prompt, output_path="output.png", model_id="sdxl_turbo", num_inference_steps=1):
    """生成图像"""
    try:
        # 加载模型
        model_info = load_image_model(model_id)
        if not model_info:
            return {"error": "模型加载失败"}
        
        pipe = model_info["pipe"]
        
        # 更新最后使用时间
        model_info["loaded_at"] = time.time()
        
        # 生成图像
        with torch.no_grad():
            image = pipe(
                prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=0.0
            ).images[0]
        
        # 保存图像
        image.save(output_path)
        
        # 清理
        if CONFIG["device"] == "cuda":
            torch.cuda.empty_cache()
        
        return {"image_path": output_path, "model": model_id}
    except Exception as e:
        logger.error(f"图像生成失败: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}

# 启动Web服务
def start_web_server():
    """启动Flask Web API服务"""
    try:
        from flask import Flask, request, jsonify
        from flask_cors import CORS
        
        app = Flask(__name__)
        CORS(app)  # 启用跨域
        
        @app.route('/api/chat', methods=['POST'])
        def chat_endpoint():
            data = request.json
            prompt = data.get('prompt', '')
            model_id = data.get('model', 'qwen2_5')
            max_tokens = data.get('max_tokens', 1024)
            temperature = data.get('temperature', 0.7)
            
            if not prompt:
                return jsonify({"error": "缺少prompt参数"}), 400
            
            result = generate_text(prompt, model_id, max_tokens, temperature)
            return jsonify(result)
        
        @app.route('/api/describe-image', methods=['POST'])
        def describe_image_endpoint():
            if 'image' not in request.files:
                return jsonify({"error": "缺少image文件"}), 400
            
            file = request.files['image']
            temp_path = f"temp_{int(time.time())}_{file.filename}"
            file.save(temp_path)
            
            try:
                result = describe_image(temp_path)
                return jsonify(result)
            finally:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        
        @app.route('/api/generate-image', methods=['POST'])
        def generate_image_endpoint():
            data = request.json
            prompt = data.get('prompt', '')
            
            if not prompt:
                return jsonify({"error": "缺少prompt参数"}), 400
            
            output_path = f"generated_{int(time.time())}.png"
            result = generate_image(prompt, output_path)
            return jsonify(result)
        
        @app.route('/api/status', methods=['GET'])
        def status_endpoint():
            # 检查模型状态
            models_status = {}
            for model_id, model_info in MODELS.items():
                models_status[model_id] = {
                    "type": model_info["type"],
                    "loaded": True,
                    "loaded_at": model_info["loaded_at"]
                }
            
            # 检查CUDA状态
            cuda_status = {"available": False}
            if CONFIG["device"] == "cuda":
                try:
                    import torch
                    cuda_status = {
                        "available": torch.cuda.is_available(),
                        "device_count": torch.cuda.device_count(),
                        "memory": {
                            "allocated": torch.cuda.memory_allocated(0) / 1024**3,
                            "total": torch.cuda.get_device_properties(0).total_memory / 1024**3
                        }
                    }
                except:
                    pass
            
            return jsonify({
                "status": "running",
                "models": models_status,
                "cuda": cuda_status,
                "config": CONFIG
            })
        
        logger.info(f"启动Web API服务，端口: {CONFIG['api_port']}")
        app.run(host='0.0.0.0', port=CONFIG['api_port'], threaded=True)
    except Exception as e:
        logger.error(f"启动Web服务失败: {str(e)}")
        logger.error(traceback.format_exc())

# 启动WebSocket服务
def start_websocket_server():
    """启动WebSocket服务"""
    try:
        import asyncio
        import websockets
        import json
        
        async def handle_websocket(websocket, path):
            logger.info(f"WebSocket连接建立: {path}")
            
            try:
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        action = data.get('action', '')
                        
                        if action == 'chat':
                            prompt = data.get('prompt', '')
                            result = generate_text(prompt)
                            await websocket.send(json.dumps(result))
                        
                        elif action == 'describe_image':
                            image_path = data.get('image_path', '')
                            result = describe_image(image_path)
                            await websocket.send(json.dumps(result))
                        
                        elif action == 'generate_image':
                            prompt = data.get('prompt', '')
                            result = generate_image(prompt)
                            await websocket.send(json.dumps(result))
                        
                        elif action == 'status':
                            status = {
                                "models": list(MODELS.keys()),
                                "config": CONFIG
                            }
                            await websocket.send(json.dumps(status))
                        
                        else:
                            await websocket.send(json.dumps({"error": "未知操作"}))
                    
                    except json.JSONDecodeError:
                        await websocket.send(json.dumps({"error": "无效的JSON格式"}))
                    except Exception as e:
                        logger.error(f"WebSocket处理错误: {str(e)}")
                        await websocket.send(json.dumps({"error": str(e)}))
            
            except websockets.ConnectionClosed:
                logger.info("WebSocket连接关闭")
            except Exception as e:
                logger.error(f"WebSocket错误: {str(e)}")
        
        async def main():
            server = await websockets.serve(handle_websocket, "0.0.0.0", CONFIG["ws_port"])
            logger.info(f"启动WebSocket服务，端口: {CONFIG['ws_port']}")
            await server.wait_closed()
        
        asyncio.get_event_loop().run_until_complete(main())
    except Exception as e:
        logger.error(f"启动WebSocket服务失败: {str(e)}")
        logger.error(traceback.format_exc())

# 监控显存使用
def monitor_memory():
    """监控显存使用情况"""
    if CONFIG["device"] != "cuda":
        return
    
    try:
        import torch
        
        while True:
            allocated = torch.cuda.memory_allocated(0) / 1024**3
            reserved = torch.cuda.memory_reserved(0) / 1024**3
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            
            usage_percent = (allocated / total) * 100
            
            if usage_percent > 90:
                logger.warning(f"显存使用率过高: {usage_percent:.1f}%，清理缓存...")
                clear_model_cache()
            
            logger.debug(f"显存使用: {allocated:.2f}/{total:.2f} GB ({usage_percent:.1f}%)")
            time.sleep(30)  # 每30秒检查一次
    except Exception as e:
        logger.error(f"显存监控失败: {str(e)}")

# 检查缺失的模型
def check_missing_models():
    """检查并提示缺失的模型，但不自动下载"""
    # 检查每个模型
    models_to_check = ["qwen2_5", "qwen2_vl", "sdxl_turbo"]
    missing_models = []
    
    for model_id in models_to_check:
        if not check_model_files(model_id):
            missing_models.append(model_id)
    
    if missing_models:
        logger.warning(f"检测到缺失的模型: {missing_models}")
        print(f"\n⚠️  警告: 检测到以下模型缺失: {missing_models}")
        print("请手动将模型文件放置在正确的目录中。")
        print("本地部署模式下不提供自动下载功能。")

# 主函数
def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='小优AI 核心系统')
    parser.add_argument('--device', choices=['cpu', 'cuda'], help='运行设备')
    parser.add_argument('--model-dir', help='模型目录')
    parser.add_argument('--api-port', type=int, help='API服务端口')
    parser.add_argument('--ws-port', type=int, help='WebSocket端口')
    parser.add_argument('--no-auto-download', action='store_true', help='禁用自动下载')
    parser.add_argument('--preload-models', nargs='+', help='预加载的模型')
    args = parser.parse_args()
    
    # 更新配置
    if args.device:
        CONFIG["device"] = args.device
    if args.model_dir:
        CONFIG["model_dir"] = args.model_dir
    if args.api_port:
        CONFIG["api_port"] = args.api_port
    if args.ws_port:
        CONFIG["ws_port"] = args.ws_port
    
    # 加载环境变量配置
    load_env_config()
    
    logger.info(f"小优AI 核心系统启动中...")
    logger.info(f"配置: {CONFIG}")
    
    # 检查环境
    if not check_environment():
        logger.error("环境检查失败，退出")
        return
    
    # 检查缺失的模型
    check_missing_models()
    
    # 预加载模型
    if args.preload_models:
        for model_id in args.preload_models:
            if model_id in ["qwen2_5", "qwen2_5b_instruct"]:
                load_language_model(model_id)
            elif model_id in ["qwen2_vl", "qwen2_vl_7b"]:
                load_vision_model(model_id)
            elif model_id in ["sdxl_turbo"]:
                load_image_model(model_id)
    
    # 启动监控线程
    if CONFIG["device"] == "cuda":
        monitor_thread = threading.Thread(target=monitor_memory, daemon=True)
        monitor_thread.start()
    
    # 启动服务线程
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    
    ws_thread = threading.Thread(target=start_websocket_server, daemon=True)
    ws_thread.start()
    
    logger.info("服务启动完成！")
    print("\n小优AI 核心系统已成功启动！")
    print(f"API服务: http://localhost:{CONFIG['api_port']}")
    print(f"WebSocket服务: ws://localhost:{CONFIG['ws_port']}")
    print(f"状态检查: http://localhost:{CONFIG['api_port']}/api/status")
    print("\n按 Ctrl+C 停止服务")
    
    try:
        # 主循环
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭服务...")
        print("\n正在关闭服务...")
    finally:
        # 清理资源
        MODELS.clear()
        if CONFIG["device"] == "cuda":
            import torch
            torch.cuda.empty_cache()
        logger.info("服务已关闭")


if __name__ == "__main__":
    main()