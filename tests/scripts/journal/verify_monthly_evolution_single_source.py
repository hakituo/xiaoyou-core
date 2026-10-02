"""离线验证角色变化只随月度总结保存，工具仍可读取，extra 蒸馏仍被调用。"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.services.journal.models import MonthlySummary  # noqa: E402
from core.services.journal.summary_service import JournalSummaryService  # noqa: E402
from core.tools.diary_tool import ReadMonthlySummaryTool  # noqa: E402


async def verify() -> None:
    date = datetime(2026, 8, 31)
    traits = {
        "new_traits": ["表达更简洁"],
        "new_interests": ["天文"],
        "relationship_change": "更加熟悉",
    }
    payload = {
        "month": "2026-08",
        "summary": "本月一起学习天文。",
        "mood_trend": "平稳",
        "persona_evolution": traits,
    }
    with tempfile.TemporaryDirectory() as folder:
        monthly_dir = Path(folder) / "monthly" / "2026" / "08"

        async def save(summary, target_date):
            assert target_date == date
            monthly_dir.mkdir(parents=True, exist_ok=True)
            (monthly_dir / "summary.json").write_text(
                summary.model_dump_json(), encoding="utf-8"
            )

        def get_monthly_dir(target_date, scope=None):
            assert target_date == date
            assert scope == "aveline"
            return monthly_dir

        storage = SimpleNamespace(
            save_monthly_summary=AsyncMock(side_effect=save),
            get_monthly_summary=AsyncMock(return_value=None),
            _get_monthly_dir=get_monthly_dir,
        )
        service = SimpleNamespace(
            storage=storage, settings=None, _parse_date=lambda _: date
        )
        generator = JournalSummaryService(service)
        generator._collect_daily_summaries = AsyncMock(
            return_value=[SimpleNamespace(date="2026-08-01", summary="一起学习天文。")]
        )
        generator.distill_memory = AsyncMock()
        with patch(
            "core.services.journal.summary_service.call_llm_stream",
            new=AsyncMock(return_value=json.dumps(payload, ensure_ascii=False)),
        ):
            result = await generator.generate_monthly_summary("2026-08-31")
        assert result.persona_evolution == traits
        stored = MonthlySummary.model_validate_json(
            (monthly_dir / "summary.json").read_text(encoding="utf-8")
        )
        assert stored.persona_evolution == traits
        generator.distill_memory.assert_awaited_once_with(result, date)
        with (
            patch("core.services.journal.service.get_journal_service", return_value=service),
            patch.object(
                importlib.import_module("core.utils.data_paths"),
                "_resolve_scope_from_active_persona",
                return_value="aveline",
            ),
        ):
            output = await ReadMonthlySummaryTool()._run(month="2026-08")
        for expected in ["2026-08", payload["summary"], "表达更简洁", "天文", "更加熟悉"]:
            assert expected in output, output

    assert not (ROOT / "core/character/configs/evolution").exists()
    for relative in [
        "core/character/managers/persona_manager.py",
        "core/services/journal/summary_service.py",
    ]:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "update_dynamic_traits" not in source
        assert "get_recent_evolution" not in source
    print("PASS：月度总结保留角色变化、读取工具正常、extra 蒸馏仍调用、独立存储已移除")


if __name__ == "__main__":
    asyncio.run(verify())
