import sys
import asyncio
import logging
import signal
import gc
import os
import subprocess
import time
import multiprocessing

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("startup.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 添加项目路径到系统路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 低配置电脑优化：减少内存占用
gc.set_threshold(5000, 10, 10)  # 调整垃圾回收阈值

# 尝试设置进程优先级（Windows系统）
try:
    if sys.platform == 'win32':
        import win32api
        import win32process
        import win32con
        # 设置为低于正常优先级，但不完全最低，以保证响应性
        win32process.SetPriorityClass(
            win32api.GetCurrentProcess(), 
            win32process.BELOW_NORMAL_PRIORITY_CLASS
        )
        logger.info("进程优先级已设置为低优先级")
except Exception as e:
    logger.warning(f"设置进程优先级失败: {e}")

# 进程管理
global_processes = []

# 启动Flask应用的函数
def start_flask_app():
    try:
        logger.info("正在启动Flask应用...")
        # 直接调用app.py模块
        from app import app
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask应用启动失败: {e}", exc_info=True)
        sys.exit(1)

# 优雅退出处理
def signal_handler(sig, frame):
    logger.info(f"收到信号 {sig}，准备退出...")
    
    # 停止所有子进程
    for proc in global_processes:
        try:
            if proc.is_alive():
                logger.info(f"终止进程: {proc.name}")
                proc.terminate()
                proc.join(timeout=3)  # 等待进程结束，最多3秒
        except Exception as e:
            logger.error(f"终止进程失败: {e}")
    
    # 触发垃圾回收
    gc.collect()
    logger.info("资源已清理，退出程序")
    sys.exit(0)

# 注册信号处理
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# 启动Flask应用的函数
def start_flask_app():
    try:
        logger.info("正在启动Flask应用...")
        # 直接调用app.py模块
        from app import app
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask应用启动失败: {e}", exc_info=True)
        sys.exit(1)

async def main_with_error_handling():
    try:
        # 不再需要主题选择，直接启动服务
        logger.info("准备启动服务...")
        
        # 启动Flask应用进程
        flask_process = multiprocessing.Process(target=start_flask_app, name='FlaskApp')
        flask_process.daemon = True  # 设置为守护进程，主进程结束时自动终止
        flask_process.start()
        global_processes.append(flask_process)
        logger.info("Flask应用进程已启动")
        
        # 等待Flask应用初始化
        time.sleep(2)
        
        # 延迟导入以减少启动时的内存占用
        from ws_server import main
        
        logger.info("正在启动WebSocket服务...")
        # 启动WebSocket服务器
        await main()
    except ImportError as e:
        logger.error(f"服务启动失败: {e}")
    except asyncio.CancelledError:
        logger.info("任务被取消")
    except Exception as e:
        logger.error(f"服务启动失败: {e}", exc_info=True)
    finally:
        # 清理资源
        for proc in global_processes:
            try:
                if proc.is_alive():
                    proc.terminate()
            except:
                pass
        gc.collect()
        logger.info("程序正常退出")

if __name__ == "__main__":
    logger.info("小悠AI系统一键启动中...")
    logger.info("正在准备启动Flask应用和WebSocket服务...")
    
    try:
        # 禁用多进程的fork模式，使用spawn模式更安全
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        # 如果已经设置过则忽略
        pass
    
    try:
        # 使用更高效的事件循环
        if sys.version_info >= (3, 7):
            asyncio.run(main_with_error_handling())
        else:
            # 兼容旧版本Python
            loop = asyncio.get_event_loop()
            try:
                loop.run_until_complete(main_with_error_handling())
            finally:
                try:
                    loop.shutdown_asyncgens()
                    loop.close()
                except:
                    pass
    except KeyboardInterrupt:
        logger.info("用户中断程序")
        # 清理所有进程
        for proc in global_processes:
            try:
                if proc.is_alive():
                    proc.terminate()
            except:
                pass
    except Exception as e:
        logger.critical(f"致命错误: {e}", exc_info=True)
        # 清理所有进程
        for proc in global_processes:
            try:
                if proc.is_alive():
                    proc.terminate()
            except:
                pass
        sys.exit(1)
