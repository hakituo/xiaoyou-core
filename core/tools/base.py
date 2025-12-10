from abc import ABC, abstractmethod
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel

class BaseTool(ABC):
    """
    Base class for all tools.
    """
    name: str
    description: str
    args_schema: Optional[Type[BaseModel]] = None

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
