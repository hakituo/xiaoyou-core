import difflib
import asyncio
from pathlib import Path
from typing import Optional

from core.services.auto_heal.models import Patch, PatchStatus, RootCauseReport
from core.utils.logger import get_logger

logger = get_logger("PatchGenerator")

_MAX_SOURCE_FOR_LLM = 8000


class PatchGenerator:
    def __init__(self, project_root: Optional[str] = None):
        if project_root:
            self._project_root = Path(project_root)
        else:
            try:
                from core.utils.common import get_project_root

                self._project_root = Path(get_project_root())
            except Exception:
                self._project_root = Path(__file__).parent.parent.parent.parent

    async def generate(
        self,
        root_cause: RootCauseReport,
        persona_context: Optional[str] = None,
    ) -> Optional[Patch]:
        if not root_cause.file_path:
            logger.warning("根因分析无文件路径，无法生成补丁")
            return None

        file_path = self._project_root / root_cause.file_path
        if not file_path.exists():
            logger.warning(f"源文件不存在: {root_cause.file_path}")
            return None

        original_code = await asyncio.to_thread(self._read_file, file_path)
        if not original_code:
            return None

        patched_code = await self._llm_generate_patch(
            root_cause, original_code, persona_context=persona_context
        )
        if not patched_code:
            return None

        if patched_code.strip() == original_code.strip():
            logger.info("LLM 生成的补丁与原始代码相同，跳过")
            return None

        diff = self._compute_diff(original_code, patched_code, root_cause.file_path)

        return Patch(
            anomaly_id=root_cause.anomaly.id,
            file_path=root_cause.file_path,
            original_code=original_code,
            patched_code=patched_code,
            diff=diff,
            description=root_cause.suggested_fix or root_cause.analysis[:200],
            status=PatchStatus.GENERATING,
            root_cause=root_cause,
            rollback_code=original_code,
        )

    async def _llm_generate_patch(
        self,
        root_cause: RootCauseReport,
        original_code: str,
        persona_context: Optional[str] = None,
    ) -> Optional[str]:
        try:
            from core.core_engine.service_singletons import get_aveline_service
            from config.model_config import get_auto_heal_model

            aveline = get_aveline_service()
            if not aveline:
                return None

            model_hint = get_auto_heal_model("patch_generation")

            fp = root_cause.anomaly.fingerprint
            error_info = ""
            if fp:
                error_info = (
                    f"错误类型: {fp.error_type}\n"
                    f"错误消息: {fp.error_message}\n"
                    f"堆栈:\n{fp.sample_traceback[:1500]}\n"
                )

            analysis_info = ""
            if root_cause.analysis:
                analysis_info = f"## 根因分析\n{root_cause.analysis}\n\n"
            if root_cause.suggested_fix:
                analysis_info += f"## 建议修复方案\n{root_cause.suggested_fix}\n\n"

            from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
                AUTO_HEAL_PERSONA_PREFIX,
                AUTO_HEAL_PATCH_PROMPT,
            )

            persona_prefix = ""
            if persona_context:
                persona_prefix = AUTO_HEAL_PERSONA_PREFIX.format(
                    persona_context=persona_context
                )

            prompt = AUTO_HEAL_PATCH_PROMPT.format(
                persona_prefix=persona_prefix,
                anomaly_type=root_cause.anomaly.anomaly_type.value,
                description=root_cause.anomaly.description,
                error_info=error_info,
                analysis_info=analysis_info,
                original_code=original_code[:_MAX_SOURCE_FOR_LLM],
                file_path=root_cause.file_path,
            )

            response_text, _ = await aveline.generate_response(
                user_input=prompt,
                conversation_id="auto_heal_patch",
                max_tokens=4096,
                temperature=0.2,
                model_hint=model_hint or None,
                save_history=False,
            )

            return self._extract_code(response_text)
        except Exception as e:
            logger.error(f"LLM 生成补丁失败: {e}")
            return None

    def _extract_code(self, text: str) -> Optional[str]:
        import re

        patterns = [
            r'```python\s*\n([\s\S]*?)```',
            r'```\s*\n([\s\S]*?)```',
        ]

        code = None
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                code = match.group(1).strip()
                break

        if code is None and text.strip().startswith(("import ", "from ", "class ", "def ", "#")):
            code = text.strip()

        if code and not self._check_try_blocks(code):
            logger.warning("提取的代码包含不完整的try块，丢弃")
            return None

        return code

    @staticmethod
    def _check_try_blocks(code: str) -> bool:
        """检查代码中所有try块是否都有对应的except或finally"""
        import ast
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _compute_diff(
        self, original: str, patched: str, file_path: str
    ) -> str:
        orig_lines = original.splitlines(keepends=True)
        patch_lines = patched.splitlines(keepends=True)

        diff = difflib.unified_diff(
            orig_lines,
            patch_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
        return "".join(diff)

    def _read_file(self, file_path: Path) -> str:
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"读取文件失败: {e}")
            return ""
