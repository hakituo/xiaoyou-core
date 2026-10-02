import os
from typing import Any, Dict


def resolve_llm_backend(gpu_config: Dict[str, Any], logger: Any) -> str:
    backend = gpu_config.get("backend")
    if backend not in ("cpp", "python"):
        backend = "cpp"
    allow_cpp_llm_worker = str(
        os.getenv("XIAOYOU_ALLOW_CPP_LLM_WORKER", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not allow_cpp_llm_worker:
        try:
            from config.integrated_config import get_settings

            allow_cpp_llm_worker = bool(
                getattr(get_settings().scheduler, "allow_cpp_llm_worker", False)
            )
        except Exception:
            allow_cpp_llm_worker = False
    if backend == "cpp" and not allow_cpp_llm_worker:
        logger.warning("C++ LLM Worker 当前不稳定，已自动切换到 Python 后端以避免进程崩溃。")
        backend = "python"
    return backend


def apply_biological_config(bio_system: Any, scheduler_py: Any, logger: Any) -> None:
    try:
        from config.integrated_config import get_settings

        settings = get_settings().scheduler
        if bio_system and hasattr(scheduler_py, "BiologicalConfig"):
            cfg = scheduler_py.BiologicalConfig()
            cfg.decay_rate = float(
                getattr(settings, "bio_decay_rate", cfg.decay_rate) or cfg.decay_rate
            )
            cfg.energy_awake_decay = float(
                getattr(settings, "bio_energy_awake_decay", cfg.energy_awake_decay)
                or cfg.energy_awake_decay
            )
            cfg.energy_sleep_recover = float(
                getattr(settings, "bio_energy_sleep_recover", cfg.energy_sleep_recover)
                or cfg.energy_sleep_recover
            )
            cfg.sleep_debt_awake_gain = float(
                getattr(
                    settings, "bio_sleep_debt_awake_gain", cfg.sleep_debt_awake_gain
                )
                or cfg.sleep_debt_awake_gain
            )
            cfg.sleep_debt_sleep_recover = float(
                getattr(
                    settings,
                    "bio_sleep_debt_sleep_recover",
                    cfg.sleep_debt_sleep_recover,
                )
                or cfg.sleep_debt_sleep_recover
            )
            bio_system.setConfig(cfg)
    except Exception as e:
        logger.warning(f"Failed to apply biological config: {e}")
