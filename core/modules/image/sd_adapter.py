#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forge API 客户端适配器 (SDAdapter)
完全替换原有的 diffusers 实现，改为调用本地 Forge API
"""

import logging
import requests
import base64
import io
import time
from typing import Dict, Optional, Any, List
from PIL import Image

# 配置日志
logger = logging.getLogger(__name__)

class SDAdapter:
    """
    Forge API 客户端
    不加载任何模型到本地显存，全部指令发送给 Forge 后端执行。
    速度快，省显存。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # 兼容旧代码的 config 参数，但主要关注 url
        self.config = config or {}
        self.url = self.config.get("forge_url", "http://127.0.0.1:7860")
        logger.info(f"图像模块初始化，连接 Forge 地址: {self.url}")
        
        # 定义模型文件名映射 (用户提供的映射 + 常用映射)
        # 必须和 Forge 文件夹里的文件名一模一样
        self.models = {
            "pony": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
            "asian": "sdxl10ArienmixxlAsian_v45Pruned.safetensors",
            "sdxl": "sdxl10ArienmixxlAsian_v45Pruned.safetensors", # Alias for asian
            "sd15": "nsfw_v10.safetensors",
            "nsfw": "nsfw_v10.safetensors",
            "chilloutmix": "chilloutmix_NiPrunedFp32Fix.safetensors",
            "ghostmix": "ghostmix_v20Bakedvae.safetensors"
        }
        
        # 定义 VAE 映射
        self.vaes = {
            "anime": "vaeKlF8Anime2_klF8Anime2VAE.safetensors",
            "klf8": "vaeKlF8Anime2_klF8Anime2VAE.safetensors",
            "default": "Automatic"
        }
        
        # 兼容 BaseAdapter 的一些属性，防止调用方报错
        self.available_models = []
        self.available_vaes = []
        self._model_name = "default"
        
        # 尝试连接并刷新模型列表
        self._refresh_assets()

    def _refresh_assets(self, model_manager=None):
        """
        从 Forge API 获取可用模型列表
        """
        try:
            # 获取模型列表
            res = requests.get(f"{self.url}/sdapi/v1/sd-models")
            if res.status_code == 200:
                models = res.json()
                self.available_models = []
                for m in models:
                    name = m.get('model_name')
                    filename = m.get('filename') # 通常包含完整路径或相对路径
                    # 简化名称用于显示
                    simple_name = m.get('title', name)
                    self.available_models.append({
                        "name": simple_name,
                        "path": filename, # 这里存 filename 给 switch_model 用
                        "id": simple_name
                    })
                    # 尝试自动更新 self.models 映射
                    # 例如如果 title 包含 'pony'，则更新 'pony' 的映射
                    lower_title = simple_name.lower()
                    if 'pony' in lower_title:
                        self.models['pony'] = simple_name
                    elif 'chilloutmix' in lower_title:
                        self.models['chilloutmix'] = simple_name
                    elif 'ghostmix' in lower_title:
                        self.models['ghostmix'] = simple_name
                    elif 'asian' in lower_title:
                        self.models['asian'] = simple_name
                        self.models['sdxl'] = simple_name
                
                logger.info(f"从 Forge 获取到 {len(self.available_models)} 个模型")
            
            # 获取 VAE 列表
            res_vae = requests.get(f"{self.url}/sdapi/v1/sd-vae")
            if res_vae.status_code == 200:
                vaes = res_vae.json()
                self.available_vaes = []
                for v in vaes:
                    self.available_vaes.append({
                        "name": v.get('model_name'),
                        "path": v.get('filename'),
                        "id": v.get('model_name')
                    })
                logger.info(f"从 Forge 获取到 {len(self.available_vaes)} 个 VAE")

        except Exception as e:
            logger.warning(f"无法连接 Forge API ({self.url}): {e}")
            # 保持默认映射

    def load_model(self, lora_path=None, lora_weight=None, vae_path=None) -> bool:
        """
        兼容旧接口，实际上只需要检查连接
        """
        try:
            requests.get(f"{self.url}/sdapi/v1/options", timeout=3)
            return True
        except:
            return False

    def set_model(self, model_key):
        """发送指令让 Forge 切换模型"""
        # 1. 尝试从 self.models 映射中获取
        target_model = self.models.get(model_key, model_key)
        
        # 2. 如果映射没找到，且 available_models 不为空，尝试模糊匹配
        if model_key not in self.models and self.available_models:
            for m in self.available_models:
                if model_key.lower() in m['name'].lower():
                    target_model = m['name'] # 使用 title
                    break

        if not target_model:
            logger.warning(f"未知模型 key: {model_key}")
            return False

        try:
            # 1. 先查当前是啥模型
            opt_res = requests.get(f"{self.url}/sdapi/v1/options")
            if opt_res.status_code != 200:
                return False
                
            current = opt_res.json().get('sd_model_checkpoint', '')
            
            # 简单包含匹配，因为 title 可能很长
            if target_model in current or current in target_model:
                logger.info(f"Forge 当前已经是 {current}，无需切换")
                self._model_name = current
                return True

            # 2. 发送切换指令
            logger.info(f"正在请求 Forge 切换到: {target_model} ...")
            payload = {"sd_model_checkpoint": target_model}
            requests.post(f"{self.url}/sdapi/v1/options", json=payload)
            
            logger.info("切换指令已发送")
            self._model_name = target_model
            return True
        except Exception as e:
            logger.error(f"连接 Forge 失败: {e}")
            return False

    def set_vae(self, vae_key):
        """发送指令让 Forge 切换 VAE"""
        # 1. 尝试从 self.vaes 映射中获取
        target_vae = self.vaes.get(vae_key, vae_key)
        
        # 2. 如果映射没找到，尝试在 available_vaes 中查找
        if vae_key not in self.vaes and self.available_vaes:
            for v in self.available_vaes:
                if vae_key.lower() in v['name'].lower():
                    target_vae = v['name']
                    break

        if not target_vae:
             # 如果都没找到，且 key 看起来像文件名，就直接试试
            target_vae = vae_key

        try:
            # 1. 先查当前 VAE
            opt_res = requests.get(f"{self.url}/sdapi/v1/options")
            if opt_res.status_code != 200:
                return False
                
            current = opt_res.json().get('sd_vae', '')
            
            if target_vae in current or current in target_vae:
                logger.info(f"Forge 当前 VAE 已经是 {current}，无需切换")
                return True

            # 2. 发送切换指令
            logger.info(f"正在请求 Forge 切换 VAE 到: {target_vae} ...")
            payload = {"sd_vae": target_vae}
            requests.post(f"{self.url}/sdapi/v1/options", json=payload)
            
            # 3. 验证是否切换成功 (可选，因为有时候 Forge 响应慢)
            # time.sleep(0.5)
            # opt_res = requests.get(f"{self.url}/sdapi/v1/options")
            # new_vae = opt_res.json().get('sd_vae', '')
            # logger.info(f"VAE 已切换为: {new_vae}")
            
            return True
        except Exception as e:
            logger.error(f"切换 VAE 失败: {e}")
            return False

    def generate_image(self, 
                      prompt: str,
                      negative_prompt: Optional[str] = None,
                      width: Optional[int] = 512,
                      height: Optional[int] = 512,
                      num_inference_steps: Optional[int] = 20,
                      guidance_scale: Optional[float] = 7.0,
                      num_images: int = 1,
                      seed: Optional[int] = -1,
                      lora_path: Optional[str] = None,
                      lora_weight: Optional[float] = None,
                      model_name: Optional[str] = None,
                      vae_name: Optional[str] = None) -> Dict[str, Any]:
        """发送画图指令"""
        try:
            # 1. 自动切换模型
            # 如果指定了 model_name，尝试切换
            if model_name:
                self.set_model(model_name)
            # 否则使用默认或当前模型 (不做操作)

            # 2. 自动切换 VAE (如果有)
            if vae_name:
                self.set_vae(vae_name)

            # 3. 准备参数
            # 处理种子
            if seed is None: seed = -1
            
            payload = {
                "prompt": prompt,
                "negative_prompt": negative_prompt if negative_prompt else "",
                "steps": num_inference_steps,
                "width": width,
                "height": height,
                "cfg_scale": guidance_scale,
                "sampler_name": "Euler a", # 默认采样器
                "batch_size": num_images,
                "seed": seed,
                "restore_faces": False # 默认关闭，SDXL通常不需要，且可能影响风格
            }
            
            # SDXL 特定优化
            # 如果是 pony 或 asian，通常建议更高的分辨率
            current_model_lower = self._model_name.lower()
            if 'xl' in current_model_lower or 'pony' in current_model_lower:
                 if width < 768 and height < 768:
                     payload['width'] = 832
                     payload['height'] = 1216
                     logger.info("检测到 SDXL 模型，自动调整分辨率为 832x1216")
                 
                 # SDXL/Pony 不使用 VAE，强制切换回 Automatic
                 # 除非用户显式指定了 vae_name (虽然一般不推荐)
                 if not vae_name:
                     logger.info("SDXL/Pony 模型: 自动将 VAE 重置为 Automatic")
                     self.set_vae("Automatic")

            logger.info(f"发送生成请求: {prompt[:50]}...")
            
            # 4. 发送请求
            response = requests.post(f"{self.url}/sdapi/v1/txt2img", json=payload)
            
            if response.status_code == 200:
                r = response.json()
                images = []
                for img_str in r['images']:
                    # 解码图片
                    image_data = base64.b64decode(img_str)
                    image = Image.open(io.BytesIO(image_data))
                    images.append(image)
                
                logger.info(f"图像生成成功！共 {len(images)} 张")
                return {"status": "success", "images": images}
            else:
                logger.error(f"Forge 返回错误: {response.status_code} - {response.text}")
                return {"status": "error", "error": f"Forge API Error: {response.status_code}"}

        except Exception as e:
            logger.error(f"生成失败，请检查 Forge 是否启动 (webui-user.bat): {e}")
            return {"status": "error", "error": str(e)}

    # 兼容性方法
    def get_available_models(self):
        return self.available_models
        
    def _check_memory_availability(self, *args):
        return True # API 模式下不检查本地显存

    def _clean_memory(self):
        pass # API 模式无需清理

    def unload(self):
        return True # 无需卸载

# 便捷函数
def create_sd_adapter(config: Optional[Dict[str, Any]] = None) -> SDAdapter:
    return SDAdapter(config)
