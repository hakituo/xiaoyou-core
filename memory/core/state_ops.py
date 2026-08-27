from typing import Any, Dict, List


def update_state(
    manager: Any, content: str, status: str = "completed", ttl_hours: int = 24
) -> str:
    return manager.state_tracker.add_state(content, status, ttl_hours)


def get_active_states(manager: Any) -> List[Dict[str, Any]]:
    return manager.state_tracker.get_active_states()


def get_state_context(manager: Any) -> str:
    return manager.state_tracker.get_context_string()
