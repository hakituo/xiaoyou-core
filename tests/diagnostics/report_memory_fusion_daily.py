import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from memory.weighted_memory_manager import get_weighted_memory_manager  # noqa: E402


def _is_today(ts: float) -> bool:
    if ts <= 0:
        return False
    return time.strftime("%Y-%m-%d", time.localtime(ts)) == time.strftime("%Y-%m-%d")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=str, default="default")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    mm = get_weighted_memory_manager(args.user_id)
    try:
        memories: List[Dict[str, Any]] = mm.get_weighted_memories(limit=max(1, int(args.limit)))
        fused = 0
        overridden = 0
        supplemented = 0
        rejected = 0
        rolled_back = 0
        uncategorized = 0
        today_total = 0
        for m in memories:
            metadata = m.get("metadata") or {}
            if not isinstance(metadata, dict):
                continue
            analysis_meta = metadata.get("analysis_meta") or {}
            if not isinstance(analysis_meta, dict):
                continue
            fusion = analysis_meta.get("fusion") or {}
            if not isinstance(fusion, dict):
                if str(m.get("category") or "uncategorized") == "uncategorized":
                    uncategorized += 1
                continue
            updated_at = float(fusion.get("updated_at") or 0.0)
            if not _is_today(updated_at):
                continue
            today_total += 1
            fused += 1
            action = str(fusion.get("action") or "")
            if action == "override":
                overridden += 1
            elif action == "supplement":
                supplemented += 1
            elif action == "rollback":
                rolled_back += 1
            else:
                rejected += 1
            if str(m.get("category") or "uncategorized") == "uncategorized":
                uncategorized += 1

        denom = float(max(1, today_total))
        report = {
            "date": time.strftime("%Y-%m-%d"),
            "user_id": args.user_id,
            "today_total": today_total,
            "fused": fused,
            "override_rate": round(overridden / denom, 4),
            "supplement_rate": round(supplemented / denom, 4),
            "reject_rate": round(rejected / denom, 4),
            "rollback_rate": round(rolled_back / denom, 4),
            "uncategorized_rate": round(uncategorized / denom, 4),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    finally:
        mm.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
