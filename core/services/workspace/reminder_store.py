import json
import os
from pathlib import Path
from typing import Dict, List

import aiofiles


class WorkspaceReminderStore:
    def __init__(self, file_path: Path):
        self._file_path = Path(file_path).resolve()

    async def read(self) -> List[Dict]:
        if not self._file_path.exists():
            return []
        try:
            async with aiofiles.open(self._file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                if not content.strip():
                    return []
                return json.loads(content)
        except Exception:
            return []

    async def write(self, data: List[Dict]) -> None:
        # 空数据时跳过写入，已有文件则删除
        if not data:
            if self._file_path.exists():
                self._file_path.unlink()
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._file_path.with_suffix(self._file_path.suffix + ".tmp")
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp_path, self._file_path)
