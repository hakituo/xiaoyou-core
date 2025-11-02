from flask import Flask, render_template, send_from_directory, request, jsonify
import os
import sys
import gc
import logging
import time
from datetime import timedelta
from functools import wraps
from collections import deque
from threading import Thread, Lock

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("flask_app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 确保 Flask 知道你的 templates 文件夹就在旁边
app = Flask(__name__, static_folder='static') 

# 配置静态文件缓存时间
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=1)

# 性能优化配置
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制请求体大小为16MB
app.config['TEMPLATES_AUTO_RELOAD'] = False  # 禁用模板自动重载

# 全局变量用于速率限制
rate_limit_data = deque(maxlen=100)  # 存储最近的请求时间
rate_limit_lock = Lock()
RATE_LIMIT_WINDOW = 60  # 60秒
RATE_LIMIT_MAX_REQUESTS = 60  # 每分钟最多60个请求

# 内存监控
last_gc_time = time.time()
GC_INTERVAL = 300  # 5分钟进行一次垃圾回收

# 优化的缓存装饰器
class SimpleCache:
    def __init__(self, timeout=3600):
        self.cache = {}
        self.timeout = timeout
        self.lock = Lock()
    
    def __call__(self, f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 为了低配置电脑，使用简单但高效的缓存键生成
            key = f.__name__ + str(args[:2]) + str(tuple(sorted(kwargs.items())[:2]))
            
            with self.lock:
                current_time = time.time()
                # 检查缓存是否存在且未过期
                if key in self.cache:
                    value, timestamp = self.cache[key]
                    if current_time - timestamp < self.timeout:
                        return value
            
            # 缓存未命中，执行函数
            result = f(*args, **kwargs)
            
            # 仅缓存成功结果且结果不太大
            if result and sys.getsizeof(result) < 1024 * 1024:  # 小于1MB
                with self.lock:
                    self.cache[key] = (result, time.time())
                    # 定期清理过期缓存
                    if len(self.cache) > 100:  # 限制缓存大小
                        self._cleanup()
            
            return result
        
        def _cleanup(self):
            current_time = time.time()
            self.cache = {k: v for k, v in self.cache.items() if current_time - v[1] < self.timeout}
        
        decorated_function._cleanup = lambda: _cleanup(self)
        return decorated_function

# 创建缓存实例
simple_cache = SimpleCache(timeout=3600)

# 内存优化中间件
def memory_optimization_middleware():
    @app.before_request
    def before_request():
        global last_gc_time
        current_time = time.time()
        
        # 定期触发垃圾回收
        if current_time - last_gc_time > GC_INTERVAL:
            try:
                gc.collect()
                last_gc_time = current_time
                logger.info("垃圾回收完成")
            except Exception as e:
                logger.error(f"垃圾回收失败: {e}")
        
        # 内存使用监控
        if hasattr(sys, 'getsizeof'):
            # 这里可以添加更复杂的内存监控
            pass
    
    return before_request

# 注册内存优化中间件
memory_optimization_middleware()

# 速率限制装饰器
def rate_limit():
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_time = time.time()
            
            with rate_limit_lock:
                # 移除过期的请求记录
                while rate_limit_data and current_time - rate_limit_data[0] > RATE_LIMIT_WINDOW:
                    rate_limit_data.popleft()
                
                # 检查是否超过速率限制
                if len(rate_limit_data) >= RATE_LIMIT_MAX_REQUESTS:
                    logger.warning(f"速率限制触发: {request.remote_addr}")
                    return jsonify({"error": "请求过于频繁，请稍后再试"}), 429
                
                # 记录新请求
                rate_limit_data.append(current_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# 错误处理
@app.errorhandler(404)
def page_not_found(e):
    logger.warning(f"404错误: {request.path} - {request.remote_addr}")
    return render_template("error.html", error="页面未找到"), 404

@app.errorhandler(413)
def request_entity_too_large(e):
    logger.warning(f"请求体过大: {request.path} - {request.remote_addr}")
    return jsonify({"error": "请求体过大"}), 413

@app.errorhandler(Exception)
def internal_server_error(e):
    logger.error(f"服务器内部错误: {str(e)}", exc_info=True)
    return render_template("error.html", error="服务器内部错误"), 500

@app.route("/")
@rate_limit()
def index():
    # 渲染新的终极科幻界面
    logger.info("使用模板: ultimate_xiaoyou_optimized.html")
    return render_template('ultimate_xiaoyou_optimized.html')

# 添加一个路由来提供 voice 目录中的静态音频文件
@app.route('/voice/<path:filename>')
@rate_limit()
def serve_voice(filename):
    voice_dir = os.path.join(app.root_path, 'voice')
    
    # 安全检查：防止目录遍历攻击
    if '..' in filename or '\\' in filename:
        logger.warning(f"安全警告：尝试访问非法路径: {filename} - {request.remote_addr}")
        return jsonify({"error": "访问被拒绝"}), 403
    
    try:
        response = send_from_directory(voice_dir, filename)
        # 额外的缓存控制
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        logger.error(f"提供音频文件失败: {filename} - {str(e)}")
        return jsonify({"error": "文件未找到"}), 404

# 健康检查端点
@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0.0"
    })

# 资源清理函数
def cleanup_resources():
    # 清理缓存
    for func in app.view_functions.values():
        if hasattr(func, '_cleanup'):
            try:
                func._cleanup()
            except Exception as e:
                logger.error(f"清理函数缓存失败: {e}")
    
    # 强制垃圾回收
    try:
        gc.collect()
    except Exception as e:
        logger.error(f"清理资源时垃圾回收失败: {e}")

if __name__ == "__main__":
    try:
        # 针对低配置电脑的最终优化配置
        app.run(
            host="0.0.0.0", 
            port=5000, 
            debug=False, 
            threaded=True,
            processes=1,  # 单进程模式，减少内存占用
            use_reloader=False,  # 禁用重载器，减少资源使用
            load_dotenv=False,  # 禁用dotenv加载，提高启动速度
            passthrough_errors=False  # 捕获所有错误
        )
    except KeyboardInterrupt:
        logger.info("Flask应用程序被用户中断")
        cleanup_resources()
    except Exception as e:
        logger.critical(f"Flask应用程序启动失败: {e}", exc_info=True)
        cleanup_resources()
        sys.exit(1)