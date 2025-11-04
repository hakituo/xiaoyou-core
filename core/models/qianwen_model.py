import os
from dotenv import load_dotenv
import dashscope
from dashscope import Generation

# Get project root directory
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Load .env file using absolute path
env_path = os.path.join(base_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"✅ Successfully loaded .env file: {env_path}")
else:
    print(f"❌ Cannot find .env file: {env_path}")

class QianwenModel:
    """
    Tongyi Qianwen Model calling class.
    (The generate method is synchronous and blocking)
    """
    def __init__(self, model_name="qwen-max"):
        self.model_name = model_name
        # Use correct environment variable name QIANWEN_API_KEY
        api_key = os.getenv("QIANWEN_API_KEY")
        if not api_key:
            print("⚠️ Warning: Environment variable QIANWEN_API_KEY is not set or empty!")
        else:
            print("✅ Successfully read API Key")
            # Set dashscope API key, required for calling Tongyi Qianwen API
            dashscope.api_key = api_key
        self.api_key = api_key
        # Default AI personality: Xiaoyou - a friendly AI assistant
        self.system_prompt = {
            "role": "system",
            "content": "You are Xiaoyou, a friendly, intelligent, and patient AI assistant. You always answer users' questions in natural, friendly language, help users solve problems, and maintain a positive and optimistic attitude."
        }

    def set_personality(self, personality_prompt: str):
        """
        Set AI personality/role prompt
        
        Args:
            personality_prompt: Prompt text describing AI's role
        """
        self.system_prompt = {
            "role": "system",
            "content": personality_prompt
        }
        print(f"✅ AI personality updated: {personality_prompt[:50]}...")
    
    def generate(self, messages: list) -> str:
        """
        Call Tongyi Qianwen API to generate response.
        (Synchronous blocking function)
        """
        if not self.api_key:
             return f"Simulated response ({self.model_name}): API Key missing, please check .env file."

        try:
            # Add system prompt to the beginning of messages list
            full_messages = [self.system_prompt] + messages
            
            response = Generation.call(
                model=self.model_name,
                messages=full_messages,
                result_format='message'
            )
            
            if response.status_code == 200 and response.output and response.output.choices:
                return response.output.choices[0].message.content
            else:
                return f"API call failed ({response.status_code}): {response.message}"

        except Exception as e:
            return f"Simulated response ({self.model_name}): Exception occurred during LLM call: {e}"