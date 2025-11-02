import os
from dotenv import load_dotenv
import dashscope
from dashscope import Generation

# 获取项目根目录
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 使用绝对路径加载 .env 文件
env_path = os.path.join(base_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"✅ 成功加载 .env 文件: {env_path}")
else:
    print(f"❌ 找不到 .env 文件: {env_path}")

class QianwenModel:
    """
    通义千问模型调用类。
    (generate 方法是同步阻塞的)
    """
    def __init__(self, model_name="qwen-max"):
        self.model_name = model_name
        # 使用正确的环境变量名 QIANWEN_API_KEY
        api_key = os.getenv("QIANWEN_API_KEY")
        if not api_key:
            print("⚠️ 警告：环境变量 QIANWEN_API_KEY 未设置或为空！")
        else:
            print("✅ 成功读取 API Key")
            # 设置 dashscope 的 API key，这是调用通义千问 API 所必需的
            dashscope.api_key = api_key
        self.api_key = api_key
        # 默认AI人设：小悠 - 一个友好的AI助手
        self.system_prompt = {
            "role": "system",
            "content": "你是小悠，一个友好、聪明、有耐心的AI助手。你总是以自然、亲切的语言回答用户的问题，帮助用户解决问题，并保持积极乐观的态度。"
        }

    def set_personality(self, personality_prompt: str):
        """
        设置AI的人设/角色提示
        
        Args:
            personality_prompt: 描述AI角色的提示文本
        """
        self.system_prompt = {
            "role": "system",
            "content": personality_prompt
        }
        print(f"✅ AI人设已更新: {personality_prompt[:50]}...")
    
    def generate(self, messages: list) -> str:
        """
        调用通义千问 API 生成回复。
        (同步阻塞函数)
        """
        if not self.api_key:
             return f"模拟回答 ({self.model_name}): API Key缺失，请检查.env文件。"

        try:
            # 将系统提示添加到消息列表的开头
            full_messages = [self.system_prompt] + messages
            
            response = Generation.call(
                model=self.model_name,
                messages=full_messages,
                result_format='message'
            )
            
            if response.status_code == 200 and response.output and response.output.choices:
                return response.output.choices[0].message.content
            else:
                return f"API调用失败 ({response.status_code}): {response.message}"

        except Exception as e:
            return f"模拟回答 ({self.model_name}): LLM调用发生异常：{e}"