import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock
from core.services.active_care.core.service import ActiveCareService

@pytest.mark.asyncio
class TestActiveCareServiceIntegration:
    async def test_startup_check(self):
        # Mock settings
        mock_settings = MagicMock()
        mock_settings.life_simulation.active_care_enabled = True
        mock_settings.life_simulation.active_care_startup_check = True
        
        service = ActiveCareService()
        service.settings = mock_settings
        
        # Mock dependencies with correct paths
        # Note: ActiveCareService imports these inside methods, so we patch the source
        with patch("core.services.life_simulation.service.get_life_simulation_service") as mock_life, \
             patch("core.managers.preference_manager.get_preference_manager") as mock_pref, \
             patch("core.llm.get_llm_module") as mock_llm:
            
            mock_life.return_value.last_interaction_time = time.time() - 3600
            mock_pref.return_value.is_active_care_enabled.return_value = True
            
            # Mock internal methods to avoid actual LLM calls
            service._trigger_message = AsyncMock()
            
            # Run startup check
            await service.check_active_care(is_startup=True)
            
            # Verify if startup trigger was called
            service._trigger_message.assert_called_with("startup", "[STARTUP_TRIGGER]", device_context=None)

    async def test_daily_limit(self):
        service = ActiveCareService()
        service.settings = MagicMock()
        service.settings.life_simulation.active_care_daily_limit = 5
        
        # Mock file reading to return a count >= limit
        with patch.object(service, '_read_json_file', new_callable=AsyncMock) as mock_read:
            # Mock proactive_count.json returning 5
            mock_read.side_effect = [{"2026-01-19": 5}, {}] 
            
            with patch("core.services.active_care.service.get_current_time") as mock_time:
                mock_time.return_value.strftime.return_value = "2026-01-19"
                
                # Mock dependencies
                with patch("core.managers.preference_manager.get_preference_manager") as mock_pref:
                    mock_pref.return_value.is_active_care_enabled.return_value = True
                    
                    # Run check
                    await service.check_active_care(is_startup=False)
                    
                    # Verify next check is delayed
                    assert service._next_llm_decision_ts > time.time()

if __name__ == "__main__":
    asyncio.run(TestActiveCareServiceIntegration().test_startup_check())
