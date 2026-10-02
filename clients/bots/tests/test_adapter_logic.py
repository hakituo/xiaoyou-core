import sys
import os
import unittest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from clients.bots.qq.intent import SemanticIntentRecognizer
from clients.bots.utils.status_renderer import (
    generate_status_image,
    generate_model_list_image,
    generate_help_image
)

class TestQQAdapterLogic(unittest.TestCase):
    def test_semantic_recognizer(self):
        recognizer = SemanticIntentRecognizer()

        self.assertTrue(len(getattr(recognizer, "patterns", []) or []) > 0)

        def _intent(text):
            m = recognizer.match(text)
            return m.get("intent") if isinstance(m, dict) else None
        
        # Test Clear Memory
        self.assertEqual(_intent("清除记忆"), "CLEAR_MEMORY")
        self.assertEqual(_intent("清空聊天记录"), "CLEAR_MEMORY")
        self.assertEqual(_intent("忘掉我们的历史"), "CLEAR_MEMORY")
        
        # Test Show Status
        self.assertEqual(_intent("查看状态"), "SHOW_STATUS")
        self.assertEqual(_intent("看看系统负载"), "SHOW_STATUS")
        self.assertEqual(_intent("显示状态"), "SHOW_STATUS")
        
        # Test Help
        self.assertEqual(_intent("帮助"), "SHOW_HELP")
        self.assertEqual(_intent("指令列表"), "SHOW_HELP")

        # Test Module Docs
        self.assertEqual(_intent("模块介绍"), "SHOW_MODULE_DOC")
        self.assertEqual(_intent("功能说明"), "SHOW_MODULE_DOC")
        self.assertEqual(_intent("readme"), "SHOW_MODULE_DOC")
        
        # Test Models
        self.assertEqual(_intent("查看模型"), "LIST_MODELS")
        self.assertEqual(_intent("列出模型"), "LIST_MODELS")
        
        # Test Switch Hint
        self.assertEqual(_intent("切换模型"), "SWITCH_MODEL")
        self.assertEqual(_intent("换个LLM"), "SWITCH_MODEL_HINT")

        # Test Mode Toggles
        self.assertEqual(_intent("开启学习模式"), "TOGGLE_STUDY_MODE")
        self.assertEqual(_intent("关闭私密模式"), "TOGGLE_PRIVACY_MODE")
        
        # Test No Match
        self.assertIsNone(_intent("你好啊"))
        self.assertIsNone(_intent("今天天气怎么样"))

    def test_renderer_generation(self):
        # Ensure image generation doesn't crash
        # Status
        path = generate_status_image(20.5, 60.2, "TestModel", "TestPersona", True, {"joy": 0.8})
        self.assertTrue(os.path.exists(path))
        os.remove(path)
        
        # Models
        llm = [{"name": "Model A", "provider": "local"}, {"name": "Model B", "provider": "cloud"}]
        img = [{"name": "SD XL", "path": "sd_xl.safetensors"}]
        path = generate_model_list_image(llm, img, "Model A", "SD XL")
        self.assertTrue(os.path.exists(path))
        os.remove(path)
        
        # Help
        cmds = [{"command": "/test", "description": "test cmd"}]
        path = generate_help_image(cmds)
        self.assertTrue(os.path.exists(path))
        os.remove(path)

if __name__ == '__main__':
    unittest.main()
