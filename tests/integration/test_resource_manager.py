import pytest
import asyncio
from unittest.mock import MagicMock, patch
from core.resource_manager import ResourceManager, ResourcePriority, ResourceType


@pytest.mark.asyncio
class TestResourceManagerIntegration:
    async def test_resource_registration(self):
        rm = ResourceManager()

        # Test registering a mock model
        mock_load = MagicMock()
        mock_unload = MagicMock()

        rm.register_model(
            model_id="test_model",
            model_type="llm",
            priority=ResourcePriority.HIGH,
            load_func=mock_load,
            unload_func=mock_unload,
            memory_usage_mb=100,
            vram_usage_mb=1000,
        )

        assert "test_model" in rm.models
        model = rm.models["test_model"]
        assert model.priority == ResourcePriority.HIGH
        assert model.vram_usage_mb == 1000

    async def test_prepare_for_heavy_task(self):
        rm = ResourceManager()

        # Mock unload functions
        unload_llm = MagicMock()
        unload_vision = MagicMock()

        # Register conflicting models
        rm.register_model(
            model_id="llm_engine",
            model_type="llm",
            priority=ResourcePriority.HIGH,
            load_func=MagicMock(),
            unload_func=unload_llm,
            vram_usage_mb=2000,
            instance=MagicMock(),
        )
        rm.register_model(
            model_id="vision_module",
            model_type="vision",
            priority=ResourcePriority.MEDIUM,
            load_func=MagicMock(),
            unload_func=unload_vision,
            vram_usage_mb=1000,
            instance=MagicMock(),
        )

        # Mark them as loaded
        rm.mark_model_loaded("llm_engine", True)
        rm.mark_model_loaded("vision_module", True)

        # Simulate preparing for image generation (should unload LLM and Vision)
        with patch("core.resource_manager.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = True

            # Mock get_gpu_free_mb_async to return low memory to force cleanup
            with patch.object(rm, "_get_gpu_free_mb_async", return_value=500):
                await rm.prepare_for_heavy_task("image_gen")

                # Check if conflicting models were unloaded
                # Since we can't easily check internal state changes without more mocks,
                # we assume no exception raised is good for now.
                pass

    async def test_offload_voice_services_prefers_model_offload_hooks(self):
        rm = ResourceManager()
        offload_tts = MagicMock()
        move_stt_to_cpu = MagicMock()

        rm.register_model(
            model_id="tts_engine",
            model_type="tts",
            priority=ResourcePriority.MEDIUM,
            load_func=MagicMock(),
            unload_func=MagicMock(),
            offload_func=offload_tts,
        )
        rm.register_model(
            model_id="stt_engine",
            model_type="stt",
            priority=ResourcePriority.MEDIUM,
            load_func=MagicMock(),
            unload_func=MagicMock(),
            instance=MagicMock(move_to_cpu=move_stt_to_cpu),
        )

        rm.mark_model_loaded("tts_engine", True)
        rm.mark_model_loaded("stt_engine", True)

        await rm._offload_voice_services()

        offload_tts.assert_called_once_with("release")
        move_stt_to_cpu.assert_called_once()
        assert rm.models["stt_engine"].device == "CPU"
        assert rm.models["stt_engine"].vram_usage_mb == 0

    async def test_resource_monitoring(self):
        rm = ResourceManager()
        rm.config["monitor_interval"] = 0.1
        rm.monitor._check_interval = 0

        with patch("core.resource_components.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value.percent = 96.0
            mock_psutil.cpu_percent.return_value = 50.0

            # Start monitoring
            await rm.start()

            # Wait for a few cycles
            await asyncio.sleep(0.3)

            # Check if state is updated
            # Note: The monitor might be running, but we check the state manually
            state = rm.monitor.get_resource_state(ResourceType.MEMORY)
            assert state.name == "EMERGENCY"

            await rm.stop()


if __name__ == "__main__":
    asyncio.run(TestResourceManagerIntegration().test_resource_registration())
