import time
from typing import Any, Dict, Optional


def record_llm_inference_stats(
    engine: Any,
    backend: str,
    generated_tokens: int,
    inference_time_s: float,
    **extra,
) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "backend": backend,
        "generated_tokens": int(generated_tokens or 0),
        "inference_time_s": float(inference_time_s or 0.0),
        "timestamp": time.time(),
    }
    for key, value in extra.items():
        stats[key] = value
    engine._last_llm_stats = stats
    return stats


def get_last_llm_stats(engine: Any) -> Optional[Dict[str, Any]]:
    return getattr(engine, "_last_llm_stats", None)
