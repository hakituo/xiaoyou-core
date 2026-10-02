import time
from typing import Any, Dict, Optional

from core.services.data_ops.service import get_data_ops_service


def unauthorized_response() -> Dict[str, Any]:
    return {"status": "error", "message": "未授权的内部调用", "timestamp": time.time()}


async def submit_daily_digest(
    *,
    date: str = "",
    include_diary_summary: bool = True,
    use_queue: bool = False,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_daily_digest(
        date=date,
        include_diary_summary=include_diary_summary,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
    )


async def submit_weekly_report(
    *, anchor_date: str = "", use_queue: bool = False, idempotency_key: str = ""
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_weekly_report(
        anchor_date=anchor_date,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
    )


async def submit_task_plan(
    *,
    date: str = "",
    force: bool = False,
    use_queue: bool = False,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_task_plan(
        date=date,
        force=force,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
    )


async def submit_human_daily_digest(
    *,
    date: str = "",
    include_device_context: bool = True,
    use_queue: bool = False,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_human_daily_digest(
        date=date,
        include_device_context=include_device_context,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
    )


async def submit_human_weekly_report(
    *,
    anchor_date: str = "",
    include_device_context: bool = False,
    use_queue: bool = False,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_human_weekly_report(
        anchor_date=anchor_date,
        include_device_context=include_device_context,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
    )


async def submit_memory_rule_analysis(
    *,
    user_id: str,
    use_queue: bool = True,
    idempotency_key: str = "",
    limit: int = 0,
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_memory_rule_analysis(
        user_id=user_id,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
        limit=limit,
    )


async def submit_memory_ai_shadow_analysis(
    *,
    user_id: str,
    use_queue: bool = True,
    idempotency_key: str = "",
    limit: int = 0,
    timeout_ms: int = 0,
    strategy: str = "",
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_memory_ai_shadow_analysis(
        user_id=user_id,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
        limit=limit,
        timeout_ms=timeout_ms,
        strategy=strategy,
    )


async def submit_memory_fusion_adjudication(
    *,
    user_id: str,
    use_queue: bool = True,
    idempotency_key: str = "",
    limit: int = 0,
    override_min_confidence: float = 0.0,
    supplement_min_confidence: float = 0.0,
    allow_override: Optional[bool] = None,
) -> Dict[str, Any]:
    return await get_data_ops_service().submit_memory_fusion_adjudication(
        user_id=user_id,
        use_queue=use_queue,
        idempotency_key=idempotency_key,
        limit=limit,
        override_min_confidence=override_min_confidence,
        supplement_min_confidence=supplement_min_confidence,
        allow_override=allow_override,
    )


async def run_data_ops_task(task_id: str) -> Dict[str, Any]:
    return await get_data_ops_service().run_task(task_id)


def get_data_ops_task(task_id: str) -> Dict[str, Any]:
    return get_data_ops_service().get_task(task_id)


def get_memory_rule_analysis_metrics() -> Dict[str, Any]:
    return get_data_ops_service().get_memory_rule_analysis_metrics()


def get_memory_ai_shadow_metrics() -> Dict[str, Any]:
    return get_data_ops_service().get_memory_ai_shadow_metrics()


def get_memory_fusion_metrics() -> Dict[str, Any]:
    return get_data_ops_service().get_memory_fusion_metrics()
