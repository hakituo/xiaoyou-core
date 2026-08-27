from abc import ABC, abstractmethod
from typing import Any, Dict, Type, Optional
from pydantic import BaseModel


class BaseTool(ABC):
    """
    Base class for all tools.
    """

    name: str
    description: str
    args_schema: Optional[Type[BaseModel]] = None
    # Short hint for prompt injection (overrides description if set)
    short_description: Optional[str] = None
    # Category for grouping (e.g. "memory", "daily", "study", "utility")
    category: str = "utility"
    # Whether this tool is enabled by default
    enabled_by_default: bool = True

    def set_runtime_context(self, context: Dict[str, Any]) -> None:
        """Inject runtime context (agent, user_id, etc.) before execution."""
        self._runtime_context = context

    def _get_ctx(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for runtime context keys."""
        return getattr(self, "_runtime_context", {}).get(key, default)

    @abstractmethod
    async def _run(self, *args, **kwargs) -> Any:
        """
        Implementation of the tool.
        """
        pass

    async def run(self, *args, **kwargs) -> str:
        """
        Execute the tool and return the result as a string.
        """
        try:
            result = await self._run(*args, **kwargs)
            return str(result)
        except Exception as e:
            return f"Error executing tool {self.name}: {str(e)}"
