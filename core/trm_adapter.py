#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import logging
import tempfile
import os
from typing import List, Dict, Any, Optional

# 导入核心模块
from core.llm_connector import query_model
from memory.memory_manager import MemoryManager

# 尝试导入STT连接器
try:
    from multimodal.stt_connector import get_stt_connector
    stt_available = True
except ImportError:
    logging.warning("STT连接器未找到，语音识别功能将不可用")
    stt_available = False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TRMAdapter:
    """
    TRM (Text, Recognition, Multimedia) 适配器
    提供统一的接口来访问LLM和STT功能
    """
    
    def __init__(self):
        """
        初始化TRM适配器
        """
        self.stt_connector = None
        self._initialize_stt_if_available()
        logger.info("TRM适配器初始化完成")
    
    def _initialize_stt_if_available(self):
        """
        如果STT可用，初始化STT连接器
        """
        if stt_available:
            try:
                # STT连接器的初始化将在第一次使用时异步完成
                logger.info("STT功能可用，将在需要时初始化")
            except Exception as e:
                logger.error(f"初始化STT连接器失败: {e}")
    
    async def _ensure_stt_connector(self):
        """
        确保STT连接器已初始化
        """
        if stt_available and not self.stt_connector:
            try:
                self.stt_connector = await asyncio.to_thread(get_stt_connector)
                logger.info("STT连接器初始化成功")
            except Exception as e:
                logger.error(f"获取STT连接器失败: {e}")
                raise
    
    async def query_llm_async(self, user_id: str, prompt: str, history: List[Dict[str, Any]]) -> str:
        """
        异步查询LLM模型
        
        Args:
            user_id: 用户ID
            prompt: 用户输入的提示文本
            history: 历史对话记录
            
        Returns:
            str: 模型生成的响应文本
        """
        try:
            logger.info(f"[TRM] 处理用户 {user_id} 的LLM请求")
            
            # 创建临时内存管理器来处理查询
            memory = MemoryManager(user_id=user_id)
            
            # 将历史记录添加到内存管理器
            for msg in history:
                memory.add_message(msg.get('role', 'user'), msg.get('content', ''))
            
            # 使用LLM连接器进行查询
            response = await query_model(prompt, memory)
            
            logger.info(f"[TRM] 成功获取LLM响应，长度: {len(response)} 字符")
            return response
            
        except Exception as e:
            logger.error(f"[TRM] LLM查询失败: {e}", exc_info=True)
            # 返回友好的错误信息而不是抛出异常，这样系统可以继续运行
            return f"抱歉，我在处理您的请求时遇到了问题。错误详情: {str(e)}"
    
    async def transcribe_audio_async(self, audio_data: bytes) -> str:
        """
        异步转录音频数据
        
        Args:
            audio_data: 音频数据（字节）
            
        Returns:
            str: 转录的文本
        """
        try:
            logger.info(f"[TRM] 处理音频转录请求，数据大小: {len(audio_data)} 字节")
            
            # 确保STT连接器可用
            if not stt_available:
                raise RuntimeError("STT功能不可用，请检查依赖安装")
            
            await self._ensure_stt_connector()
            
            # 将音频数据保存到临时文件
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name
            
            try:
                # 使用STT连接器进行转录
                result = await self.stt_connector.transcribe_audio_file(temp_file_path, language="zh-CN")
                
                # 提取转录文本
                transcription = result.get("text", "")
                
                logger.info(f"[TRM] 音频转录成功: {transcription[:50]}...")
                return transcription
                
            finally:
                # 清理临时文件
                if os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"[TRM] 音频转录失败: {e}", exc_info=True)
            # 返回友好的错误信息而不是抛出异常
            return f"语音识别失败: {str(e)}"
    
    async def close(self):
        """
        关闭适配器，释放资源
        """
        try:
            if self.stt_connector:
                await self.stt_connector.close()
                self.stt_connector = None
                logger.info("TRM适配器资源已释放")
        except Exception as e:
            logger.error(f"关闭TRM适配器时出错: {e}")
    
    async def __aenter__(self):
        """
        异步上下文管理器入口
        """
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        异步上下文管理器出口
        """
        await self.close()


# 全局适配器实例，用于快速访问
global_trm_adapter = None


def get_trm_adapter() -> TRMAdapter:
    """
    获取全局TRM适配器实例
    
    Returns:
        TRMAdapter: 适配器实例
    """
    global global_trm_adapter
    
    if global_trm_adapter is None:
        global_trm_adapter = TRMAdapter()
    
    return global_trm_adapter


# 导出模块中的主要类和函数
__all__ = ['TRMAdapter', 'get_trm_adapter']


# 测试代码
if __name__ == "__main__":
    import asyncio
    
    async def test_adapter():
        adapter = TRMAdapter()
        
        # 测试LLM查询
        try:
            response = await adapter.query_llm_async(
                "test_user", 
                "你好，你是谁？", 
                []
            )
            print(f"LLM测试响应: {response}")
        except Exception as e:
            print(f"LLM测试失败: {e}")
        
        await adapter.close()
    
    asyncio.run(test_adapter())