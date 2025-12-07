#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StableDiffusion模型适配器
专注于图像生成任务的适配器
"""

import os
import logging
import time
import torch
from typing import Dict, Optional, Any, Union, List
from PIL import Image
from core.core_engine.model_manager import get_model_manager
from core.utils.base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class SDAdapter(BaseAdapter):
    """
    StableDiffusion模型适配器
    处理图像生成任务
    """
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # 默认配置 - 优化为轻量级模式
        self.default_config = {
            'model_type': 'stable_diffusion',  # stable_diffusion, sdxl, other_image_gen
            'sd_model_path': '',
            'device': 'auto',
            'quantization': {
                'enabled': True,  # 默认启用量化
                'torch_dtype': torch.float16 if torch.cuda.is_available() else torch.float32,
                'device_map': 'auto',
                'precision_level': 'fp16'  # fp16, fp8, fp4 - 用于动态精度调整
            },
            'generation': {
                'width': 512,
                'height': 512,
                'num_inference_steps': 20,  # 减少推理步数以提高速度
                'guidance_scale': 7.0,  # 稍微降低引导比例
                'negative_prompt': 'ugly, blurry, low quality, bad anatomy',
                'low_vram_mode': True,  # 默认启用低显存模式
                'disable_postprocessing': True  # 禁用非必要后处理
            },
            'lora': {
                'enabled': False,  # 默认禁用LoRA
                'path': '',  # LoRA文件路径
                'weight': 0.7,  # LoRA权重强度
                'base_model_path': ''  # 可选的基础模型路径
            },
            'safety_checker': False,  # 默认禁用安全检查器以节省资源
            'timeout': 60,  # 缩短超时时间
            'max_retries': 2,
            'memory_monitoring': {
                'enabled': True,
                'warning_threshold_gb': 6.0,  # 8GB显存环境下的警告阈值
                'critical_threshold_gb': 7.0,  # 8GB显存环境下的临界阈值
                'auto_precision_downscale': True  # 启用自动精度降级
            }
        }
        
        # 合并配置
        self.config = self._merge_config_with_defaults(self.default_config, config)
        
        # 设置模型名称
        self._model_type = self.config['model_type']
        self._model_name = f"sd_{self._model_type}_{hash(self.config['sd_model_path'])}%10000" if self.config['sd_model_path'] else f"sd_{self._model_type}"
        
        # 获取模型管理器
        model_manager = get_model_manager()
        
        # 调用父类初始化，传递所有必需参数
        super().__init__(model_manager, 'image', self._model_name)
        
        # 注册模型到管理器
        self._register_model()
        
        # 初始化加载状态
        self._model_loaded = False
    
    def _merge_config_with_defaults(self, default_config: Dict[str, Any], user_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """合并默认配置和用户配置，支持嵌套字典"""
        result = default_config.copy()
        
        if user_config is None:
            return result
            
        for key, value in user_config.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # 递归合并嵌套字典
                result[key] = self._merge_config_with_defaults(result[key], value)
            else:
                result[key] = value
                
        return result

    def _register_model(self):
        """注册模型到模型管理器"""
        try:
            if self.config['sd_model_path']:
                self.model_manager.register_model(
                    model_name=self._model_name,
                    model_type='image_gen',
                    model_path=self.config['sd_model_path']
                )
            logger.info(f"SD模型已注册: {self._model_name}")
        except Exception as e:
            logger.error(f"注册SD模型失败: {str(e)}")

    def _get_precision_dtype(self, precision_level: str) -> torch.dtype:
        """
        根据精度级别获取对应的torch数据类型
        
        Args:
            precision_level: 精度级别 ('fp16', 'fp8', 'fp4')
            
        Returns:
            torch.dtype: 对应的torch数据类型
        """
        if precision_level == 'fp8' and hasattr(torch, 'float8_e4m3fn'):
            return torch.float8_e4m3fn
        elif precision_level == 'fp4' and hasattr(torch, 'float4'):
            return torch.float4
        return torch.float16
    
    def load_model(self, lora_path: str = None, lora_weight: float = None) -> bool:
        """
        加载StableDiffusion模型 - 优化版，支持低显存模式
        
        Args:
            lora_path: LoRA权重路径，如果提供将覆盖配置中的设置
            lora_weight: LoRA权重强度，如果提供将覆盖配置中的设置
            
        Returns:
            bool: 是否加载成功
        """
        try:
            if self._model_type in ['stable_diffusion', 'sdxl', 'other_image_gen']:
                # 检查并调整精度以适应可用显存
                precision_level = self.config['quantization'].get('precision_level', 'fp16')
                if self._check_memory_pressure() and self.config['memory_monitoring']['auto_precision_downscale']:
                    logger.warning("检测到显存压力，尝试降低精度加载模型")
                    precision_level = self._get_optimal_precision_level()
                    self.config['quantization']['precision_level'] = precision_level
                
                # 获取对应的dtype
                torch_dtype = self._get_precision_dtype(precision_level)
                
                # 准备加载参数 - 轻量级配置
                # 移除device_map，改用diffusers原生的offload机制
                load_kwargs = {
                    'device': self.config['device'],
                    'torch_dtype': torch_dtype,
                    'quantized': self.config['quantization']['enabled'],
                    'model_kwargs': {
                        # 'device_map': self.config['quantization']['device_map'],
                        'safety_checker': self.config['safety_checker'],
                        'variant': 'fp16' if torch_dtype == torch.float16 else None,
                        'low_cpu_mem_usage': True,
                        'offload_folder': os.path.join(os.path.dirname(__file__), '..', 'cache', 'model_offload')
                    }
                }
                
                # 如果用户明确指定了非auto的device_map (如cuda:0)，则保留
                if self.config['quantization']['device_map'] != 'auto':
                    load_kwargs['model_kwargs']['device_map'] = self.config['quantization']['device_map']
                
                # 低显存模式下的特殊处理
                if self.config['generation'].get('low_vram_mode', False):
                    # load_kwargs['model_kwargs']['device_map'] = 'sequential' # 导致挂起，禁用
                    # load_kwargs['model_kwargs']['offload_state_dict'] = True
                    logger.info("启用低显存模式加载 (使用model_cpu_offload)")
                
                # 清理显存后再加载
                self._clean_memory()
                
                # 加载模型
                model = self.model_manager.load_model(self._model_name, **load_kwargs)
                if model:
                    self._model_loaded = True
                    self._is_loaded = True
                    logger.info(f"SD模型加载成功: {self._model_name} (精度: {precision_level})")
                    
                    # 加载LoRA权重（如果配置了）
                    final_lora_path = lora_path if lora_path is not None else (self.config['lora'].get('path') if self.config['lora'].get('enabled', False) else None)
                    final_lora_weight = lora_weight if lora_weight is not None else self.config['lora'].get('weight', 0.7)
                    
                    if final_lora_path:
                        logger.info(f"加载LoRA权重: {final_lora_path}, 权重强度: {final_lora_weight}")
                        self._load_lora(final_lora_path, final_lora_weight)
                    
                    return True
                else:
                    logger.error(f"SD模型加载失败: {self._model_name}")
                    
                    # 尝试降级精度重试
                    if self.config['memory_monitoring']['auto_precision_downscale']:
                        lower_precision = self._get_next_lower_precision(precision_level)
                        if lower_precision:
                            logger.warning(f"尝试降级精度至 {lower_precision} 重新加载")
                            self.config['quantization']['precision_level'] = lower_precision
                            return self.load_model(lora_path, lora_weight)
                    
                    return False
            else:
                # 对于其他类型的图像生成模型，这里可以扩展
                self._model_loaded = True
                self._is_loaded = True
                logger.info(f"图像生成模型已就绪: {self._model_type}")
                return True
        except torch.cuda.OutOfMemoryError:
            logger.error("加载SD模型时显存不足")
            self._clean_memory()
            
            # 尝试降级精度
            if self.config['memory_monitoring']['auto_precision_downscale']:
                precision_level = self.config['quantization'].get('precision_level', 'fp16')
                lower_precision = self._get_next_lower_precision(precision_level)
                if lower_precision:
                    logger.warning(f"显存不足，尝试降级精度至 {lower_precision} 重新加载")
                    self.config['quantization']['precision_level'] = lower_precision
                    return self.load_model(lora_path, lora_weight)
            
            return False
        except Exception as e:
            logger.error(f"加载SD模型时出错: {str(e)}")
            return False
            
    def _load_lora(self, lora_path: str, weight: float = 0.7):
        """
        加载LoRA权重并应用到管道
        
        Args:
            lora_path: LoRA权重文件路径
            weight: LoRA应用权重
        """
        try:
            import os
            
            # 确保路径存在
            if not os.path.exists(lora_path):
                logger.error(f"LoRA文件不存在: {lora_path}")
                return False
            
            logger.info(f"正在加载LoRA权重: {lora_path}")
            
            # 获取模型实例
            model = self.model_manager.load_model(self._model_name)
            if not model:
                logger.error("模型未加载，无法应用LoRA权重")
                return False
            
            # 加载LoRA权重
            model.load_lora_weights(
                lora_path,
                weight_name=os.path.basename(lora_path) if os.path.isfile(lora_path) else None
            )
            
            # 设置LoRA权重强度
            model.fuse_lora(lora_scale=weight)
            
            logger.info(f"LoRA权重加载成功，强度设置为: {weight}")
            return True
            
        except ImportError:
            logger.error("缺少必要的依赖库，请确保已安装diffusers库的最新版本")
            return False
        except Exception as e:
            logger.error(f"LoRA权重加载失败: {str(e)}")
            return False

    def _check_memory_pressure(self) -> bool:
        """
        检查是否存在显存压力
        
        Returns:
            bool: 是否存在显存压力
        """
        if not torch.cuda.is_available():
            return False
        
        try:
            allocated = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
            total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
            usage_ratio = allocated / total
            
            # 如果已使用超过70%的显存，认为有压力
            return usage_ratio > 0.7
        except Exception as e:
            logger.warning(f"检查显存压力时出错: {str(e)}")
            return False
    
    def _get_optimal_precision_level(self) -> str:
        """
        根据可用显存获取最佳精度级别
        
        Returns:
            str: 推荐的精度级别
        """
        if not torch.cuda.is_available():
            return 'fp16'
        
        try:
            allocated = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
            total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
            available = total - allocated
            
            # 根据可用显存推荐精度
            if available < 4.0:
                return 'fp4'  # 极低显存环境
            elif available < 6.0:
                return 'fp8'  # 低显存环境
            else:
                return 'fp16'  # 正常环境
        except Exception as e:
            logger.warning(f"获取最佳精度级别时出错: {str(e)}")
            return 'fp16'
    
    def _get_next_lower_precision(self, current_precision: str) -> Optional[str]:
        """
        获取比当前精度更低的精度级别
        
        Args:
            current_precision: 当前精度级别
            
        Returns:
            Optional[str]: 更低的精度级别，如果已是最低则返回None
        """
        precision_hierarchy = {'fp16': 'fp8', 'fp8': 'fp4', 'fp4': None}
        return precision_hierarchy.get(current_precision)
    
    def _apply_memory_optimizations(self):
        """
        应用内存优化措施
        """
        # 清理缓存
        self._clean_memory()
        
        # 如果启用了内存监控，检查显存使用情况
        if self.config['memory_monitoring']['enabled'] and torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
            total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
            
            critical_threshold = self.config['memory_monitoring']['critical_threshold_gb']
            warning_threshold = self.config['memory_monitoring']['warning_threshold_gb']
            
            if allocated > critical_threshold:
                logger.warning(f"显存使用达到临界阈值 ({allocated:.2f}GB > {critical_threshold}GB)")
                # 尝试更激进的内存释放
                if hasattr(torch.cuda, 'empty_cache'):
                    torch.cuda.empty_cache()
                if hasattr(torch.cuda, 'ipc_collect'):
                    torch.cuda.ipc_collect()
            elif allocated > warning_threshold:
                logger.info(f"显存使用达到警告阈值 ({allocated:.2f}GB > {warning_threshold}GB)")
    
    def generate_image(self, 
                      prompt: str,
                      negative_prompt: Optional[str] = None,
                      width: Optional[int] = None,
                      height: Optional[int] = None,
                      num_inference_steps: Optional[int] = None,
                      guidance_scale: Optional[float] = None,
                      num_images: int = 1,
                      seed: Optional[int] = None,
                      lora_path: Optional[str] = None,
                      lora_weight: Optional[float] = None) -> Dict[str, Any]:
        """
        使用StableDiffusion生成图像 - 优化版，支持显存管理、精度降级和LoRA
        
        Args:
            prompt: 提示词
            negative_prompt: 负面提示词
            width: 生成图像宽度
            height: 生成图像高度
            num_inference_steps: 推理步数
            guidance_scale: 引导尺度
            num_images: 生成图像数量
            seed: 随机种子
            lora_path: LoRA权重路径，如果提供将覆盖配置中的设置
            lora_weight: LoRA权重强度，如果提供将覆盖配置中的设置
            
        Returns:
            包含生成结果的字典
        """
        try:
            # 验证参数
            if not prompt or not isinstance(prompt, str):
                return {"status": "error", "error": "无效的提示词"}
            
            if num_images < 1 or num_images > 4:
                return {"status": "error", "error": "图像数量必须在1-4之间"}
            
            # 设置默认值
            if negative_prompt is None:
                negative_prompt = self.config['generation']['negative_prompt']
            
            # 限制分辨率，确保初始分辨率符合要求
            if width is None:
                width = self.config['generation']['width']
            else:
                # 限制最大宽度不超过640
                width = min(width, 640)
            
            if height is None:
                height = self.config['generation']['height']
            else:
                # 限制最大高度不超过640
                height = min(height, 640)
            
            # 减少推理步数以提高速度
            if num_inference_steps is None:
                num_inference_steps = self.config['generation']['num_inference_steps']
            else:
                # 限制最小步数，确保基本质量
                num_inference_steps = max(15, min(num_inference_steps, 30))
            
            if guidance_scale is None:
                guidance_scale = self.config['generation']['guidance_scale']
            
            # 应用内存优化
            self._apply_memory_optimizations()
            
            # 处理LoRA配置
            use_lora = False
            final_lora_path = None
            final_lora_weight = 0.7
            
            # 首先检查参数中是否提供了LoRA配置
            if lora_path:
                use_lora = True
                final_lora_path = lora_path
                final_lora_weight = lora_weight if lora_weight is not None else 0.7
            # 然后检查配置文件中是否启用了LoRA
            elif self.config['lora'].get('enabled', False) and self.config['lora'].get('path'):
                use_lora = True
                final_lora_path = self.config['lora'].get('path')
                final_lora_weight = self.config['lora'].get('weight', 0.7)
            
            # 确保模型已加载，并应用LoRA（如果配置了）
            if not self._ensure_model_loaded() or \
               (use_lora and (not hasattr(self, '_current_lora_path') or 
                             self._current_lora_path != final_lora_path or 
                             not hasattr(self, '_current_lora_weight') or 
                             self._current_lora_weight != final_lora_weight)):
                
                # 如果已经加载了模型，先卸载
                if self._model_loaded:
                    self._model_loaded = False
                    self.model_manager.unload_model(self._model_name)
                
                # 加载模型（带LoRA配置）
                if not self.load_model(lora_path=final_lora_path if use_lora else None, 
                                     lora_weight=final_lora_weight if use_lora else None):
                    return {"status": "error", "error": "模型加载失败"}
                
                # 记录当前使用的LoRA配置
                if use_lora:
                    self._current_lora_path = final_lora_path
                    self._current_lora_weight = final_lora_weight
                    logger.info(f"已应用LoRA配置: {final_lora_path}, 权重: {final_lora_weight}")
                else:
                    # 清除之前的LoRA配置
                    if hasattr(self, '_current_lora_path'):
                        delattr(self, '_current_lora_path')
                    if hasattr(self, '_current_lora_weight'):
                        delattr(self, '_current_lora_weight')
            
            # 检查显存是否充足
            if not self._check_memory_availability(width, height):
                # 尝试清理显存后再检查
                self._clean_memory()
                if not self._check_memory_availability(width, height):
                    # 如果仍然不足，尝试降低分辨率
                    logger.warning("显存不足，尝试降低分辨率")
                    width = int(width * 0.8)
                    height = int(height * 0.8)
                    
                    # 再次检查
                    if not self._check_memory_availability(width, height):
                        return {"status": "error", "error": "显存严重不足，无法生成图像"}
            
            # 记录开始时间用于性能监控
            start_time = time.time()
            
            # 根据模型类型调用不同的生成方法
            if self._model_type == 'stable_diffusion':
                images = self._generate_with_sd(prompt, negative_prompt, width, height, 
                                              num_inference_steps, guidance_scale, 
                                              num_images, seed)
            elif self._model_type == 'sdxl':
                images = self._generate_with_sdxl(prompt, negative_prompt, width, height, 
                                                num_inference_steps, guidance_scale, 
                                                num_images, seed)
            else:
                # 其他图像生成模型的处理逻辑
                images = self._generate_with_other_model(prompt, negative_prompt, width, height, 
                                                        num_inference_steps, guidance_scale, 
                                                        num_images, seed)
            
            # 记录生成时间
            generation_time = time.time() - start_time
            logger.info(f"图像生成耗时: {generation_time:.2f}秒")
            
            # 将生成的图像转换为可用格式
            result = {
                "status": "success",
                "images": images,
                "metadata": {
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "width": width,
                    "height": height,
                    "num_inference_steps": num_inference_steps,
                    "guidance_scale": guidance_scale,
                    "seed": seed,
                    "timestamp": time.time(),
                    "generation_time": generation_time,
                    "precision_level": self.config['quantization'].get('precision_level', 'fp16')
                }
            }
            
            # 生成后再次清理内存
            self._clean_memory()
            
            return result
            
        except torch.cuda.OutOfMemoryError:
            logger.error("生成图像时显存不足")
            self._clean_memory()
            
            # 尝试精度降级
            if self.config['memory_monitoring']['auto_precision_downscale']:
                precision_level = self.config['quantization'].get('precision_level', 'fp16')
                lower_precision = self._get_next_lower_precision(precision_level)
                if lower_precision:
                    logger.warning(f"显存不足，尝试降级精度至 {lower_precision}")
                    self.config['quantization']['precision_level'] = lower_precision
                    # 重新加载模型
                    if self.unload() and self.load_model():
                        # 重试生成，但降低分辨率
                        return self.generate_image(
                            prompt, negative_prompt, width=int(width*0.8), height=int(height*0.8),
                            num_inference_steps=num_inference_steps, guidance_scale=guidance_scale,
                            num_images=num_images, seed=seed
                        )
            
            return {"status": "error", "error": "显存不足，请尝试降低图像尺寸或减少生成图像数量"}
        except Exception as e:
            logger.error(f"生成图像时出错: {str(e)}")
            self._clean_memory()  # 出错时也清理内存
            return {"status": "error", "error": f"错误: {str(e)}"}

    def _generate_with_sd(self, 
                         prompt: str,
                         negative_prompt: str,
                         width: int,
                         height: int,
                         num_inference_steps: int,
                         guidance_scale: float,
                         num_images: int,
                         seed: Optional[int]) -> List[Image.Image]:
        """
        使用基础StableDiffusion生成图像 - 优化版，支持低显存模式
        """
        model = self.model_manager.load_model(self._model_name)
        
        if not model:
            raise Exception("SD模型未加载")
        
        try:
            from diffusers import StableDiffusionPipeline
            
            # 检查模型类型
            if isinstance(model, StableDiffusionPipeline):
                # 设置随机种子
                if seed is not None:
                    torch.manual_seed(seed)
                    torch.cuda.manual_seed_all(seed)
                
                # 准备生成参数 - 优化版本
                generate_kwargs = {
                    'prompt': prompt,
                    'negative_prompt': negative_prompt,
                    'width': width,
                    'height': height,
                    'num_inference_steps': num_inference_steps,
                    'guidance_scale': guidance_scale,
                    'num_images_per_prompt': num_images,
                    'output_type': 'pil'
                }
                
                # 低显存模式优化
                if self.config['generation'].get('low_vram_mode', False):
                    # generate_kwargs['callback_on_step_end'] = self._memory_optimization_callback
                    # generate_kwargs['callback_on_step_end_tensor_inputs'] = ['latents']
                    logger.debug("启用低显存生成模式")
                
                # 禁用后处理（如果配置要求）
                if self.config['generation'].get('disable_postprocessing', True):
                    # 移除可能的后处理器
                    if hasattr(model, 'safety_checker'):
                        model.safety_checker = None
                    if hasattr(model, 'feature_extractor'):
                        model.feature_extractor = None
                    logger.debug("已禁用后处理")
                
                # 使用torch.no_grad()和可能的amp.autocast优化
                with torch.no_grad():
                    # Check if we should use CUDA based on model device or config
                    use_cuda = torch.cuda.is_available()
                    if hasattr(model, 'device'):
                        use_cuda = use_cuda and (model.device.type == 'cuda')
                    if self.config.get('device') == 'cpu':
                        use_cuda = False

                    if use_cuda:
                        try:
                            # Use new amp syntax
                            with torch.amp.autocast('cuda'):
                                images = model(**generate_kwargs).images
                        except Exception as e:
                            logger.warning(f"混合精度推理失败: {e}，尝试回退到普通模式")
                            images = model(**generate_kwargs).images
                    else:
                        # CPU模式
                        images = model(**generate_kwargs).images
                
                return images
            else:
                # 通用处理逻辑
                logger.warning("使用通用SD模型处理逻辑")
                return self._generic_sd_generation(model, prompt, negative_prompt, 
                                                 width, height, num_inference_steps, 
                                                 guidance_scale, num_images, seed)
                
        except ImportError:
            # 如果没有diffusers包，使用通用方法
            logger.warning("未找到diffusers包，使用通用方法")
            raise Exception("缺少diffusers库，请安装后重试")
        except Exception as e:
            logger.error(f"使用SD模型生成图像时出错: {str(e)}")
            raise
    
    def _memory_optimization_callback(self, pipeline, step_index, timestep, callback_kwargs):
        """
        每步推理后执行的内存优化回调
        
        Args:
            pipeline: 管道实例
            step_index: 当前步骤索引
            timestep: 当前时间步
            callback_kwargs: 回调参数
        """
        # 每几步清理一次缓存，避免频繁清理影响性能
        if step_index % 5 == 0 and torch.cuda.is_available():
            torch.cuda.empty_cache()
        return callback_kwargs

    def _generate_with_sdxl(self, 
                          prompt: str,
                          negative_prompt: str,
                          width: int,
                          height: int,
                          num_inference_steps: int,
                          guidance_scale: float,
                          num_images: int,
                          seed: Optional[int]) -> List[Image.Image]:
        """
        使用SDXL生成图像
        """
        model = self.model_manager.load_model(self._model_name)
        
        if not model:
            raise Exception("SDXL模型未加载")
        
        try:
            from diffusers import StableDiffusionXLPipeline
            
            # 检查模型类型
            if isinstance(model, StableDiffusionXLPipeline):
                # 设置随机种子
                if seed is not None:
                    torch.manual_seed(seed)
                    torch.cuda.manual_seed_all(seed)
                
                # SDXL推荐尺寸
                if width < 768 or height < 768:
                    logger.warning("SDXL模型推荐使用768x768或更大的分辨率")
                
                # 生成图像
                images = model(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=guidance_scale,
                    num_images_per_prompt=num_images
                ).images
                
                return images
            else:
                # 尝试通用处理
                logger.warning("使用通用SDXL模型处理逻辑")
                return self._generic_sd_generation(model, prompt, negative_prompt, 
                                                 width, height, num_inference_steps, 
                                                 guidance_scale, num_images, seed)
                
        except ImportError:
            logger.warning("未找到diffusers包，无法使用SDXL")
            raise Exception("缺少diffusers库，请安装后重试")
        except Exception as e:
            logger.error(f"使用SDXL模型生成图像时出错: {str(e)}")
            raise

    def _generate_with_other_model(self, 
                                 prompt: str,
                                 negative_prompt: str,
                                 width: int,
                                 height: int,
                                 num_inference_steps: int,
                                 guidance_scale: float,
                                 num_images: int,
                                 seed: Optional[int]) -> List[Image.Image]:
        """
        使用其他类型的图像生成模型
        这里可以扩展支持其他图像生成模型
        """
        model = self.model_manager.get_model(self._model_name)
        
        if not model:
            raise Exception("图像生成模型未加载")
        
        # 示例实现，实际使用时需要根据具体模型API调整
        logger.warning(f"使用其他图像生成模型类型: {self._model_type}")
        
        # 尝试使用通用方法
        return self._generic_sd_generation(model, prompt, negative_prompt, 
                                         width, height, num_inference_steps, 
                                         guidance_scale, num_images, seed)

    def _generic_sd_generation(self, 
                              model,
                              prompt: str,
                              negative_prompt: str,
                              width: int,
                              height: int,
                              num_inference_steps: int,
                              guidance_scale: float,
                              num_images: int,
                              seed: Optional[int]) -> List[Image.Image]:
        """
        通用SD图像生成方法
        当没有特定模型处理器时使用
        """
        # 这是一个占位实现
        # 实际使用时应该根据具体模型的API进行实现
        raise NotImplementedError("通用SD生成方法未实现")

    def _check_memory_availability(self, width: int, height: int) -> bool:
        """
        检查显存是否足够 - 优化版，更精确的内存估算
        
        Args:
            width: 图像宽度
            height: 图像高度
            
        Returns:
            bool: 显存是否足够
        """
        try:
            if not torch.cuda.is_available():
                return True  # CPU模式下总是返回True
            
            # 获取当前GPU信息
            device_props = torch.cuda.get_device_properties(0)
            total_memory_gb = device_props.total_memory / (1024 * 1024 * 1024)
            
            # 更精确的显存估算，考虑分辨率、批次大小和模型大小
            # 基础模型大小估算 (GB)
            model_size_gb = 2.0  # SD基础模型约2GB
            if self._model_type == 'sdxl':
                model_size_gb = 6.0  # SDXL模型更大
            
            # 根据精度调整模型大小估算
            precision_level = self.config['quantization'].get('precision_level', 'fp16')
            if precision_level == 'fp8':
                model_size_gb *= 0.5
            elif precision_level == 'fp4':
                model_size_gb *= 0.25
            
            # 计算潜在空间大小并估算所需显存
            # 潜在空间通常是原始图像的1/8大小
            latent_width = width // 8
            latent_height = height // 8
            # 每个潜在向量使用的内存（取决于精度）
            precision_size = 2.0 if precision_level == 'fp16' else 1.0 if precision_level in ['fp8', 'fp4'] else 4.0
            # 估算每步推理需要的内存
            per_step_memory_gb = (latent_width * latent_height * 4 * precision_size) / (1024 * 1024 * 1024)
            
            # 总的显存估算（模型大小 + 生成过程中的峰值内存）
            # 考虑到UNet、VAE等组件的内存占用
            estimated_memory_gb = model_size_gb + (per_step_memory_gb * 3)  # 乘以3作为缓冲
            
            # 获取当前已分配的显存
            allocated_gb = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
            
            # 计算可用显存
            available_gb = total_memory_gb - allocated_gb
            
            # 添加安全余量（至少保留0.5GB）
            required_gb = estimated_memory_gb + 0.5
            
            logger.debug(f"显存检查: 可用={available_gb:.2f}GB, 估计需要={required_gb:.2f}GB, 分辨率={width}x{height}")
            
            # 检查是否有足够的显存
            return available_gb > required_gb
            
        except Exception as e:
            logger.warning(f"检查显存时出错: {str(e)}")
            # 出错时使用保守的估计
            try:
                if torch.cuda.is_available():
                    allocated_gb = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
                    total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
                    # 保守估计，确保至少有30%的显存取用空间
                    return (total_gb - allocated_gb) > (total_gb * 0.3)
            except:
                pass
            return False

    def _clean_memory(self):
        """
        清理显存
        """
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
                logger.info("已清理显存")
        except Exception as e:
            logger.error(f"清理显存时出错: {str(e)}")

    def unload(self) -> bool:
        """
        卸载模型
        
        Returns:
            bool: 是否卸载成功
        """
        try:
            if self._model_name:
                result = self.model_manager.unload_model(self._model_name)
                if result:
                    self._model_loaded = False
                    self._clean_memory()  # 卸载后清理显存
                    logger.info(f"SD模型已卸载: {self._model_name}")
                return result
            return True
        except Exception as e:
            logger.error(f"卸载SD模型失败: {str(e)}")
            return False

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
            
            if self._model_type in ['stable_diffusion', 'sdxl', 'other_image_gen']:
                # 检查本地模型
                is_loaded = self.model_manager.is_model_loaded(self._model_name)
                result["model_loaded"] = is_loaded
                result["model_path"] = self.config["sd_model_path"]
                
                if torch.cuda.is_available():
                    # 添加GPU状态信息
                    current_available = torch.cuda.memory_allocated() / (1024 * 1024 * 1024)
                    max_memory = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
                    result["gpu_memory_used_gb"] = round(current_available, 2)
                    result["gpu_memory_total_gb"] = round(max_memory, 2)
                
                if not is_loaded:
                    result["status"] = "warning"
                    result["message"] = "模型未加载，但可以按需加载"
                    
            return result
            
        except Exception as e:
            logger.error(f"健康检查失败: {str(e)}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": time.time()
            }


# 便捷函数
def create_sd_adapter(config: Optional[Dict[str, Any]] = None) -> SDAdapter:
    """
    创建StableDiffusion模型适配器实例
    
    Args:
        config: 配置参数
        
    Returns:
        SDAdapter实例
    """
    return SDAdapter(config)