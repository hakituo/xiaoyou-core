#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2025 Leslie Qi

import asyncio
import websockets
import json
import time
import logging
import os
import sys
from collections import defaultdict

# Set up event loop policy for Windows at the module level
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 导入配置
from config.config import Config
config = Config()

from core.llm_connector import query_model
from memory.memory_manager import MemoryManager
from core.utils import tts_generate
import base64

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Connection management
global_clients = set()
# Use dictionary to store MemoryManager instances for each user
# We'll create MemoryManager instances dynamically based on user_id
user_memory_map = {}

# Helper function to get or create MemoryManager for a user
def get_user_memory(user_id):
    if user_id not in user_memory_map:
        user_memory_map[user_id] = MemoryManager(user_id=user_id, max_length=10, auto_save_interval=300)
    return user_memory_map[user_id]
# Heartbeat time records
socket_heartbeats = {}
# 从配置文件读取设置
MAX_CONNECTIONS = config.MAX_CONNECTIONS
# Heartbeat interval (seconds)
HEARTBEAT_INTERVAL = config.WS_HEARTBEAT_INTERVAL
# Heartbeat timeout (seconds)
HEARTBEAT_TIMEOUT = config.WS_TIMEOUT

# 并发控制
MAX_CONCURRENT_QUERIES = 3
query_semaphore = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)

async def broadcast(msg, exclude_client=None):
    """Optimized broadcast function that supports excluding specific clients and error handling"""
    if not global_clients:
        return
    
    # Filter out possibly closed connections
    # Use getattr for safe checking, compatible with different WebSocket implementations
    active_clients = []
    for c in global_clients:
        try:
            # Try to check if connection is still open
            # For websockets library, use socket property or other methods to determine
            if hasattr(c, 'closed'):
                if not c.closed:
                    active_clients.append(c)
            elif hasattr(c, 'socket') and c.socket:
                active_clients.append(c)
            elif hasattr(c, 'connection') and c.connection:
                active_clients.append(c)
            else:
                # If unable to determine, try sending a ping or simple message
                # But for safety, keep the connection by default
                active_clients.append(c)
        except:
            # If check fails, exclude this connection
            pass
    
    # Update global client set
    global_clients.clear()
    global_clients.update(active_clients)
    
    if not active_clients:
        return
    
    # Create list of send tasks
    send_tasks = []
    for client in active_clients:
        if client != exclude_client:
            send_tasks.append(send_with_retry(client, json.dumps(msg)))
    
    if send_tasks:
        # Execute all send tasks asynchronously
        results = await asyncio.gather(*send_tasks, return_exceptions=True)
        # Handle failed sending cases
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to broadcast message to client: {result}")

async def send_with_retry(websocket, message, max_retries=2):
    """Message sending function with retry mechanism and connection status pre-check"""
    # Validate inputs
    if not websocket or not message:
        logger.error("Invalid websocket or message parameter")
        return False
    
    # Check connection status first
    if hasattr(websocket, 'closed') and websocket.closed:
        logger.warning("Connection closed, skipping sending")
        return False
    
    retries = 0
    while retries <= max_retries:
        try:
            # Use shield to prevent cancellation from affecting sending
            await asyncio.shield(websocket.send(message))
            return True
        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as conn_err:
            # Connection closed, stop retrying
            logger.warning(f"Connection closed, stopping retry: {conn_err}")
            return False
        except asyncio.TimeoutError:
            # Handle timeout specifically
            logger.warning(f"Message send timeout, retrying ({retries}/{max_retries})")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

        retries += 1
        if retries > max_retries:
            logger.error(f"Failed to send message, reached maximum retry attempts: {e}")
            # No longer throw exceptions to avoid task failure
            return False
        logger.warning(f"Failed to send message, retrying ({retries}/{max_retries}): {e}")
        # Exponential backoff with jitter
        await asyncio.sleep(0.5 * (1.5 ** (retries - 1)))
    
    return False

async def handle_message(websocket, data):
    """Process received messages using task manager to limit concurrency"""
    try:
        platform = data.get("platform", "unknown")
        user_id = data.get("user_id", "web")
        # 优先使用text字段，兼容性支持message字段
        text = data.get("text", data.get("message", "")).strip()
        message_type = data.get("type", "text")
        
        # Skip empty messages
        if not text:
            return
        
        # 使用信号量控制并发
        async with query_semaphore:
            # Handle file upload messages
            if message_type == "file" and data.get("file_data"):
                file_data = data["file_data"]
                file_name = file_data.get("original_filename", "Unknown file")
                file_path = file_data.get("file_path", "")
                file_type = file_data.get("file_type", "unknown")
                
                logger.info(f"Received file upload - User: {user_id}, File: {file_name}, Type: {file_type}")
                
                # Get or create memory manager for the user
                user_memory = get_user_memory(user_id)
                
                # Process based on file type
                if file_type == "image":
                    # For image files, mention that we're processing the image
                    processed_text = f"正在分析图片: {file_name}。请等待，我会描述图片内容并回答相关问题。"
                    
                    # Add original request to history
                    user_memory.add_message("user", text)
                    
                    # Generate response considering image context
                    response = await query_model(processed_text, user_memory)
                    
                else:
                    # For audio files
                    processed_text = f"收到音频文件: {file_name}。请上传图片或发送文本消息进行交流。"
                    
                    # Add original request to history
                    user_memory.add_message("user", text)
                    
                    # Generate response
                    response = await query_model(processed_text, user_memory)
                    
                # Add assistant response to history
                user_memory.add_message("assistant", response)
                
                # Asynchronously generate TTS without blocking the response
                tts_success = False
                audio_filename = f"response_{int(time.time())}.wav"
                # 使用绝对路径来确保目录创建正确
                script_dir = os.path.dirname(os.path.abspath(__file__))
                output_dir = os.path.join(script_dir, "multimodal", "voice")
                output_path = os.path.join(output_dir, audio_filename)
                
                try:
                    # 确保目录存在 - 先检查是否存在同名文件
                    if os.path.exists(output_dir) and not os.path.isdir(output_dir):
                        logger.warning(f"Output directory exists but is not a directory, removing: {output_dir}")
                        os.remove(output_dir)
                    # 创建目录
                    os.makedirs(output_dir, exist_ok=True)
                    logger.debug(f"Created TTS directory: {output_dir}")
                    
                    # 确保输出路径是文件而不是目录
                    if os.path.exists(output_path) and os.path.isdir(output_path):
                        logger.warning(f"Output path exists but is a directory, removing: {output_path}")
                        import shutil
                        shutil.rmtree(output_path)
                    
                    tts_success = await tts_generate(response, output_path=output_path)
                except Exception as e:
                    logger.error(f"Failed to generate TTS: {e}", exc_info=True)
                
                # Prepare response data
                msg_data = {
                    "type": "message",
                    "platform": platform,
                    "user_id": user_id,
                    "text": text,
                    "response": response,
                    "tts": tts_success,
                    "audio_file": audio_filename if tts_success else None,
                    "timestamp": time.time()
                }
                
                # Send response to client
                await send_with_retry(websocket, json.dumps(msg_data))
                return
            
            # Handle voice messages
            elif message_type == "voice":
                logger.info(f"Received voice message - User: {user_id}, Text: {text[:50]}...")
                
                # Get or create memory manager for the user
                user_memory = get_user_memory(user_id)
                
                # Add voice-transcribed text to history
                user_memory.add_message("user", text)
                
                # Generate response
                response = await query_model(text, user_memory)
                
                # Add assistant response to history
                user_memory.add_message("assistant", response)
                
                # Asynchronously generate TTS without blocking the response
                tts_success = False
                audio_filename = f"response_{int(time.time())}.wav"
                # 使用绝对路径来确保目录创建正确
                script_dir = os.path.dirname(os.path.abspath(__file__))
                output_dir = os.path.join(script_dir, "multimodal", "voice")
                output_path = os.path.join(output_dir, audio_filename)
                
                try:
                    # 确保目录存在 - 先检查是否存在同名文件
                    if os.path.exists(output_dir) and not os.path.isdir(output_dir):
                        logger.warning(f"Output directory exists but is not a directory, removing: {output_dir}")
                        os.remove(output_dir)
                    # 创建目录
                    os.makedirs(output_dir, exist_ok=True)
                    logger.debug(f"Created TTS directory: {output_dir}")
                    
                    # 确保输出路径是文件而不是目录
                    if os.path.exists(output_path) and os.path.isdir(output_path):
                        logger.warning(f"Output path exists but is a directory, removing: {output_path}")
                        import shutil
                        shutil.rmtree(output_path)
                    
                    tts_success = await tts_generate(response, output_path=output_path)
                except Exception as e:
                    logger.error(f"Failed to generate TTS: {e}", exc_info=True)
                
                # Prepare response data
                msg_data = {
                    "type": "message",
                    "platform": platform,
                    "user_id": user_id,
                    "text": text,
                    "response": response,
                    "tts": tts_success,
                    "audio_file": audio_filename if tts_success else None,
                    "timestamp": time.time()
                }
                
                # Send response to client
                await send_with_retry(websocket, json.dumps(msg_data))
                return
            
            # Check if it's a heartbeat message
            if text == "__heartbeat__":
                socket_heartbeats[websocket] = time.time()
                await websocket.send(json.dumps({"type": "heartbeat"}))
                return
            
            # Get or create memory manager for the user
            user_memory = get_user_memory(user_id)
            
            # Standard text message handling
            logger.info(f"Received text message - User: {user_id}, Length: {len(text)} chars")
            
            # Directly call query_model to generate response
            response = await query_model(text, user_memory)
            
            # Asynchronously generate TTS without blocking the response
            tts_success = False
            audio_filename = f"response_{int(time.time())}.wav"
            # 使用绝对路径确保可靠性
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, "multimodal/voice")
            output_path = os.path.join(output_dir, audio_filename)
            
            try:
                # 确保目录存在 - 先检查是否存在同名文件
                if os.path.exists(output_dir) and not os.path.isdir(output_dir):
                    logger.warning(f"Output directory exists but is not a directory, removing: {output_dir}")
                    os.remove(output_dir)
                # 创建目录
                os.makedirs(output_dir, exist_ok=True)
                logger.debug(f"Created TTS directory: {output_dir}")
                
                # 确保输出路径是文件而不是目录
                if os.path.exists(output_path) and os.path.isdir(output_path):
                    logger.warning(f"Output path exists but is a directory, removing: {output_path}")
                    import shutil
                    shutil.rmtree(output_path)
                
                tts_success = await tts_generate(response, output_path=output_path)
            except Exception as e:
                logger.error(f"Failed to generate TTS: {e}", exc_info=True)
                # Continue processing response even if TTS fails
            
            # Add message to history
            user_memory.add_message("user", text)
            user_memory.add_message("assistant", response)
            
            # Prepare response data
            msg_data = {
                "type": "message",
                "platform": platform,
                "user_id": user_id,
                "text": text,
                "response": response,
                "tts": tts_success,
                "audio_file": audio_filename if tts_success else None,
                "timestamp": time.time()
            }
            
            # Send response to current client
            await send_with_retry(websocket, json.dumps(msg_data))
            
            # Broadcast message to other clients
            await broadcast(msg_data, exclude_client=websocket)
            
            logger.info(f"Message processing completed - User: {user_id}, Platform: {platform}, Message length: {len(text)}")
            
    except json.JSONDecodeError:
        error_msg = "Invalid JSON format"
        await websocket.send(json.dumps({"type": "error", "message": error_msg}))
        logger.error(f"JSON parsing error: {data}")
    except Exception as e:
        error_msg = "处理消息时出错，请稍后再试"
        await send_with_retry(websocket, json.dumps({
            "type": "error", 
            "message": error_msg,
            "timestamp": time.time()
        }))
        logger.error(f"Error processing message: {e}", exc_info=True)

async def handler(websocket):
    """Optimized WebSocket connection handling function"""
    # Check connection limit
    if len(global_clients) >= MAX_CONNECTIONS:
        await websocket.send(json.dumps({"type": "error", "message": "Connection limit reached, please try again later"}))
        await websocket.close()
        logger.warning("Rejected new connection, maximum connection limit reached")
        return
    
    # Add to client set
    global_clients.add(websocket)
    socket_heartbeats[websocket] = time.time()
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    logger.info(f"New client connected: {client_ip}, Current connections: {len(global_clients)}")
    
    try:
        # Send welcome message
        await websocket.send(json.dumps({
            "type": "welcome", 
            "message": "Connection successful, welcome to Xiaoyou AI!",
            "version": "1.0.0"
        }))
        
        # Message handling loop
        async for message in websocket:
            try:
                data = json.loads(message)
                # Process messages asynchronously to avoid blocking, use task for better tracking
                task = asyncio.create_task(handle_message(websocket, data))
                # Add exception handling to avoid uncaught task exceptions
                task.add_done_callback(lambda t: logger.error(f"Message processing task exception: {t.exception()}") if t.exception() else None)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON format"}))
    except websockets.exceptions.ConnectionClosedError as e:
        logger.info(f"Client connection closed abnormally: {client_ip}, Error code: {e.code}, Reason: {e.reason}")
    except websockets.exceptions.ConnectionClosedOK:
        logger.info(f"Client connection closed normally: {client_ip}")
    except Exception as e:
        logger.error(f"Error occurred while handling client: {e}", exc_info=True)
    finally:
        # Clean up resources
        global_clients.discard(websocket)
        socket_heartbeats.pop(websocket, None)
        logger.info(f"Client disconnected: {client_ip}, Current connections: {len(global_clients)}")

async def heartbeat_checker():
    """Periodically check connection heartbeats and clean up timed-out connections"""
    while True:
        try:
            current_time = time.time()
            to_close = []
            
            # Find timed-out connections
            for websocket, last_heartbeat in socket_heartbeats.items():
                if current_time - last_heartbeat > HEARTBEAT_TIMEOUT:
                    to_close.append(websocket)
                    logger.info(f"Detected timed-out connection, preparing to close")
            
            # Close timed-out connections, using more appropriate error code 1001(going away) instead of 1008(policy violation)
            for websocket in to_close:
                try:
                    await websocket.close(code=1001, reason="Connection timed out")
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                except Exception as e:
                    # Connection might already be closed, silently handle error
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                    logger.debug(f"Failed to close timed-out connection (might already be closed): {e}")
            
            # Send heartbeat checks
            for websocket in list(global_clients):
                try:
                    # Safely check connection status
                    if hasattr(websocket, 'closed') and websocket.closed:
                        # Connection closed, clean up resources
                        socket_heartbeats.pop(websocket, None)
                        global_clients.discard(websocket)
                        continue
                    
                    # Use safer way to send heartbeat to avoid errors during transmission
                    await asyncio.shield(websocket.send(json.dumps({"type": "ping"})))
                except Exception as e:
                    # Connection might be closed, clean up resources
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                    logger.debug(f"Failed to send heartbeat (connection might be closed): {e}")
            
            # Check at regular intervals
            await asyncio.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            logger.error(f"Error in heartbeat check: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

async def main():
    """WebSocket server main function"""
    # Start heartbeat checker task
    asyncio.create_task(heartbeat_checker())
    
    # Configure WebSocket server
    server_config = {
        "host": "127.0.0.1",  # 使用127.0.0.1而不是0.0.0.0，避免可能的绑定问题
        "port": config.WS_PORT,
        "max_size": 1 * 1024 * 1024,  # Limit maximum message size to 1MB
        "ping_interval": None,  # Disable built-in ping, use custom heartbeat
        "ping_timeout": None,
        "close_timeout": 5.0,
    }
    
    try:
        # 添加更多调试信息
        logger.info(f"Attempting to bind WebSocket server to {server_config['host']}:{server_config['port']}")
        
        # 先尝试创建一个简单的socket连接，验证端口可用性
        import socket
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            test_socket.bind((server_config['host'], server_config['port']))
            test_socket.close()
            logger.info(f"Port {server_config['port']} is available")
        except Exception as e:
            logger.error(f"Port {server_config['port']} binding test failed: {e}")
        
        async with websockets.serve(handler, **server_config):
            logger.info(f"WebSocket service started successfully: ws://{server_config['host']}:{server_config['port']}")
            logger.info(f"Maximum connection limit: {MAX_CONNECTIONS}")
            logger.info(f"Heartbeat interval: {HEARTBEAT_INTERVAL}s, Timeout: {HEARTBEAT_TIMEOUT}s")
            # Keep server running
            await asyncio.Future()  # This will run forever
    except KeyboardInterrupt:
        logger.info("⚠️ WebSocket service stopping...")
    except Exception as e:
        logger.error(f"❌ WebSocket server error: {e}", exc_info=True)
        raise

def start_websocket_server():
    """Start the WebSocket server"""
    logger.info("Starting WebSocket server...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ WebSocket service stopping...")
        logger.info("WebSocket service stopped")
    except Exception as e:
        logger.error(f"WebSocket server failed to start: {str(e)}")
        logger.info("WebSocket service stopped")

if __name__ == "__main__":
    start_websocket_server()