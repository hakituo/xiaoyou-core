from typing import Optional, Type
from pydantic import BaseModel, Field
from core.tools.base import BaseTool
from core.services.workspace.service import get_workspace_service


class AddStatusInput(BaseModel):
    name: str = Field(
        description="状态名称，简短关键词，如 '口腔溃疡', '感冒', '考试周'"
    )
    description: str = Field(
        description="状态描述，包含具体症状或注意事项，如 '痛感明显，不能吃辣'"
    )
    duration_days: Optional[int] = Field(
        default=None, description="预计持续天数，过期后自动移除"
    )


class RemoveStatusInput(BaseModel):
    name: str = Field(description="要移除的状态名称")


class AddStatusTool(BaseTool):
    name = "add_user_status"
    description = "记录用户的持续性状态（如生病、忙碌、特殊时期）。当用户说自己身体不适或有长期安排时使用。"
    args_schema: Type[BaseModel] = AddStatusInput

    async def _run(
        self, name: str, description: str, duration_days: Optional[int] = None
    ) -> str:
        ws = get_workspace_service()
        result = await ws.add_user_status(name, description, duration_days)
        summary = await ws.get_user_status_summary()
        storage_path = await ws.get_user_status_storage_path()
        return f"{result}\n\n{summary}\n\n状态文件: {storage_path}"


class RemoveStatusTool(BaseTool):
    name = "remove_user_status"
    description = "移除用户的持续性状态。当用户说病好了或事情结束时使用。"
    args_schema: Type[BaseModel] = RemoveStatusInput

    async def _run(self, name: str) -> str:
        ws = get_workspace_service()
        result = await ws.remove_user_status(name)
        summary = await ws.get_user_status_summary()
        storage_path = await ws.get_user_status_storage_path()
        return f"{result}\n\n{summary}\n\n状态文件: {storage_path}"


class GetStatusTool(BaseTool):
    name = "get_user_status"
    description = "查看用户当前的所有持续性状态。"

    async def _run(self) -> str:
        ws = get_workspace_service()
        summary = await ws.get_user_status_summary()
        storage_path = await ws.get_user_status_storage_path()
        return f"{summary}\n\n状态文件: {storage_path}"
