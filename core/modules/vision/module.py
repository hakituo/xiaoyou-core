import os
import gc
import time
import asyncio
from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.utils.resource_lock import get_resource_lock
from core.utils.config_accessor import get_config
from core.utils.async_locks import LazyAsyncLock

# 配置日志
logger = get_logger("VISION_MODULE")


class VisionModule:
    """
    视觉模块，负责处理图像理解和分析任务。
    封装了视觉模型的加载和推理逻辑。
    """

    def __init__(self, config=None):
        """
        初始化视觉模块

        Args:
            config: 模块配置字典 (已弃用，优先使用 integrated_config)
        """
        self.settings = get_settings()
        self.config = config or {}

        # 优先从 integrated_config 获取路径
        self.vision_model_path = self.settings.model.vision_path
        if not self.vision_model_path:
            # 尝试从旧配置获取
            self.vision_model_path = self.config.get("vision_model_path")

        if not self.vision_model_path:
            try:
                from core.core_engine.config_manager import get_config_manager

                get_config_manager()
                self.vision_model_path = self.settings.model.vision_path
            except Exception:
                pass

        self.device = self.settings.model.device
        self.provider = self.settings.model.vision.provider

        try:
            if self.provider == "local":
                dev = str(self.device or "").strip().lower()
                if dev in ("cuda", "gpu", "auto"):
                    logger.warning(
                        "检测到配置请求使用 CUDA，本地直连 GPU 已禁用，将强制使用 CPU 推理"
                    )
                    self.device = "cpu"
        except Exception:
            self.device = "cpu"

        self.model = None
        self.tokenizer = None
        self.processor = None
        self.is_loaded = False
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）

        # Cloud Client
        self.cloud_client = None
        if self.provider != "local":
            try:
                vision_model = self.settings.model.vision.model
                
                # 根据 provider 选择合适的客户端
                if self.provider == "siliconflow":
                    from core.llm.siliconflow_client import SiliconFlowClient
                    self.cloud_client = SiliconFlowClient(
                        api_key=self.settings.model.vision.api_key,
                        vision_model=vision_model,
                    )
                    logger.info(
                        f"Vision Module initialized with SiliconFlow Client, vision model: {vision_model}"
                    )
                elif self.provider == "zhipu":
                    from core.llm.openai_compat import ZhiPuClient
                    self.cloud_client = ZhiPuClient(
                        api_key=self.settings.model.vision.api_key,
                        base_url=self.settings.model.vision.base_url,
                        model=vision_model,
                    )
                    logger.info(
                        f"Vision Module initialized with Zhipu Client, model: {vision_model}"
                    )
                else:
                    from core.llm.openai_compat import OpenAIClient
                    self.cloud_client = OpenAIClient(
                        api_key=self.settings.model.vision.api_key,
                        base_url=self.settings.model.vision.base_url,
                        model=vision_model,
                    )
                    logger.info(
                        f"Vision Module initialized with OpenAI-compatible Client: {self.provider}, model: {vision_model}"
                    )
            except Exception as e:
                logger.error(f"Failed to initialize Vision Cloud Client: {e}")

        # Register with Resource Manager
        try:
            from core.resource_manager import get_resource_manager, ResourcePriority

            rm = get_resource_manager()
            rm.register_model(
                model_id="vision_module",
                model_type="vision",
                priority=ResourcePriority.MEDIUM,
                load_func=self._load_model,
                unload_func=self.unload_model,
            )
            try:
                rm.register_resource_handler(
                    "gpu_memory", ResourcePriority.MEDIUM, self.handle_resource_pressure
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to register Vision Module with Resource Manager: {e}")

    async def _load_model(self):
        """
        加载视觉模型和分词器 (异步包装)
        """
        if self.provider != "local":
            return True

        # Prepare resources (Unload LLM if needed)
        try:
            from core.resource_manager import get_resource_manager

            rm = get_resource_manager()
            await rm.prepare_for_heavy_task("vision")
        except Exception as e:
            logger.warning(f"Resource preparation failed: {e}")

        if not self.vision_model_path:
            logger.error("视觉模型路径未配置")
            return False

        ok = await asyncio.to_thread(self._load_model_sync)
        try:
            from core.resource_manager import get_resource_manager

            get_resource_manager().mark_model_loaded("vision_module", bool(ok))
        except Exception:
            pass
        return ok

    def _load_model_sync(self):
        """
        加载视觉模型和分词器 (同步实现)
        """
        try:
            # 延迟导入重型库
            import torch
            from transformers import (
                AutoModelForVision2Seq,
                AutoTokenizer,
                AutoProcessor,
            )

            # 自动选择设备
            if self.device == "auto" or not self.device:
                self.device = "cpu"

            if str(self.device).lower() == "cuda":
                logger.warning(
                    "检测到配置请求使用 CUDA，本地直连 GPU 已禁用，将强制使用 CPU 推理"
                )
                self.device = "cpu"

            logger.info(
                f"正在加载视觉模型: {self.vision_model_path} (Device: {self.device})"
            )

            if not os.path.exists(self.vision_model_path):
                logger.error(f"模型路径不存在: {self.vision_model_path}")
                return False

            model_kwargs = {
                "low_cpu_mem_usage": True,
                "torch_dtype": torch.float16
                if self.device == "cuda"
                else torch.float32,
                "local_files_only": True,
            }

            try:
                self.processor = AutoProcessor.from_pretrained(
                    self.vision_model_path,
                    local_files_only=True,
                    trust_remote_code=True,
                )
            except Exception:
                logger.info("未找到Processor，将仅使用Tokenizer")
                self.processor = None

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.vision_model_path, local_files_only=True, trust_remote_code=True
            )
            self.model = AutoModelForVision2Seq.from_pretrained(
                self.vision_model_path, trust_remote_code=True, **model_kwargs
            )

            self.model = self.model.to(self.device)

            self.is_loaded = True
            logger.info("视觉模型加载成功")
            return True

        except ImportError as e:
            logger.error(f"缺少必要的依赖库: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"加载视觉模型失败: {str(e)}")
            return False

    async def unload_model(self):
        """卸载模型释放资源"""
        async with self._lock:
            if self.model:
                del self.model
                self.model = None
            if self.tokenizer:
                del self.tokenizer
                self.tokenizer = None

            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

            gc.collect()
            self.is_loaded = False
            try:
                from core.resource_manager import get_resource_manager

                get_resource_manager().mark_model_loaded("vision_module", False)
            except Exception:
                pass
            logger.info("视觉模型已卸载")

    async def move_to_cpu(self):
        if self.provider != "local":
            return
        async with self._lock:
            if not self.is_loaded or self.model is None:
                self.device = "cpu"
                return
            try:
                import torch

                await asyncio.to_thread(self.model.to, "cpu")
                self.device = "cpu"
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                self.device = "cpu"
            try:
                from core.resource_manager import get_resource_manager

                rm = get_resource_manager()
                rm.mark_model_loaded("vision_module", True)
                model = rm.models.get("vision_module")
                if model:
                    model.device = "CPU"
                    model.vram_usage_mb = 0
                    model.is_offloaded = True
            except Exception:
                pass

    async def move_to_gpu(self):
        """将视觉模型移至 GPU（当前本地直连 GPU 已禁用，强制 CPU 推理）"""
        if self.provider != "local":
            return
        async with self._lock:
            # 本地直连 GPU 已禁用，保持 CPU 模式
            self.device = "cpu"
            try:
                from core.resource_manager import get_resource_manager

                rm = get_resource_manager()
                rm.mark_model_loaded("vision_module", True)
                model = rm.models.get("vision_module")
                if model:
                    model.device = "CPU"
                    model.is_offloaded = False
            except Exception:
                pass

    async def handle_resource_pressure(self, action: str):
        act = str(action or "").strip().lower()
        if act == "release":
            await self.move_to_cpu()
        elif act in {"recover", "restore"}:
            try:
                from core.resource_manager import get_resource_manager, ResourceType

                rm = get_resource_manager()
                if rm and not rm.monitor.is_resource_pressure(ResourceType.GPU_MEMORY):
                    await self.move_to_gpu()
            except Exception:
                return

    async def describe_image(self, image, prompt=None):
        """
        使用视觉模型描述图像

        Args:
            image: PIL Image对象或图像路径
            prompt: 可选的提示文本

        Returns:
            包含状态和描述的字典
        """
        if self.provider != "local" and self.cloud_client:
            return await self._describe_image_cloud(image, prompt)

        async with get_resource_lock().acquire("Vision"):
            async with self._lock:
                try:
                    if not self.is_loaded:
                        success = await self._load_model()
                        if not success:
                            return {"status": "error", "error": "模型加载失败"}

                    if prompt is None:
                        prompt = "请详细描述这张图片的内容，包括场景、人物、动作、文字、图表以及任何关键的视觉细节。如果是界面截图，请重点描述文字内容和数据信息。"

                    # 延迟导入PIL
                    from PIL import Image

                    # 处理图像输入
                    if isinstance(image, str):
                        if not os.path.exists(image):
                            return {
                                "status": "error",
                                "error": f"图像文件不存在: {image}",
                            }
                        # 异步读取图片
                        image = await asyncio.to_thread(
                            lambda: Image.open(image).convert("RGB")
                        )
                    elif not isinstance(image, Image.Image):
                        return {"status": "error", "error": "无效的图像输入"}

                    # 异步执行推理
                    start_time = time.time()
                    result = await asyncio.to_thread(
                        self._inference_sync, image, prompt
                    )
                    duration = time.time() - start_time
                    logger.info(f"图像识别推理完成，耗时: {duration:.2f}秒")
                    return result

                except Exception as e:
                    logger.error(f"描述图像时出错: {str(e)}")
                    return {"status": "error", "error": str(e)}

    async def _describe_image_cloud(self, image, prompt):
        """
        使用云端服务描述图像
        """
        import base64
        from io import BytesIO
        from PIL import Image

        if isinstance(image, str):
            # Load from file
            if not os.path.exists(image):
                return {"status": "error", "error": f"图像文件不存在: {image}"}
            with open(image, "rb") as f:
                base64_image = base64.b64encode(f.read()).decode("utf-8")
        elif isinstance(image, Image.Image):
            buffered = BytesIO()
            # Convert to RGB if needed to save as JPEG
            if image.mode in ("RGBA", "P"):
                image = image.convert("RGB")
            image.save(buffered, format="JPEG")
            base64_image = base64.b64encode(buffered.getvalue()).decode("utf-8")
        else:
            return {"status": "error", "error": "Invalid image format"}

        if prompt is None:
            prompt = "请详细描述这张图片的内容，包括场景、人物、动作、文字、图表以及任何关键的视觉细节。如果是界面截图，请重点描述所有可见的文字内容、数字、进度条和图标数据。请尽可能详尽，不要遗漏任何细节。"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ]

        try:
            # 如果是 siliconflow 客户端，确保正确调用
            if self.provider == "siliconflow":
                # SiliconFlowClient 的 _vision_inference 或者直接 chat
                response = await self.cloud_client.chat(messages, max_tokens=1024)
                if isinstance(response, dict) and "response" in response:
                    return {"status": "success", "response": response["response"]}
                else:
                    return {"status": "success", "response": str(response)}
            else:
                response = await self.cloud_client.chat(messages, max_tokens=1024)
                if isinstance(response, dict):
                    resp_text = response.get("response", "")
                else:
                    resp_text = str(response)
                if resp_text.startswith("Error:") or resp_text.startswith("[DEBUG_ERROR]"):
                    return {"status": "error", "error": resp_text}
                return {"status": "success", "response": resp_text}
        except Exception as e:
            logger.error(f"Error in _describe_image_cloud: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def _inference_sync(self, image, prompt):
        """同步推理逻辑"""
        try:
            import torch

            inputs = None

            # 1. 优先尝试 Qwen-VL 的 from_list_format
            if hasattr(self.tokenizer, "from_list_format"):
                logger.info("Using Qwen-VL from_list_format")
                try:
                    inputs = self.tokenizer.from_list_format(
                        [
                            {"image": image},
                            {"text": prompt},
                        ],
                        return_tensors="pt",
                    ).to(self.model.device)
                except Exception as e:
                    logger.warning(f"Qwen-VL from_list_format failed: {e}")
                    inputs = None
            else:
                logger.info("Tokenizer does not have from_list_format")

            # 2. Qwen2-VL 特殊处理
            if inputs is None and "Qwen2-VL" in self.vision_model_path:
                logger.info("Attempting Qwen2-VL specific formatting")
                try:
                    # 尝试使用 apply_chat_template
                    messages = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "image": image},
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ]

                    text = None
                    if hasattr(self.processor, "apply_chat_template"):
                        try:
                            text = self.processor.apply_chat_template(
                                messages, tokenize=False, add_generation_prompt=True
                            )
                        except Exception as te:
                            logger.warning(f"apply_chat_template failed: {te}")

                    if not text:
                        from core.agents.chat_agent_components.persona_system.prompt.service_prompts import QWEN2_VL_TEMPLATE
                        logger.info("Using manual fallback for Qwen2-VL template")
                        text = QWEN2_VL_TEMPLATE.format(prompt=prompt)

                    logger.info(f"Qwen2-VL chat template: {text}")

                    # Qwen2-VL 性能优化：手动缩放图片，避免 Processor 不支持参数或分辨率过高导致推理变慢
                    try:
                        max_hw = 1024  # 增加到 1024，捕捉更多文字细节 (如游戏 UI 数据)
                        w, h = image.size
                        if max(w, h) > max_hw:
                            scale = max_hw / max(w, h)
                            new_size = (int(w * scale), int(h * scale))
                            image = image.resize(
                                new_size, resample=3
                            )  # 3 is Image.LANCZOS
                            logger.info(
                                f"Manually resized image from {w}x{h} to {new_size[0]}x{new_size[1]}"
                            )
                    except Exception as re:
                        logger.warning(f"Image resize failed: {re}")

                    inputs = self.processor(
                        text=[text], images=[image], padding=True, return_tensors="pt"
                    ).to(self.model.device)
                    logger.info(
                        f"Qwen2-VL inputs prepared: input_ids shape {inputs.input_ids.shape}"
                    )

                except Exception as e:
                    logger.warning(f"Qwen2-VL handling failed: {e}")
                    inputs = None

            # 3. 如果没有结果，尝试 Processor
            if inputs is None and self.processor:
                logger.info("Using Processor")
                try:
                    # Debug: Try adding <image> token if missing
                    # prompt_with_image = f"<img>{image}</img>\n{prompt}" # This requires path, but we have PIL image.
                    # Qwen-VL expects <img>path</img> if passing string, or specific tokens.

                    inputs = self.processor(
                        images=image, text=prompt, return_tensors="pt"
                    ).to(self.model.device)
                except TypeError:
                    # Fallback if processor signature mismatch
                    logger.warning("Processor TypeError")
                    pass
                except Exception as e:
                    logger.debug(f"Processor failed: {e}")

            # 3. 最后尝试通用 Tokenizer
            if inputs is None:
                logger.info("Using generic Tokenizer fallback")
                # 通用处理
                inputs = self.tokenizer(
                    images=image, text=prompt, return_tensors="pt"
                ).to(self.model.device)

            if inputs:
                if "input_ids" in inputs:
                    logger.info(f"Input IDs shape: {inputs['input_ids'].shape}")
                    # logger.info(f"Input IDs: {inputs['input_ids']}")
                if "pixel_values" in inputs:
                    logger.info(f"Pixel values shape: {inputs['pixel_values'].shape}")

            if (
                inputs is not None
                and "input_ids" in inputs
                and inputs["input_ids"].shape[1] == 0
            ):
                logger.error(
                    "Input IDs are empty after all processing attempts. Generation will fail."
                )
                return {
                    "status": "error",
                    "error": "模型输入解析失败 (Input IDs empty)",
                }

            with torch.no_grad():
                # 默认值提高到 1024，防止复杂描述截断
                max_new_tokens = 1024
                try:
                    # 尝试从 vision 配置获取
                    cfg_val = get_config(
                        "model.vision.max_new_tokens",
                        default=None,
                        settings=self.settings,
                    )
                    if cfg_val is None:
                        # 尝试从全局模型配置获取
                        cfg_val = getattr(self.settings.model, "max_new_tokens", None)

                    if cfg_val is not None:
                        max_new_tokens = int(cfg_val)
                except Exception:
                    pass

                gen_kwargs = {
                    "max_new_tokens": max(
                        64, min(max_new_tokens, 2048)
                    ),  # 允许最大 2048
                    "do_sample": True,
                    "temperature": 0.2,  # 使用低温度减少循环
                    "top_p": 0.9,
                    "repetition_penalty": 1.1,  # 增加重复惩罚
                }
                try:
                    eos_token_id = getattr(self.tokenizer, "eos_token_id", None)
                    if eos_token_id is not None:
                        gen_kwargs["eos_token_id"] = eos_token_id
                    pad_token_id = getattr(self.tokenizer, "pad_token_id", None)
                    if pad_token_id is not None:
                        gen_kwargs["pad_token_id"] = pad_token_id
                except Exception:
                    pass

                logger.info(
                    f"Starting generation with max_new_tokens={max_new_tokens}..."
                )
                import time

                start_time = time.time()
                output = self.model.generate(**inputs, **gen_kwargs)
                end_time = time.time()
                logger.info(
                    f"Generation finished in {end_time - start_time:.2f}s. Output shape: {output.shape}"
                )

            # Slice the output to remove input tokens
            generated_ids = output
            if "input_ids" in inputs:
                input_len = inputs["input_ids"].shape[1]
                output_len = output.shape[1]
                logger.info(f"Input tokens: {input_len}, Total tokens: {output_len}")
                if output_len > input_len:
                    generated_ids = output[:, input_len:]
                else:
                    # 如果输出长度不大于输入长度，可能是模型只返回了新生成的 token
                    # 或者生成失败。
                    logger.warning(
                        "Output length <= Input length. Assuming output is only new tokens."
                    )
                    generated_ids = output

            # 优先使用 processor 解码
            if self.processor and hasattr(self.processor, "batch_decode"):
                try:
                    response = self.processor.batch_decode(
                        generated_ids,
                        skip_special_tokens=True,
                        clean_up_tokenization_spaces=True,
                    )[0]
                except Exception as e:
                    logger.warning(
                        f"Processor batch_decode failed: {e}, falling back to tokenizer"
                    )
                    response = self.tokenizer.decode(
                        generated_ids[0], skip_special_tokens=True
                    )
            else:
                response = self.tokenizer.decode(
                    generated_ids[0], skip_special_tokens=True
                )

            logger.info(f"Decoded response (before cleaning): {response}")

            # Clean up response (remove special tokens and stop at end of turn)
            # 增加对 "Human:", "User:", "Assistant:" 等幻觉对话标记的截断，防止循环输出
            stop_markers = [
                "<|im_end|>",
                "<|im_start|>",
                "<|endoftext|>",
                "Human:",
                "User:",
                "Assistant:",
                "User ",
                "Assistant ",
                "###",
                "\n\n\n",
            ]
            for stop_token in stop_markers:
                if stop_token in response:
                    response = response.split(stop_token)[0]

            # 进一步清理重复段落（如果模型陷入了长段落循环）
            lines = response.split("\n")
            unique_lines = []
            for line in lines:
                line = line.strip()
                if line and line not in unique_lines:
                    unique_lines.append(line)
                elif not line:
                    unique_lines.append(line)

            # 如果重复率过高，尝试只保留唯一部分
            if len(lines) > 10 and len(unique_lines) < len(lines) * 0.5:
                logger.warning(
                    "Detected high repetition in vision response, pruning..."
                )
                response = "\n".join(unique_lines)

            response = response.strip()

            if self.processor and hasattr(self.processor, "decode"):
                # Note: Processor decode might re-introduce special tokens if not handled carefully,
                # but usually we trust tokenizer decode for the raw text extraction first.
                pass

            return {
                "status": "success",
                "response": response,
                "description": response,  # 兼容前端字段名
            }
        except Exception as e:
            logger.error(f"推理失败: {e}")
            raise
