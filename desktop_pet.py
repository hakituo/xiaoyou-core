#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 桌宠 UI 应用程序 (PyQt Lottie)
import os
import sys
import logging
import asyncio
import websockets
import json
import random
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='history/desktop_pet.log'
)
logger = logging.getLogger(__name__)

# 尝试导入PyQt6
HAS_PYQT6 = False
try:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QLineEdit, QTextEdit
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
    from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap
    HAS_PYQT6 = True
    logger.info("PyQt6导入成功")
    
    # 尝试导入pygame和lottie
    try:
        import pygame  # 用于音频播放
        HAS_PYGAME = True
    except ImportError:
        logger.warning("pygame不可用，音频播放将被禁用")
        HAS_PYGAME = False
        
    try:
        import lottie  # 用于Lottie动画渲染
        HAS_LOTTIE = True
    except ImportError:
        logger.warning("lottie不可用，动画渲染将受限制")
        HAS_LOTTIE = False
except ImportError:
    logger.warning("PyQt6不可用，将使用命令行界面")

class AudioPlayer:
    """音频播放器"""
    def __init__(self):
        if HAS_PYQT6 and HAS_PYGAME:
            pygame.mixer.init()
            logger.info("音频播放器初始化成功")
        else:
            logger.warning("音频播放器未初始化（PyQt6或pygame不可用）")
        self.currently_playing = None
    
    def play_audio(self, audio_path):
        """播放音频文件"""
        try:
            if not HAS_PYQT6 or not HAS_PYGAME:
                logger.warning("音频播放功能未启用")
                return
                
            if os.path.exists(audio_path):
                # 停止当前播放的音频
                if self.currently_playing and pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                
                pygame.mixer.music.load(audio_path)
                pygame.mixer.music.play()
                self.currently_playing = audio_path
                logger.info(f"播放音频: {audio_path}")
            else:
                logger.error(f"音频文件不存在: {audio_path}")
        except Exception as e:
            logger.error(f"音频播放失败: {str(e)}")
    
    def stop_audio(self):
        """停止音频播放"""
        if HAS_PYQT6 and HAS_PYGAME:
            pygame.mixer.music.stop()
        self.currently_playing = None

# 只在PyQt6可用时定义PyQt6相关的类
if HAS_PYQT6:
    class WebSocketClient(QThread):
        """WebSocket客户端线程"""
        message_received = pyqtSignal(str)
        connected = pyqtSignal()
        disconnected = pyqtSignal()
        error = pyqtSignal(str)
        
        def __init__(self, uri="ws://localhost:8765"):
            super().__init__()
            self.uri = uri
            self.websocket = None
            self.running = False
        
        def run(self):
            """启动WebSocket连接"""
            self.running = True
            asyncio.run(self._connect())
        
        async def _connect(self):
            """异步连接WebSocket"""
            while self.running:
                try:
                    async with websockets.connect(self.uri) as websocket:
                        self.websocket = websocket
                        self.connected.emit()
                        logger.info(f"WebSocket连接成功: {self.uri}")
                        
                        # 发送初始连接消息
                        await websocket.send(json.dumps({
                            "type": "connect",
                            "client_type": "desktop_pet"
                        }))
                        
                        # 接收消息循环
                        while self.running:
                            message = await websocket.recv()
                            self.message_received.emit(message)
                            
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"WebSocket错误: {error_msg}")
                    self.error.emit(error_msg)
                    self.disconnected.emit()
                    # 重连延迟
                    await asyncio.sleep(5)
        
        async def send_message(self, message):
            """发送消息到WebSocket服务器"""
            if self.websocket and self.websocket.open:
                await self.websocket.send(message)
                return True
            return False
        
        def send_sync(self, message):
            """同步发送消息"""
            if self.running:
                asyncio.run(self.send_message(message))
        
        def stop(self):
            """停止WebSocket连接"""
            self.running = False
            self.wait()

if HAS_PYQT6:
    class LottieAnimationWidget(QWidget):
        """Lottie动画控件"""
        def __init__(self, parent=None):
            super().__init__(parent)
            self.animation_path = "static/lottie/pet_idle.json"
            self.current_animation = "idle"
            self.setup_ui()
        
        def setup_ui(self):
            """设置UI"""
            self.setMinimumSize(200, 200)
            self.setStyleSheet("background-color: transparent;")
        
        def load_animation(self, animation_name):
            """加载动画"""
            animation_map = {
                "idle": "static/lottie/pet_idle.json",
                "happy": "static/lottie/pet_happy.json",
                "thinking": "static/lottie/pet_thinking.json",
                "sleeping": "static/lottie/pet_sleeping.json"
            }
            
            if animation_name in animation_map:
                self.animation_path = animation_map[animation_name]
                self.current_animation = animation_name
                logger.info(f"加载动画: {animation_name}")
                self.update()
        
        def paintEvent(self, event):
            """绘制事件"""
            # 这里会在实际使用时实现Lottie动画渲染
            pass
    
    class DesktopPetWindow(QMainWindow):
        """桌宠主窗口"""
        def __init__(self):
            super().__init__()
            self.audio_player = AudioPlayer()
            self.websocket_client = WebSocketClient()
            self.setup_ui()
            self.setup_signals()
            
        def setup_ui(self):
            """设置UI"""
            # 设置窗口属性
            self.setWindowTitle("小悠桌宠")
            self.setGeometry(100, 100, 300, 400)
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            
            # 主布局
            central_widget = QWidget()
            central_widget.setStyleSheet("background-color: rgba(255, 255, 255, 200); border-radius: 10px;")
            self.setCentralWidget(central_widget)
            
            main_layout = QVBoxLayout(central_widget)
            
            # 动画控件
            self.animation_widget = LottieAnimationWidget()
            main_layout.addWidget(self.animation_widget)
            
            # 状态标签
            self.status_label = QLabel("正在连接...")
            self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            main_layout.addWidget(self.status_label)
            
            # 消息显示
            self.message_text = QTextEdit()
            self.message_text.setReadOnly(True)
            self.message_text.setMaximumHeight(100)
            main_layout.addWidget(self.message_text)
            
            # 输入区域
            input_layout = QVBoxLayout()
            self.input_line = QLineEdit()
            self.input_line.setPlaceholderText("输入消息...")
            send_button = QPushButton("发送")
            send_button.clicked.connect(self.send_message)
            
            input_layout.addWidget(self.input_line)
            input_layout.addWidget(send_button)
            main_layout.addLayout(input_layout)
        
        def setup_signals(self):
            """设置信号连接"""
            self.websocket_client.connected.connect(self.on_connected)
            self.websocket_client.disconnected.connect(self.on_disconnected)
            self.websocket_client.message_received.connect(self.on_message_received)
            self.websocket_client.error.connect(self.on_error)
            
            # 启动WebSocket客户端
            self.websocket_client.start()
        
        def on_connected(self):
            """连接成功回调"""
            self.status_label.setText("已连接")
            self.animation_widget.load_animation("happy")
        
        def on_disconnected(self):
            """断开连接回调"""
            self.status_label.setText("连接断开")
            self.animation_widget.load_animation("idle")
        
        def on_error(self, error_msg):
            """错误回调"""
            self.status_label.setText(f"错误: {error_msg}")
        
        def on_message_received(self, message):
            """接收消息回调"""
            try:
                data = json.loads(message)
                
                # 处理不同类型的消息
                if data.get("type") == "message":
                    content = data.get("content", "")
                    self.message_text.append(f"小悠: {content}")
                    self.animation_widget.load_animation("happy")
                    
                    # 如果有音频，播放
                    if "audio_path" in data:
                        self.audio_player.play_audio(data["audio_path"])
                
                elif data.get("type") == "typing":
                    self.animation_widget.load_animation("thinking")
            except Exception as e:
                logger.error(f"处理消息失败: {str(e)}")
        
        def send_message(self):
            """发送消息"""
            text = self.input_line.text().strip()
            if text:
                message = json.dumps({
                    "type": "message",
                    "content": text
                })
                self.websocket_client.send_sync(message)
                self.message_text.append(f"我: {text}")
                self.input_line.clear()
        
        def mousePressEvent(self, event):
            """鼠标按下事件，用于拖动窗口"""
            if event.button() == Qt.MouseButton.LeftButton:
                self.drag_position = event.globalPosition() - self.frameGeometry().topLeft()
                event.accept()
        
        def mouseMoveEvent(self, event):
            """鼠标移动事件，用于拖动窗口"""
            if event.buttons() == Qt.MouseButton.LeftButton:
                self.move((event.globalPosition() - self.drag_position).toPoint())
                event.accept()
        
        def closeEvent(self, event):
            """关闭事件"""
            self.websocket_client.stop()
            self.audio_player.stop_audio()
            event.accept()

    def main():
        """主函数"""
        # 确保Lottie动画目录存在
        os.makedirs("static/lottie", exist_ok=True)
        
        # 创建示例Lottie文件（在实际应用中应该由用户提供）
        if not os.path.exists("static/lottie/pet_idle.json"):
            with open("static/lottie/pet_idle.json", "w") as f:
                f.write('{"v":"5.7.4","fr":30,"ip":0,"op":90,"w":200,"h":200,"nm":"Pet_Idle","ddd":0,"assets":[],"layers":[]}')
        
        app = QApplication(sys.argv)
        window = DesktopPetWindow()
        window.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    if HAS_PYQT6:
        # 如果在PyQt6条件块中定义了main函数，需要调用那个版本
        if 'main' in locals():
            locals()['main']()
        else:
            # 否则使用通用版本
            # 确保Lottie动画目录存在
            os.makedirs("static/lottie", exist_ok=True)
            
            # 创建示例Lottie文件（在实际应用中应该由用户提供）
            if not os.path.exists("static/lottie/pet_idle.json"):
                with open("static/lottie/pet_idle.json", "w") as f:
                    f.write('{"v":"5.7.4","fr":30,"ip":0,"op":90,"w":200,"h":200,"nm":"Pet_Idle","ddd":0,"assets":[],"layers":[]}')
            
            app = QApplication(sys.argv)
            window = DesktopPetWindow()
            window.show()
            sys.exit(app.exec())
    else:
        # 降级到命令行界面
        print("\n=========================================")
        print("🔔 小悠 AI 桌宠 (命令行模式)")
        print("=========================================")
        print("PyQt6未安装，无法启动图形界面。")
        print("\n✅ 核心WebSocket服务已成功启动")
        print("\n📝 您可以：")
        print("1. 使用WebSocket客户端连接到核心服务")
        print("2. 安装PyQt6来启动图形界面: pip install PyQt6")
        print("\n💡 提示：核心功能已经可用，只是缺少图形界面。")
        print("=========================================\n")
        
        # 保持程序运行一段时间
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 小悠命令行模式已退出")
            sys.exit(0)