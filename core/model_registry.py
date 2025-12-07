# core/model_registry.py
import gc
import torch
from core.utils.logger import get_logger

logger = get_logger("ModelRegistry")


class ModelRegistry:
    _models = {}

    @classmethod
    def register_model(cls, name, model):
        """注册模型"""
        cls._models[name] = model
        logger.info(f"模型已注册: {name}")
    
    @classmethod
    def get_model(cls, name):
        """获取模型"""
        return cls._models.get(name)
    
    @classmethod
    def unregister_model(cls, name):
        """注销模型并释放资源"""
        if name in cls._models:
            model = cls._models.pop(name)
            if hasattr(model, 'to'):
                try:
                    # 尝试将模型移到CPU并清空缓存
                    model = model.cpu()
                except:
                    pass
            del model
            gc.collect()
            torch.cuda.empty_cache()
            logger.info(f"模型已注销: {name}")

# 全局模型注册中心实例
global_model_registry = ModelRegistry()
