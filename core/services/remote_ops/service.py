from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from core.services.workspace.service import get_workspace_service

RemoteFileAction = Literal["list", "read", "write", "append", "mkdir", "exists"]
ALLOWED_REMOTE_FILE_ACTIONS = {"list", "read", "write", "append", "mkdir", "exists"}


class RemoteOpsService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RemoteOpsService, cls).__new__(cls)
        return cls._instance

    async def run_workspace_file_action(
        self,
        *,
        action: RemoteFileAction,
        path: Optional[str] = None,
        content: Optional[str] = None,
        max_chars: int = 200000,
        limit: int = 200,
    ) -> Dict[str, Any]:
        action_name = str(action or "").strip().lower()
        if action_name not in ALLOWED_REMOTE_FILE_ACTIONS:
            raise ValueError(f"不支持的远程文件动作: {action_name}")

        ws = get_workspace_service()
        relative_path = str(path or ".").strip() or "."
        if action_name == "list":
            safe_limit = max(1, min(int(limit or 200), 2000))
            data = await ws.list_study_items(relative_path, recursive=False, limit=safe_limit)
            return {"action": action_name, **data}
            
        if action_name == "read":
            if not str(path or "").strip():
                raise ValueError("read 需要 path")
            safe_chars = max(1, min(int(max_chars or 200000), 2_000_000))
            data = await ws.read_study_text(relative_path, max_chars=safe_chars)
            return {"action": action_name, **data}
            
        if action_name == "write":
            if not str(path or "").strip():
                raise ValueError("write 需要 path")
            if content is None:
                raise ValueError("write 需要 content")
            data = await ws.write_study_text(relative_path, str(content), append=False)
            return {"action": action_name, **data}
            
        if action_name == "append":
            if not str(path or "").strip():
                raise ValueError("append 需要 path")
            if content is None:
                raise ValueError("append 需要 content")
            data = await ws.write_study_text(relative_path, str(content), append=True)
            return {"action": action_name, **data}
            
        mapped_action = "mkdir" if action_name == "mkdir" else "exists"
        if not str(path or "").strip():
            raise ValueError(f"{action_name} 需要 path")
        data = await ws.run_study_data_action(action=mapped_action, path=relative_path)
        return {"action": action_name, **data}

    async def approve_action(self, token: str) -> Dict[str, Any]:
        return {"success": False, "message": "学习文件操作已改为直接执行，无需审批"}

    async def reject_action(self, token: str) -> Dict[str, Any]:
        return {"success": False, "message": "学习文件操作已改为直接执行，无需审批"}


def get_remote_ops_service() -> RemoteOpsService:
    return RemoteOpsService()
