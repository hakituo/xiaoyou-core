#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import websockets
import json
import time
import logging
import httpx
from collections import defaultdict
import threading
from pathlib import Path

# --- 核心模块导入 ---
# TRM适配器导入
try:
    from core.trm_adapter import TRMAdapter
except ImportError:
    logging.warning("TRM适配器未找到。使用模拟实现。")
    class TRMAdapterMock:
        async def query_llm_async(self, user_id, prompt, history):
            await asyncio.sleep(1.5)
            return f"这是对'{prompt[:20]}...'的异步回复。"
        
        async def transcribe_audio_async(self, audio_data):
            await asyncio.sleep(1)
            return "这是模拟的语音转录结果。"
    
    def get_trm_adapter():
        return TRMAdapterMock()

# TTS管理器导入
try:
    from multimodal.tts_manager import get_tts_manager
except ImportError:
    # 如果voice包中的tts_manager不可用，尝试直接导入
    try:
        from tts_manager import get_tts_manager
    except ImportError:
        # 最后的降级方案：使用简单同步模拟
        logging.warning("tts_manager未找到。使用简单同步模拟。")
        class TTSManagerMock:
            def synthesize_and_play(self, text: str):
                logging.info(f"🎤 [TTS模拟] 正在合成'{text[:30]}...'(阻塞方式，2秒)。")
                time.sleep(2)
                logging.info("🔊 [TTS模拟] 播放完成。")
        _tts_mock = TTSManagerMock()
        def get_tts_manager(): return _tts_mock

# 内存管理器导入
try:
    from memory.memory_manager import MemoryManager
except ImportError:
    logging.warning("内存管理器未找到。使用模拟实现。")
    class MemoryManager:
        def __init__(self, user_id, max_length=50, auto_save_interval=300):
            self.user_id = user_id
            self.history = []
            self.max_length = max_length
            self.auto_save_interval = auto_save_interval
            self.last_save_time = time.time()
        
        def add_message(self, role, content):
            self.history.append({"role": role, "content": content})
            if len(self.history) > self.max_length:
                self.history = self.history[-self.max_length:]
        
        def get_history(self):
            return self.history
        
        def save_memory(self):
            logging.info(f"💾 [同步I/O] 已保存用户 {self.user_id} 的记忆。")
            self.last_save_time = time.time()
        
        def should_auto_save(self):
            return time.time() - self.last_save_time > self.auto_save_interval


# --- 异步LLM查询函数（使用TRM适配器）---
async def query_model_async(user_id: str, prompt: str, history: list) -> str:
    """
    异步调用LLM模型，使用TRM适配器处理I/O密集型任务。
    通过'await'确保不会阻塞事件循环。
    """
    logger.info(f"🌐 [I/O任务] 用户 {user_id} 正在发送请求到LLM模型...")
    
    try:
        # 尝试获取TRM适配器
        try:
            trm_adapter = TRMAdapter() if 'TRMAdapter' in globals() else get_trm_adapter()
            response_text = await trm_adapter.query_llm_async(user_id, prompt, history)
        except Exception as adapter_error:
            # 如果TRM适配器调用失败，降级到模拟实现
            logging.warning(f"TRM适配器调用失败，使用模拟响应: {adapter_error}")
            if "mock 5s" in prompt.lower():
                await asyncio.sleep(5)  
                response_text = "我已完成5秒的并行推理模拟。注意在等待期间WebSocket连接保持流畅。"
            else:
                await asyncio.sleep(1.5)  
                response_text = f"这是对'{prompt[:20]}...'的异步回复。"
                
    except Exception as e:
        response_text = f"系统错误: {str(e)}"
        logger.error(f"LLM调用失败: {e}", exc_info=True)
        
    logger.info(f"✅ [I/O任务] 用户 {user_id} 已收到LLM响应。")
    return response_text

# --- 异步语音转录函数 ---  
async def transcribe_audio_async(user_id: str, audio_data) -> str:
    """
    异步转录音频数据，使用TRM适配器处理STT任务。
    """
    logger.info(f"🎵 [I/O任务] 用户 {user_id} 正在进行语音识别...")
    
    try:
        # 尝试使用TRM适配器进行语音转录
        try:
            trm_adapter = TRMAdapter() if 'TRMAdapter' in globals() else get_trm_adapter()
            transcription = await trm_adapter.transcribe_audio_async(audio_data)
        except Exception as adapter_error:
            logging.warning(f"STT转录失败，使用模拟结果: {adapter_error}")
            await asyncio.sleep(1)
            transcription = "[模拟] 你好，我是小悠，很高兴为你服务！"
            
        logger.info(f"🎯 [I/O任务] 用户 {user_id} 的语音识别完成。")
        return transcription
    except Exception as e:
        logger.error(f"语音转录失败: {e}", exc_info=True)
        return f"语音识别错误: {str(e)}"


# --- 配置和全局状态 ---

# 配置日志
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 连接管理
global_clients = set()
# 用户记忆映射表
user_memory_map = defaultdict(lambda: MemoryManager(user_id="default", max_length=50, auto_save_interval=300))
# 心跳时间记录
socket_heartbeats = {}
# 最大连接数
MAX_CONNECTIONS = 10
# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 30
# 心跳超时（秒）
HEARTBEAT_TIMEOUT = 60

# 系统状态
SYSTEM_STATUS = {
    "running": True,
    "start_time": time.time(),
    "total_queries": 0,
    "active_users": 0
}


# --- 异步核心功能：TTS包装器 ---
async def synthesize_and_send_tts(user_id: str, text: str):
    """
    将同步TTS调用包装到单独的线程中，避免阻塞asyncio事件循环。
    """
    logger.info(f"⚙️ [CPU任务] 用户 {user_id} 请求TTS合成...")
    tts_manager = get_tts_manager()
    
    # 使用asyncio.to_thread()将同步阻塞函数卸载到后台线程池
    try:
        await asyncio.to_thread(tts_manager.synthesize_and_play, text)
        logger.info(f"🎉 [CPU任务] 用户 {user_id} 的TTS合成已在后台线程完成。")
    except Exception as e:
        logger.error(f"TTS合成失败: {e}", exc_info=True)


# --- WebSocket消息处理器 ---
async def handler(websocket, path):
    """处理单个WebSocket连接"""
    if len(global_clients) >= MAX_CONNECTIONS:
        await websocket.close(code=1008, reason="服务器已达到最大容量")
        logger.warning("连接被拒绝: 已达到最大连接数。")
        return
        
    global_clients.add(websocket)
    # 为每个连接分配用户ID
    user_id = f"user_{id(websocket)}"
    socket_heartbeats[websocket] = time.time()
    user_memory = user_memory_map[user_id] 
    user_memory.user_id = user_id 
    logger.info(f"🔗 已建立来自 {websocket.remote_address} 的新连接，分配ID: {user_id}")
    
    # 更新系统状态
    SYSTEM_STATUS["active_users"] += 1
    
    try:
        # 通知客户端连接成功
        await websocket.send(json.dumps({
            "type": "system", 
            "content": f"小悠核心连接成功。您的用户ID: {user_id}。输入'mock 5s'测试并发I/O性能。"
        }))

        # 主循环：接收消息
        async for message in websocket:
            socket_heartbeats[websocket] = time.time()  # 心跳更新
            
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"从 {user_id} 收到无效的JSON: {message[:50]}...")
                continue
            
            msg_type = data.get("type")
            
            if msg_type == "heartbeat":
                continue
                
            elif msg_type == "text_input":
                prompt = data.get("text", "").strip()
                if not prompt:
                    continue

                logger.info(f"💬 [输入] 用户 {user_id}: {prompt}")
                
                # 1. 记录用户输入
                user_memory.add_message("user", prompt)
                
                # 2. 发送'思考中'通知（非阻塞）
                await websocket.send(json.dumps({
                    "type": "system", 
                    "content": "小悠正在思考中...",
                    "action": "thinking"
                }))
                
                # 3. 启动异步LLM调用（I/O密集型任务）
                # 这里的'await'在等待I/O时释放CPU给其他客户端
                response_text = await query_model_async(user_id, prompt, user_memory.get_history())
                
                # 更新系统统计
                SYSTEM_STATUS["total_queries"] += 1
                
                # 4. 记录AI响应
                user_memory.add_message("ai", response_text)
                
                # 5. 发送最终响应（非阻塞）
                await websocket.send(json.dumps({
                    "type": "message", 
                    "content": response_text,
                    "timestamp": time.time()
                }))
                
                # 6. 启动TTS播放和记忆保存（同步任务，包装在后台线程中）
                # 使用asyncio.create_task实现"即发即弃"的后台任务，防止阻塞接收下一条消息
                asyncio.create_task(synthesize_and_send_tts(user_id, response_text))
                
                # 检查是否需要自动保存记忆
                if hasattr(user_memory, 'should_auto_save') and user_memory.should_auto_save():
                    asyncio.create_task(asyncio.to_thread(user_memory.save_memory))
                    
            elif msg_type == "audio_input":
                # 处理语音输入
                audio_data = data.get("audio_data")
                if not audio_data:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "content": "无效的音频数据"
                    }))
                    continue
                
                # 异步转录音频
                transcription = await transcribe_audio_async(user_id, audio_data)
                
                # 将转录结果发送给客户端
                await websocket.send(json.dumps({
                    "type": "transcription",
                    "content": transcription
                }))
                
                # 可选：直接将转录结果作为文本输入处理
                if data.get("auto_process", False):
                    user_memory.add_message("user", transcription)
                    # 后续处理逻辑...
                    
            elif msg_type == "system_status":
                # 返回系统状态信息
                await websocket.send(json.dumps({
                    "type": "system_status",
                    "data": {
                        "running": SYSTEM_STATUS["running"],
                        "uptime": time.time() - SYSTEM_STATUS["start_time"],
                        "total_queries": SYSTEM_STATUS["total_queries"],
                        "active_users": SYSTEM_STATUS["active_users"]
                    }
                }))
                
            else:
                logger.warning(f"未知消息类型: {msg_type} 来自 {user_id}")

    except websockets.exceptions.ConnectionClosedOK:
        logger.info(f"🚫 连接已被 {user_id} 正常关闭。")
    except websockets.exceptions.ConnectionClosedError as e:
        logger.error(f"❌ 连接关闭时发生错误: {e}")
    except Exception as e:
        logger.error(f"❌ 处理 {user_id} 时出现未处理的错误: {e}", exc_info=True)
    finally:
        # 清理资源
        global_clients.discard(websocket)
        socket_heartbeats.pop(websocket, None)
        user_memory_map.pop(user_id, None)
        
        # 更新系统状态
        if SYSTEM_STATUS["active_users"] > 0:
            SYSTEM_STATUS["active_users"] -= 1
            
        logger.info(f"🧹 已完成 {user_id} 的连接清理。当前活跃客户端数: {len(global_clients)}")


# --- 心跳检查器 ---
async def heartbeat_checker():
    """定期检查客户端心跳，关闭超时连接。"""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            now = time.time()
            
            to_close = [] 
            for client in list(global_clients): 
                last_ping = socket_heartbeats.get(client, 0)
                if (now - last_ping) > HEARTBEAT_TIMEOUT:
                    remote_addr = getattr(client, 'remote_address', 'unknown')
                    logger.warning(f"客户端 {remote_addr} 心跳超时。正在关闭连接。")
                    to_close.append(client)
                
            for client in to_close:
                try:
                    await client.close(code=1008, reason="心跳超时")
                except Exception:
                    pass 
                finally:
                    global_clients.discard(client)
                    socket_heartbeats.pop(client, None)
                    # 更新活跃用户数
                    if SYSTEM_STATUS["active_users"] > 0:
                        SYSTEM_STATUS["active_users"] -= 1
                        
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"心跳检查错误: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)


# --- 周期性系统自检任务 ---
async def system_maintenance():
    """
    执行周期性系统维护任务，包括：
    - 检查内存使用情况
    - 清理过期会话数据
    - 记录系统状态日志
    """
    while True:
        try:
            await asyncio.sleep(300)  # 5分钟执行一次
            
            # 记录系统状态
            uptime = time.time() - SYSTEM_STATUS["start_time"]
            hours, remainder = divmod(int(uptime), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            logger.info(f"📊 系统状态报告 - 运行时间: {hours}h {minutes}m {seconds}s, "
                       f"活跃用户: {SYSTEM_STATUS['active_users']}, "
                       f"总请求数: {SYSTEM_STATUS['total_queries']}, "
                       f"活跃连接数: {len(global_clients)}")
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"系统维护任务错误: {e}", exc_info=True)
            await asyncio.sleep(60)  # 出错后等待1分钟再试

async def main():
    """WebSocket服务器主函数"""
    # 启动异步心跳检查器任务
    heartbeat_task = asyncio.create_task(heartbeat_checker())
    # 启动系统维护任务
    maintenance_task = asyncio.create_task(system_maintenance())
    
    server_config = {
        "host": "0.0.0.0",
        "port": 6789,
        "max_size": 5 * 1024 * 1024,  # 增加最大消息大小到5MB，以支持音频传输
        "ping_interval": None,
        "ping_timeout": None,
    }
    
    try:
        # 启动WebSocket服务器
        async with websockets.serve(handler, **server_config):
            logger.info(f"🎉 小悠核心服务(异步)启动成功: ws://{server_config['host']}:{server_config['port']}")
            logger.info("--- 使用asyncio并发调度 ---"),
            logger.info("📝 支持的消息类型: text_input, audio_input, system_status, heartbeat")
            
            # 通过等待一个永远不会完成的Future来保持服务器运行
            await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("⚠️ 小悠核心服务正在停止...")
        # 取消后台任务
        heartbeat_task.cancel()
        maintenance_task.cancel()
        # 等待任务完成
        await asyncio.gather(heartbeat_task, maintenance_task, return_exceptions=True)
    except Exception as e:
        logger.critical(f"❌ WebSocket服务器关键错误: {e}", exc_info=True)
        # 取消后台任务
        heartbeat_task.cancel()
        maintenance_task.cancel()
        raise


if __name__ == "__main__":
    # 在主线程中运行异步主函数
    try:
        logger.info("🚀 小悠核心启动中...")
        # 尝试使用asyncio.run()，处理潜在的环境问题
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 小悠核心已被用户中断。")
        SYSTEM_STATUS["running"] = False
    except Exception as e:
        logger.critical(f"❌ 小悠核心启动失败: {e}")
        SYSTEM_STATUS["running"] = False