import os
# 设置 HF 镜像以解决国内连接问题
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# 禁用 HF Symlinks 警告 (Windows下可能无法创建软链接)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import torch
from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline, EulerAncestralDiscreteScheduler
import gc
import asyncio
from config.integrated_config import get_settings
from core.utils.logger import get_logger

# 配置日志
logger = get_logger("IMAGE_MODULE")

class ImageModule:
    """
    图像模块，负责处理图像生成任务。
    封装了Stable Diffusion模型的加载和推理逻辑。
    """
    
    # 预定义模型路径
    PRESET_MODELS = {
        "pony": r"D:\AI\xiaoyou-core\models\img\stable-diffusion-webui-forge-main\models\Stable-diffusion\ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
        "asian": r"D:\AI\xiaoyou-core\models\img\stable-diffusion-webui-forge-main\models\Stable-diffusion\sdxl10ArienmixxlAsian_v45Pruned.safetensors"
    }

    def __init__(self, config=None):
        """
        初始化图像模块
        
        Args:
            config: 模块配置字典 (已弃用，优先使用 integrated_config)
        """
        self.settings = get_settings()
        self.config = config or {}
        
        # 优先从 integrated_config 获取路径
        # 默认使用 Pony 模型
        self.image_gen_model_path = self.settings.model.image_gen_path or self.config.get("image_gen_model_path", self.PRESET_MODELS["pony"])
        self.device = self.settings.model.device
        
        if self.device == "auto" or not self.device:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            
        self.pipe = None
        self.is_loaded = False
        self._lock = asyncio.Lock()

        # 内存优化配置
        self.low_vram_mode = self.config.get("low_vram_mode", True)
        self.auto_precision = self.config.get("auto_precision", True)
        self.current_precision = "fp16"

    def switch_model(self, model_key):
        """切换模型 (pony, asian, default)"""
        if model_key in self.PRESET_MODELS:
            new_path = self.PRESET_MODELS[model_key]
            if new_path != self.image_gen_model_path:
                logger.info(f"切换模型到: {model_key} ({new_path})")
                self.image_gen_model_path = new_path
                # 如果已经加载，需要重新加载
                if self.is_loaded:
                    asyncio.create_task(self.unload_model()) # 异步卸载，下次使用时会自动加载
        else:
            logger.warning(f"未知模型: {model_key}")

    def _check_memory_pressure(self) -> bool:
        """检查是否存在显存压力"""
        if not torch.cuda.is_available():
            return False
        try:
            allocated = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
            total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
            usage_ratio = allocated / total
            return usage_ratio > 0.7
        except Exception as e:
            logger.warning(f"检查显存压力时出错: {str(e)}")
            return False

    def _get_optimal_precision_level(self) -> str:
        """根据可用显存获取最佳精度级别"""
        if not torch.cuda.is_available():
            return 'fp16'
        try:
            allocated = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
            total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
            available = total - allocated
            
            if available < 4.0:
                return 'fp4'
            elif available < 6.0:
                return 'fp8'
            else:
                return 'fp16'
        except Exception as e:
            logger.warning(f"获取最佳精度级别时出错: {str(e)}")
            return 'fp16'

    def _get_precision_dtype(self, precision_level: str):
        """根据精度级别获取对应的torch数据类型"""
        if precision_level == 'fp8' and hasattr(torch, 'float8_e4m3fn'):
            return torch.float8_e4m3fn
        elif precision_level == 'fp4' and hasattr(torch, 'float4'):
            return torch.float4
        return torch.float16

    def _get_next_lower_precision(self, current_precision: str):
        """获取更低的精度级别"""
        precision_hierarchy = {'fp16': 'fp8', 'fp8': 'fp4', 'fp4': None}
        return precision_hierarchy.get(current_precision)

    def _clean_memory(self):
        """清理显存"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, 'ipc_collect'):
                torch.cuda.ipc_collect()
        gc.collect()

    async def _load_model(self):
        """
        加载图像生成模型 (异步包装)
        """
        return await asyncio.to_thread(self._load_model_sync)

    def _load_model_sync(self, precision_level=None):
        """
        加载图像生成模型 (同步实现)
        """
        try:
            logger.info(f"正在加载图像生成模型: {self.image_gen_model_path}")
            
            is_single_file = os.path.isfile(self.image_gen_model_path)
            
            if not os.path.exists(self.image_gen_model_path) and not is_single_file:
                # 尝试作为pretrained model name加载
                logger.info(f"路径不存在，尝试作为模型名称加载: {self.image_gen_model_path}")
                
            # 确定精度
            if precision_level is None:
                precision_level = "fp16"
                if self.auto_precision and self._check_memory_pressure():
                    logger.warning("检测到显存压力，尝试降低精度加载模型")
                    precision_level = self._get_optimal_precision_level()
            
            self.current_precision = precision_level
            torch_dtype = self._get_precision_dtype(precision_level)
            
            pipe_kwargs = {
                "torch_dtype": torch_dtype
            }
            
            # 如果是本地文件且不是单文件，默认只查本地；如果是单文件，可能需要联网下载Config
            if not is_single_file and os.path.exists(self.image_gen_model_path):
                 pipe_kwargs["local_files_only"] = True
            else:
                 # 单文件或路径不存在（尝试下载），允许联网
                 pipe_kwargs["local_files_only"] = False

            if self.device == "cuda":
                # pipe_kwargs["device_map"] = "auto" # 可能会导致冲突，特别是与offload结合时
                pass
                
            logger.info(f"加载参数: precision={precision_level}, low_vram={self.low_vram_mode}, local_files_only={pipe_kwargs.get('local_files_only')}")

            try:
                if is_single_file:
                    # 判断是否为SDXL
                    filename = os.path.basename(self.image_gen_model_path).lower()
                    if "xl" in filename:
                        PipelineClass = StableDiffusionXLPipeline
                        logger.info("检测到SDXL模型，使用StableDiffusionXLPipeline")
                    else:
                        PipelineClass = StableDiffusionPipeline
                        logger.info("检测到SD1.5/2.x模型，使用StableDiffusionPipeline")
                        
                    self.pipe = PipelineClass.from_single_file(self.image_gen_model_path, **pipe_kwargs)
                else:
                    self.pipe = StableDiffusionPipeline.from_pretrained(self.image_gen_model_path, **pipe_kwargs)
                
                # 针对 Pony/SDXL 的特定优化
                if isinstance(self.pipe, StableDiffusionXLPipeline):
                    # 1. 解决 fp16 下的黑图/伪影/模糊问题
                    # 不要直接转换 .to(float32)，因为会与 cpu_offload 冲突导致 Input type mismatch
                    # 使用 force_upcast = True 让 VAE 在推理时自动提升精度
                    if hasattr(self.pipe, "vae") and hasattr(self.pipe.vae, "config"):
                        self.pipe.vae.config.force_upcast = True
                        logger.info("已启用 VAE force_upcast 以防止图像伪影")
                    
                    # 2. 切换 Scheduler 为 Euler a (Pony 推荐)
                    self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(self.pipe.scheduler.config)
                    logger.info("已将采样器切换为 EulerAncestralDiscreteScheduler (Euler a)")

            except Exception as e:
                logger.error(f"模型加载失败: {e}")
                # 如果是网络问题导致下载Config失败，尝试不带local_files_only=False再次尝试(虽然通常没用)
                # 这里主要处理其他异常
                raise e
            
            if self.device == "cuda":
                if self.low_vram_mode:
                    try:
                        if hasattr(self.pipe, 'enable_model_cpu_offload'):
                            self.pipe.enable_model_cpu_offload()
                            logger.info("已启用模型CPU卸载 (Low VRAM Mode)")
                        else:
                            self.pipe.enable_sequential_cpu_offload()
                            logger.info("已启用顺序CPU卸载")
                    except Exception as e:
                        logger.warning(f"启用CPU卸载失败: {e}, 回退到直接移动到CUDA")
                        self.pipe = self.pipe.to("cuda")
                else:
                    self.pipe = self.pipe.to("cuda")
                
            self.is_loaded = True
            logger.info(f"图像生成模型加载成功 (精度: {precision_level})")
            return True
            
        except torch.cuda.OutOfMemoryError:
            logger.error("加载模型时显存不足")
            self._clean_memory()
            
            if self.auto_precision:
                lower = self._get_next_lower_precision(self.current_precision)
                if lower:
                    logger.warning(f"尝试降级精度至 {lower} 重新加载")
                    return self._load_model_sync(precision_level=lower)
            return False
            
        except Exception as e:
            logger.error(f"加载图像生成模型失败: {str(e)}")
            return False

    async def unload_model(self):
        """卸载模型释放资源"""
        async with self._lock:
            if self.pipe:
                del self.pipe
                self.pipe = None
            
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            self.is_loaded = False
            logger.info("图像生成模型已卸载")

    async def generate_image(self, prompt, negative_prompt=None, height=512, width=512, num_inference_steps=20, guidance_scale=7.0, clip_skip=2):
        """
        生成图像
        
        Args:
            prompt: 提示词
            negative_prompt: 负向提示词
            height: 高度
            width: 宽度
            num_inference_steps: 推理步数
            guidance_scale: 提示词相关性 (CFG Scale)
            clip_skip: Clip Skip (Pony通常需要2)
            
        Returns:
            包含状态和图像的字典
        """
        async with self._lock:
            try:
                if not self.is_loaded:
                    success = await self._load_model()
                    if not success:
                        return {"status": "error", "error": "模型加载失败"}
                        
                return await asyncio.to_thread(
                    self._generate_image_sync,
                    prompt, negative_prompt, height, width, num_inference_steps, guidance_scale, clip_skip
                )
            
            except Exception as e:
                logger.error(f"生成图像时出错: {str(e)}")
                return {"status": "error", "error": str(e)}

    def _generate_image_sync(self, prompt, negative_prompt, height, width, num_inference_steps, guidance_scale, clip_skip):
        """同步图像生成逻辑"""
        with torch.no_grad():
            # 动态调整 clip_skip (如果有接口支持，目前diffusers主要通过加载时控制，这里暂时保留接口参数位置)
            # Pony 推荐 clip_skip=2，diffusers 的 from_single_file 默认会尝试读取配置
            
            extra_kwargs = {}
            if isinstance(self.pipe, StableDiffusionXLPipeline):
                # SDXL 通常支持 guidance_scale
                extra_kwargs["guidance_scale"] = guidance_scale
                # clip_skip 在 diffusers 运行时较难动态调整，通常依赖加载时的配置
                
                # 自动添加 Pony 专属前缀 (如果当前是 Pony 模型且 prompt 中没有包含核心前缀)
                # 这里简单判断路径名是否包含 pony，或者你可以更严谨地判断模型哈希
                if "pony" in str(self.image_gen_model_path).lower():
                    pony_prefix = "score_9, score_8_up, score_7_up, "
                    pony_negative = "score_4, score_5, score_6, source_furry, source_pony, source_cartoon, "
                    
                    if "score_9" not in prompt:
                        prompt = pony_prefix + prompt
                        logger.info("已自动添加 Pony 正向提示词前缀")
                        
                    if negative_prompt and "score_4" not in negative_prompt:
                        negative_prompt = pony_negative + negative_prompt
                        logger.info("已自动添加 Pony 负向提示词前缀")
                    elif not negative_prompt:
                        negative_prompt = pony_negative + "ugly, blurry, low quality"
                        logger.info("已自动添加 Pony 默认负向提示词")

            image = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                height=height,
                width=width,
                num_inference_steps=num_inference_steps,
                **extra_kwargs
            ).images[0]
        
        return {
            "status": "success",
            "image": image
        }

