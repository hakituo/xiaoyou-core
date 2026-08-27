from typing import Any, Dict, Optional


def _get_sleep_debt(bio_system: Any) -> float:
    try:
        getter = getattr(bio_system, "getSleepDebt", None)
        if callable(getter):
            return float(getter())
        getter = getattr(bio_system, "get_sleep_debt", None)
        if callable(getter):
            return float(getter())
        return float(
            getattr(
                bio_system,
                "sleep_debt",
                getattr(bio_system, "sleepDebt", 0.0),
            )
        )
    except Exception:
        return 0.0


def build_biological_status(bio_system: Any) -> Optional[Dict[str, Any]]:
    if not bio_system:
        return None
    nt = bio_system.getNeurotransmitters()
    sleep_debt = _get_sleep_debt(bio_system)
    return {
        "neurotransmitters": {
            "dopamine": float(getattr(nt, "dopamine", 0.5)),
            "serotonin": float(getattr(nt, "serotonin", 0.5)),
            "norepinephrine": float(getattr(nt, "norepinephrine", 0.5)),
            "oxytocin": float(getattr(nt, "oxytocin", 0.5)),
            "cortisol": float(getattr(nt, "cortisol", 0.3)),
        },
        "energy": float(bio_system.getEnergy()),
        "sleep_debt": sleep_debt,
        "circadian_phase": str(bio_system.getCircadianPhase()).split(".")[-1],
        "cognitive_delay": float(bio_system.calculateCognitiveDelay(0.5)),
    }
