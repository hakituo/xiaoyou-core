import time
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass

from core.utils.logger import get_logger
from core.contracts import ApprovalStatus
from core.utils.async_locks import LazyAsyncLock

logger = get_logger("ApprovalService")

@dataclass
class ApprovalRequest:
    request_id: str
    action_type: str
    description: str
    payload: Dict[str, Any]
    created_at: float
    expires_at: float
    status: ApprovalStatus = ApprovalStatus.PENDING
    executor: Optional[Callable[..., Awaitable[Any]]] = None

class ApprovalService:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ApprovalService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._requests: Dict[str, ApprovalRequest] = {}
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._initialized = True
        self._cleanup_task = None

    def create_request(
        self,
        action_type: str,
        description: str,
        payload: Dict[str, Any],
        executor: Callable[..., Awaitable[Any]],
        ttl_seconds: int = 300
    ) -> str:
        """Create a new approval request and return its ID (token)."""
        request_id = str(uuid.uuid4())[:8]  # Short ID for ease of typing
        now = time.time()
        req = ApprovalRequest(
            request_id=request_id,
            action_type=action_type,
            description=description,
            payload=payload,
            created_at=now,
            expires_at=now + ttl_seconds,
            status=ApprovalStatus.PENDING,
            executor=executor
        )
        self._requests[request_id] = req
        logger.info(f"Created approval request {request_id}: {action_type} - {description}")
        return request_id

    async def approve_request(self, request_id: str) -> Dict[str, Any]:
        """Approve and execute a pending request."""
        async with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return {"success": False, "message": "审批单不存在"}
            
            if req.status != ApprovalStatus.PENDING:
                return {"success": False, "message": f"审批单状态无效: {req.status.value}"}
            
            if time.time() > req.expires_at:
                req.status = ApprovalStatus.EXPIRED
                return {"success": False, "message": "审批单已过期"}
            
            req.status = ApprovalStatus.APPROVED
            
        try:
            logger.info(f"Executing approved request {request_id}...")
            if req.executor:
                result = await req.executor()
                return {"success": True, "message": "执行成功", "result": result}
            return {"success": True, "message": "审批通过（无执行逻辑）"}
        except Exception as e:
            logger.error(f"Execution failed for {request_id}: {e}", exc_info=True)
            return {"success": False, "message": f"执行失败: {str(e)}"}
        finally:
            # Clean up after execution (or keep for audit log if needed later)
            async with self._lock:
                self._requests.pop(request_id, None)

    async def reject_request(self, request_id: str) -> Dict[str, Any]:
        """Reject a pending request."""
        async with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return {"success": False, "message": "审批单不存在"}
            
            req.status = ApprovalStatus.REJECTED
            self._requests.pop(request_id, None)
            logger.info(f"Rejected request {request_id}")
            return {"success": True, "message": "已拒绝"}

    async def get_request_info(self, request_id: str) -> Optional[Dict[str, Any]]:
        req = self._requests.get(request_id)
        if not req:
            return None
        return {
            "request_id": req.request_id,
            "action_type": req.action_type,
            "description": req.description,
            "status": req.status.value,
            "expires_in": max(0, int(req.expires_at - time.time())),
            "payload_summary": str(req.payload)[:200]
        }

    async def cleanup_expired(self):
        """Cleanup expired requests."""
        now = time.time()
        async with self._lock:
            expired = [rid for rid, req in self._requests.items() if now > req.expires_at]
            for rid in expired:
                self._requests.pop(rid, None)

def get_approval_service() -> ApprovalService:
    return ApprovalService()
