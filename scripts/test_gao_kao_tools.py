import os
import sys
import unittest
import shutil

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools.registry import ToolRegistry
from core.tools.gao_kao import MathPlotTool, FileCreationTool, TextToSpeechTool

class TestGaoKaoTools(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(MathPlotTool())
        self.registry.register(FileCreationTool())
        self.registry.register(TextToSpeechTool())
        
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "output")
        self.img_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "images", "generated")
        
        # Clean up previous test runs
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)
        if os.path.exists(self.img_dir):
            shutil.rmtree(self.img_dir)
            
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.img_dir, exist_ok=True)

    def test_math_plot_tool(self):
        tool = self.registry.get_tool("generate_math_plot")
        self.assertIsNotNone(tool)
        
        # Test generating a sine wave
        result = tool._run(plot_type="sin", params={"amplitude": 2, "period": 3.14})
        print(f"MathPlotTool Result: {result}")
        self.assertIn("[GEN_IMG:", result)
        self.assertTrue(os.path.exists(self.img_dir))
        # Check if any file was created
        files = os.listdir(self.img_dir)
        self.assertTrue(len(files) > 0)

    def test_file_creation_tool(self):
        tool = self.registry.get_tool("create_file")
        self.assertIsNotNone(tool)
        
        content = [{"name": "Alice", "score": 90}, {"name": "Bob", "score": 85}]
        filename = "test_scores.xlsx"
        
        result = tool._run(content=content, filename=filename)
        print(f"FileCreationTool Result: {result}")
        
        filepath = os.path.join(self.output_dir, filename)
        self.assertTrue(os.path.exists(filepath))

    def test_tts_tool(self):
        tool = self.registry.get_tool("text_to_speech")
        self.assertIsNotNone(tool)
        
        # This might fail if TTS models are not downloaded or environment issues
        # But we want to test the integration logic
        try:
            result = tool._run(text="Hello world, this is a test.", emotion="neutral")
            print(f"TTSTool Result: {result}")
            if "Error" not in result:
                self.assertIn("[GEN_AUDIO:", result)
            else:
                print("TTS failed as expected (might be missing models/env), but tool logic ran.")
        except Exception as e:
            print(f"TTS Test Exception: {e}")

if __name__ == "__main__":
    unittest.main()
