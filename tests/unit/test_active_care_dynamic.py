import unittest
from unittest.mock import MagicMock

from core.services.active_care.scheduling.scheduler_logic import ActiveCareSchedulerLogic


class TestActiveCareDynamic(unittest.TestCase):
    def setUp(self):
        self.logic = ActiveCareSchedulerLogic()
        self.logic.settings = MagicMock()
        self.logic.settings.life_simulation.active_check_interval = 600
        self.logic.settings.life_simulation.quiet_check_interval = 3600

    def test_randomness_produces_multiple_values(self):
        values = {
            self.logic.calculate_dynamic_interval(
                bio_state={},
                emotion_state=None,
                consecutive_non_responses=0,
                quiet_mode=False,
            )
            for _ in range(30)
        }
        self.assertTrue(len(values) >= 8)

    def test_quiet_mode_is_slower_on_average(self):
        active = [
            self.logic.calculate_dynamic_interval(
                bio_state={},
                emotion_state=None,
                consecutive_non_responses=0,
                quiet_mode=False,
            )
            for _ in range(200)
        ]
        quiet = [
            self.logic.calculate_dynamic_interval(
                bio_state={},
                emotion_state=None,
                consecutive_non_responses=0,
                quiet_mode=True,
            )
            for _ in range(200)
        ]
        self.assertTrue(sum(quiet) / len(quiet) > sum(active) / len(active))


if __name__ == "__main__":
    unittest.main()
