import asyncio
import websockets
import json
import time
import logging
from collections import defaultdict

from core.llm_connector import query_model, task_manager
from memory.memory_manager import MemoryManager
from core.utils import tts_generate

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 连接管理
global_clients = set()
# 使用字典存储每个用户的MemoryManager实例
user_memory_map = defaultdict(lambda: MemoryManager(user_id="default", max_length=10, auto_save_interval=300))
# 心跳时间记录
socket_heartbeats = {}
# 最大连接数
MAX_CONNECTIONS = 10
# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 30
# 心跳超时（秒）
HEARTBEAT_TIMEOUT = 60

async def broadcast(msg, exclude_client=None):
    """优化的广播函数，支持排除特定客户端和错误处理"""
    if not global_clients:
        return
    
    # 过滤掉可能已关闭的连接
    # 使用getattr安全检查，对于不同WebSocket实现有兼容性
    active_clients = []
    for c in global_clients:
        try:
            # 尝试检查连接是否仍处于打开状态
            # 对于websockets库，使用socket属性或其他方式判断
            if hasattr(c, 'closed'):
                if not c.closed:
                    active_clients.append(c)
            elif hasattr(c, 'socket') and c.socket:
                active_clients.append(c)
            elif hasattr(c, 'connection') and c.connection:
                active_clients.append(c)
            else:
                # 如果无法判断，尝试发送一个ping或简单消息
                # 但为了安全起见，默认保留连接
                active_clients.append(c)
        except:
            # 如果检查失败，排除该连接
            pass
    
    # 更新全局客户端集合
    global_clients.clear()
    global_clients.update(active_clients)
    
    if not active_clients:
        return
    
    # 创建发送任务列表
    send_tasks = []
    for client in active_clients:
        if client != exclude_client:
            send_tasks.append(send_with_retry(client, json.dumps(msg)))
    
    if send_tasks:
        # 异步执行所有发送任务
        results = await asyncio.gather(*send_tasks, return_exceptions=True)
        # 处理发送失败的情况
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"广播消息失败到客户端: {result}")

async def send_with_retry(websocket, message, max_retries=2):
    """带重试机制的消息发送函数，增加连接状态预检查"""
    # 先检查连接状态
    if hasattr(websocket, 'closed') and websocket.closed:
        logger.warning("连接已关闭，跳过发送")
        return False
    
    retries = 0
    while retries <= max_retries:
        try:
            # 使用shield防止取消操作影响发送
            await asyncio.shield(websocket.send(message))
            return True
        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
            # 连接已关闭，不再重试
            logger.warning("连接已关闭，停止重试")
            return False
        except Exception as e:
            retries += 1
            if retries > max_retries:
                logger.error(f"发送消息失败，已达到最大重试次数: {e}")
                # 不再抛出异常，避免任务失败
                return False
            logger.warning(f"发送消息失败，正在重试 ({retries}/{max_retries}): {e}")
            await asyncio.sleep(0.5)
    return False

async def handle_message(websocket, data):
    """处理接收到的消息，使用任务管理器限制并发"""
    platform = data.get("platform", "unknown")
    user_id = data.get("user_id", "web")
    text = data.get("message", "").strip()
    
    # 空消息不处理
    if not text:
        return
    
    try:
        # 检查是否是文件上传消息
        if data.get("file_info"):
            file_info = data["file_info"]
            file_name = file_info.get("name", "未知文件")
            file_size = file_info.get("size", 0)
            
            logger.info(f"收到文件上传请求 - 用户: {user_id}, 文件名: {file_name}, 大小: {file_size}字节")
            
            # 由于千问3max模型可能不直接支持文件处理，我们提供一个友好的响应
            file_response = f"我已收到您上传的文件 '{file_name}'。目前千问3max模型支持处理文字内容，如果您希望我分析文件内容，请您描述文件中的关键信息，我会尽力为您提供帮助。"
            
            # 获取或创建用户的内存管理器
            user_memory = user_memory_map[user_id]
            
            # 添加消息到历史记录
            user_memory.add_message("user", text)
            user_memory.add_message("assistant", file_response)
            
            # 准备响应数据
            msg_data = {
                "type": "message",
                "platform": platform,
                "user_id": user_id,
                "text": text,
                "response": file_response,
                "timestamp": time.time()
            }
            
            # 发送响应给客户端
            await send_with_retry(websocket, json.dumps(msg_data))
            return
        
        # 检查是否是心跳消息
        if text == "__heartbeat__":
            socket_heartbeats[websocket] = time.time()
            await websocket.send(json.dumps({"type": "heartbeat"}))
            return
        
        # 获取或创建用户的内存管理器
        user_memory = user_memory_map[user_id]
        
        # 使用任务管理器限制并发请求数
        response = await task_manager.run_task(query_model(text, user_memory))
        
        # 异步生成TTS，但不阻塞响应
        tts_path = ""
        try:
            tts_path = await tts_generate(response)
        except Exception as e:
            logger.error(f"生成TTS失败: {e}")
            # 即使TTS失败，也继续处理响应
        
        # 添加消息到历史记录
        user_memory.add_message("user", text)
        user_memory.add_message("assistant", response)
        
        # 准备响应数据
        msg_data = {
            "type": "message",
            "platform": platform,
            "user_id": user_id,
            "text": text,
            "response": response,
            "tts": tts_path,
            "audio_file": tts_path.split('/')[-1] if tts_path else None,  # 添加audio_file字段，只包含文件名
            "timestamp": time.time()
        }
        
        # 发送响应给当前客户端
        await send_with_retry(websocket, json.dumps(msg_data))
        
        # 广播消息给其他客户端
        await broadcast(msg_data, exclude_client=websocket)
        
        logger.info(f"处理消息完成 - 用户: {user_id}, 平台: {platform}, 消息长度: {len(text)}")
    
    except json.JSONDecodeError:
        error_msg = "无效的JSON格式"
        await websocket.send(json.dumps({"type": "error", "message": error_msg}))
        logger.error(f"JSON解析错误: {data}")
    except Exception as e:
        error_msg = f"处理消息时出错: {str(e)}"
        await websocket.send(json.dumps({"type": "error", "message": error_msg}))
        logger.error(f"处理消息错误: {e}", exc_info=True)

async def handler(websocket):
    """优化的WebSocket连接处理函数"""
    # 检查连接数限制
    if len(global_clients) >= MAX_CONNECTIONS:
        await websocket.send(json.dumps({"type": "error", "message": "连接数已达上限，请稍后再试"}))
        await websocket.close()
        logger.warning("拒绝新连接，已达到最大连接数限制")
        return
    
    # 添加到客户端集合
    global_clients.add(websocket)
    socket_heartbeats[websocket] = time.time()
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    logger.info(f"新客户端连接: {client_ip}, 当前连接数: {len(global_clients)}")
    
    try:
        # 发送欢迎消息
        await websocket.send(json.dumps({
            "type": "welcome", 
            "message": "连接成功，欢迎使用小悠AI！",
            "version": "1.0.0"
        }))
        
        # 处理消息循环
        async for message in websocket:
            try:
                data = json.loads(message)
                # 异步处理消息，避免阻塞，使用task而不是直接create_task以便更好地追踪
                task = asyncio.create_task(handle_message(websocket, data))
                # 添加异常处理，避免任务异常未被捕获
                task.add_done_callback(lambda t: logger.error(f"消息处理任务异常: {t.exception()}") if t.exception() else None)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "message": "无效的JSON格式"}))
    except websockets.exceptions.ConnectionClosedError as e:
        logger.info(f"客户端连接异常关闭: {client_ip}, 错误代码: {e.code}, 原因: {e.reason}")
    except websockets.exceptions.ConnectionClosedOK:
        logger.info(f"客户端正常关闭连接: {client_ip}")
    except Exception as e:
        logger.error(f"处理客户端时发生错误: {e}", exc_info=True)
    finally:
        # 清理资源
        global_clients.discard(websocket)
        socket_heartbeats.pop(websocket, None)
        logger.info(f"客户端断开连接: {client_ip}, 当前连接数: {len(global_clients)}")

async def heartbeat_checker():
    """定期检查连接心跳，清理超时连接"""
    while True:
        try:
            current_time = time.time()
            to_close = []
            
            # 找出超时连接
            for websocket, last_heartbeat in socket_heartbeats.items():
                if current_time - last_heartbeat > HEARTBEAT_TIMEOUT:
                    to_close.append(websocket)
                    logger.info(f"检测到超时连接，准备关闭")
            
            # 关闭超时连接，使用更合适的错误码1001(going away)而非1008(policy violation)
            for websocket in to_close:
                try:
                    await websocket.close(code=1001, reason="连接超时")
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                except Exception as e:
                    # 连接可能已经关闭，静默处理错误
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                    logger.debug(f"关闭超时连接失败(可能已关闭): {e}")
            
            # 发送心跳检查
            for websocket in list(global_clients):
                try:
                    # 安全检查连接状态
                    if hasattr(websocket, 'closed') and websocket.closed:
                        # 连接已关闭，清理资源
                        socket_heartbeats.pop(websocket, None)
                        global_clients.discard(websocket)
                        continue
                    
                    # 使用更安全的方式发送心跳，避免在发送过程中发生错误
                    await asyncio.shield(websocket.send(json.dumps({"type": "ping"})))
                except Exception as e:
                    # 连接可能已关闭，清理资源
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                    logger.debug(f"发送心跳失败(连接可能已关闭): {e}")
            
            # 每隔一段时间检查一次
            await asyncio.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            logger.error(f"心跳检查出错: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

async def main():
    """WebSocket服务器主函数"""
    # 启动心跳检查任务
    asyncio.create_task(heartbeat_checker())
    
    # 配置WebSocket服务器
    server_config = {
        "host": "0.0.0.0",
        "port": 6789,
        "max_size": 1 * 1024 * 1024,  # 限制最大消息大小为1MB
        "ping_interval": None,  # 禁用内置ping，使用自定义心跳
        "ping_timeout": None,
    }
    
    try:
        async with websockets.serve(handler, **server_config):
            logger.info(f"WebSocket 服务启动成功: ws://{server_config['host']}:{server_config['port']}")
            logger.info(f"最大连接数限制: {MAX_CONNECTIONS}")
            logger.info(f"心跳间隔: {HEARTBEAT_INTERVAL}秒, 超时时间: {HEARTBEAT_TIMEOUT}秒")
            # 保持服务器运行
            await asyncio.Future()
    except Exception as e:
        logger.error(f"❌ WebSocket 服务器异常: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ WebSocket 服务已停止（用户中断）")
    except Exception as e:
        logger.critical(f"❌ WebSocket 服务启动失败: {e}", exc_info=True)