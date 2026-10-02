import sys
import asyncio
import importlib
import unittest
import time
import os
from unittest.mock import MagicMock, patch, AsyncMock

# Mock scheduler_py before importing engine
mock_scheduler_core = MagicMock()
sys.modules["scheduler_py"] = mock_scheduler_core
sys.modules["xiaoyou_scheduler_core"] = mock_scheduler_core 

CPPSchedulerEngine = importlib.import_module(
    "core.services.scheduler.cpp_scheduler_engine"
).CPPSchedulerEngine
ResourceManager = importlib.import_module("core.resource_manager").ResourceManager
image_manager_module = importlib.import_module("core.image.image_manager")
ImageManager = image_manager_module.ImageManager
ImageGenerationConfig = image_manager_module.ImageGenerationConfig

class TestConcurrentGeneration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Setup mocks
        self.mock_scheduler = MagicMock()
        mock_scheduler_core.ResourceIsolationScheduler.return_value = self.mock_scheduler
        
        # Mock Settings
        self.settings_patcher = patch("config.integrated_config.get_settings")
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.model.image_output_dir = "test_output"
        self.mock_settings.model.default_image_model = "sd1.5"
        self.mock_settings.model.image_provider = "forge" # Ensure Forge is used
        
        # Initialize Engine
        CPPSchedulerEngine._instance = None
        self.engine = CPPSchedulerEngine()
        self.engine.enabled = True
        self.engine.scheduler = self.mock_scheduler
        
        # Initialize Resource Manager with Engine
        self.rm = ResourceManager()
        self.rm.scheduler_engine = self.engine
        
        # Initialize Image Manager
        with patch("core.image.image_manager.ForgeClient") as MockForge:
            self.mock_forge = MockForge.return_value
            # Default behavior
            self.mock_forge.generate_images.return_value = b"fake_image_data"
            self.image_manager = ImageManager()
            await self.image_manager.initialize()
            
        # Patch Global Accessors
        self.rm_patcher = patch("core.resource_manager.get_resource_manager", return_value=self.rm)
        self.rm_patcher.start()
        
        self.eng_patcher = patch("core.services.scheduler.cpp_scheduler_engine.get_scheduler_engine", return_value=self.engine)
        self.eng_patcher.start()
        
        # Patch get_global_resource_manager for ImageManager (it uses async accessor sometimes)
        self.grm_patcher = patch("core.resource_manager.get_global_resource_manager", new_callable=AsyncMock)
        self.mock_grm = self.grm_patcher.start()
        self.mock_grm.return_value = self.rm

    async def asyncTearDown(self):
        self.settings_patcher.stop()
        self.rm_patcher.stop()
        self.eng_patcher.stop()
        self.grm_patcher.stop()

    async def test_llm_gpu_to_cpu_handover(self):
        """
        Test that starting image generation forces LLM to release GPU (move to CPU/unload).
        """
        print("\n[Test] Starting LLM GPU -> CPU Handover Test")
        
        # 1. Simulate LLM running on GPU
        llm_mock = MagicMock()
        llm_mock.model_id = "llm_engine"
        llm_mock.device = "GPU"
        llm_mock.is_loaded = True
        llm_mock.instance = self.engine # Link the engine as the instance
        llm_mock.offload_func = AsyncMock() # Must be present
        
        self.rm._models["llm_engine"] = llm_mock
        
        # Mock the engine's release method to verify it's called
        # Note: We are mocking the method on the INSTANCE
        self.engine.release_llm_vram_for_image_gen = AsyncMock(return_value=True)
        self.engine.restore_llm_to_gpu = AsyncMock(return_value=True)
        
        # 2. Trigger Image Generation
        print("[Test] Triggering Image Generation (Simulating 50s heavy load)...")
        config = ImageGenerationConfig(
            width=512, height=512, num_inference_steps=20,
            additional_params={"num_images": 2, "timeout": 50.0}
        )
        
        # We simulate the image generation taking some time
        # This MUST be a synchronous function if run_in_executor is used
        def delayed_generate(*args, **kwargs):
            print("[MockForge] Generating images... (Simulating delay)")
            time.sleep(0.5) # Shorten for test speed, use sync sleep
            return [b"image1", b"image2"]
            
        self.mock_forge.generate_images.side_effect = delayed_generate
        
        # Run generate_image
        result = await self.image_manager.generate_image(
            prompt="A test image",
            config=config,
            model_id="sd1.5",
            save_to_file=False 
        )
        
        # 3. Verify Handover
        print("[Test] Verifying Scheduler Interactions")
        
        # Verify LLM release was requested (ImageManager calls it twice: in _begin_image_gen and _generate_with_forge)
        self.assertTrue(self.engine.release_llm_vram_for_image_gen.call_count >= 1)
        print("✅ release_llm_vram_for_image_gen called")
        
        # Verify Image Generation succeeded
        self.assertTrue(result["success"])
        self.assertEqual(len(result["images"]), 2)
        print("✅ Image generation successful with 2 images")
        
        # Verify Restore was requested (ImageManager calls it in _end_image_gen)
        deadline = asyncio.get_running_loop().time() + 5.0
        while (
            self.engine.restore_llm_to_gpu.call_count < 1
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.1)
        self.assertTrue(self.engine.restore_llm_to_gpu.call_count >= 1)
        print(f"✅ restore_llm_to_gpu called {self.engine.restore_llm_to_gpu.call_count} times")

    async def test_restore_gpu_closes_old_cpu_instance_in_demo_mode(self):
        class DummyLlama:
            def __init__(self, name: str):
                self.name = name
                self.closed = False

            def close(self):
                self.closed = True

            def save_state(self):
                return {"name": self.name}

            def load_state(self, _state):
                return

        self.engine._llm_backend = "python"
        self.engine._gpu_config = {"backend": "python", "n_gpu_layers": 0, "force_cpu": True}
        self.engine._python_force_cpu = True
        self.engine._prev_n_gpu_layers = 12

        old_cpu = DummyLlama("cpu")
        self.engine.llm = old_cpu

        def fake_setup(_cfg, return_instance: bool = False):
            inst = DummyLlama("gpu")
            return inst if return_instance else None

        self.engine.request_stop_current_inference = AsyncMock()
        self.engine._setup_python_llm = fake_setup

        with patch.dict(os.environ, {"XIAOYOU_DEMO_MODE": "1"}, clear=False):
            ok = await self.engine.restore_llm_to_gpu()

        self.assertTrue(ok)
        self.assertTrue(old_cpu.closed)
        self.assertIsNot(self.engine.llm, old_cpu)

if __name__ == "__main__":
    unittest.main()
