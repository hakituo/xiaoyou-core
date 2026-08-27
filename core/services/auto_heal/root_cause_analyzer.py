import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from core.services.auto_heal.models import (
    AnomalyEvent,
    AnomalyType,
    RootCauseReport,
)
from core.utils.logger import get_logger

logger = get_logger("RootCauseAnalyzer")

_MAX_SOURCE_CONTEXT_LINES = 80
_EXTRA_CONTEXT_LINES = 15


class RootCauseAnalyzer:
    def __init__(self, project_root: Optional[str] = None):
        if project_root:
            self._project_root = Path(project_root)
        else:
            try:
                from core.utils.common import get_project_root

                self._project_root = Path(get_project_root())
            except Exception:
                self._project_root = Path(__file__).parent.parent.parent.parent

    async def analyze(
        self,
        anomaly: AnomalyEvent,
        persona_context: Optional[str] = None,
    ) -> Optional[RootCauseReport]:
        if anomaly.anomaly_type in (
            AnomalyType.ERROR_BURST,
            AnomalyType.ERROR_CLUSTER,
            AnomalyType.REPEATED_EXCEPTION,
        ):
            return await self._analyze_error_anomaly(
                anomaly, persona_context=persona_context
            )
        elif anomaly.anomaly_type == AnomalyType.BUSINESS_METRIC_ANOMALY:
            return await self._analyze_business_anomaly(
                anomaly, persona_context=persona_context
            )
        elif anomaly.anomaly_type == AnomalyType.SERVICE_DEGRADATION:
            return await self._analyze_service_anomaly(
                anomaly, persona_context=persona_context
            )
        return None

    async def _analyze_error_anomaly(
        self,
        anomaly: AnomalyEvent,
        persona_context: Optional[str] = None,
    ) -> Optional[RootCauseReport]:
        fp = anomaly.fingerprint
        if fp is None or not fp.file_path:
            if anomaly.metadata.get("error_type"):
                return await self._locate_error_by_type(anomaly)
            return None

        file_path = self._resolve_source_path(fp.file_path)
        if file_path is None or not file_path.exists():
            logger.warning(f"源文件不存在: {fp.file_path}")
            return None

        source_code, start_line, end_line = await asyncio.to_thread(
            self._read_source_context, file_path, fp.line_number
        )

        if not source_code:
            return None

        function_name, class_name = self._extract_function_class(
            source_code, fp.line_number - start_line
        )

        analysis = await self._llm_analyze(
            anomaly, source_code, file_path, persona_context=persona_context
        )

        return RootCauseReport(
            anomaly=anomaly,
            file_path=str(file_path.relative_to(self._project_root)).replace(
                "\\", "/"
            ),
            start_line=start_line,
            end_line=end_line,
            function_name=function_name or fp.function_name,
            class_name=class_name,
            analysis=analysis.get("analysis", ""),
            confidence=float(analysis.get("confidence", 0.5)),
            source_code=source_code,
            related_files=analysis.get("related_files", []),
            suggested_fix=analysis.get("suggested_fix", ""),
        )

    async def _analyze_business_anomaly(
        self,
        anomaly: AnomalyEvent,
        persona_context: Optional[str] = None,
    ) -> Optional[RootCauseReport]:
        metric_name = anomaly.metric_name
        if metric_name == "active_care_messages_today":
            return await self._analyze_active_care_flood(anomaly)
        return None

    async def _analyze_active_care_flood(
        self, anomaly: AnomalyEvent
    ) -> Optional[RootCauseReport]:
        suspect_files = [
            "core/services/active_care/scheduler_logic.py",
            "core/services/active_care/proactive_checker.py",
            "core/services/active_care/service.py",
            "core/services/active_care/executor.py",
            "core/services/active_care/decision.py",
        ]

        for rel_path in suspect_files:
            file_path = self._resolve_source_path(rel_path)
            if file_path and file_path.exists():
                source_code = await asyncio.to_thread(self._read_full_file, file_path)
                if source_code:
                    analysis = await self._llm_analyze(anomaly, source_code, file_path)
                    return RootCauseReport(
                        anomaly=anomaly,
                        file_path=rel_path,
                        start_line=1,
                        end_line=source_code.count("\n") + 1,
                        function_name="",
                        class_name="",
                        analysis=analysis.get("analysis", ""),
                        confidence=float(analysis.get("confidence", 0.3)),
                        source_code=source_code[:5000],
                        related_files=[
                            f for f in suspect_files if f != rel_path
                        ],
                        suggested_fix=analysis.get("suggested_fix", ""),
                    )
        return None

    async def _analyze_service_anomaly(
        self,
        anomaly: AnomalyEvent,
        persona_context: Optional[str] = None,
    ) -> Optional[RootCauseReport]:
        unhealthy = anomaly.metadata.get("unhealthy_services", [])
        if not unhealthy:
            return None

        service_file_map = {
            "active_care_service": "core/services/active_care/service.py",
            "immune_system": "core/services/immune/service.py",
            "websocket_adapter": "core/interfaces/websocket/fastapi_websocket_adapter.py",
            "cpp_scheduler_engine": "core/services/scheduler/cpp_scheduler_engine.py",
            "task_scheduler": "core/services/scheduler/task/task_scheduler.py",
            "monitoring_system": "core/async_monitor.py",
            "aveline_service": "core/services/aveline/service.py",
        }

        for svc_name in unhealthy:
            rel_path = service_file_map.get(svc_name)
            if rel_path:
                file_path = self._resolve_source_path(rel_path)
                if file_path and file_path.exists():
                    source_code = await asyncio.to_thread(
                        self._read_full_file, file_path
                    )
                    if source_code:
                        return RootCauseReport(
                            anomaly=anomaly,
                            file_path=rel_path,
                            start_line=1,
                            end_line=source_code.count("\n") + 1,
                            function_name="",
                            class_name="",
                            analysis=f"服务 {svc_name} 不健康，可能存在初始化或运行时错误",
                            confidence=0.4,
                            source_code=source_code[:5000],
                            related_files=[],
                            suggested_fix="",
                        )
        return None

    async def _locate_error_by_type(
        self, anomaly: AnomalyEvent
    ) -> Optional[RootCauseReport]:
        error_type = anomaly.metadata.get("error_type", "")
        if not error_type:
            return None

        result = self._find_by_logger_name(error_type, anomaly)
        if result:
            return result

        result = self._find_by_error_type(error_type, anomaly)
        return result

    def _find_by_logger_name(
        self, logger_name: str, anomaly: AnomalyEvent
    ) -> Optional[RootCauseReport]:
        search_dirs = [
            self._project_root / "core",
            self._project_root / "config",
        ]
        patterns = [
            f'get_logger("{logger_name}")',
            f"get_logger('{logger_name}')",
            f'Logger("{logger_name}")',
            f"Logger('{logger_name}')",
        ]
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    for pattern in patterns:
                        if pattern in content:
                            rel = str(py_file.relative_to(self._project_root)).replace(
                                "\\", "/"
                            )
                            return RootCauseReport(
                                anomaly=anomaly,
                                file_path=rel,
                                start_line=1,
                                end_line=min(content.count("\n") + 1, 100),
                                function_name="",
                                class_name="",
                                analysis=f"通过 logger 名称 {logger_name} 定位到错误来源文件",
                                confidence=0.5,
                                source_code=content[:3000],
                                related_files=[],
                                suggested_fix="",
                            )
                except Exception:
                    continue
        return None

    def _find_by_error_type(
        self, error_type: str, anomaly: AnomalyEvent
    ) -> Optional[RootCauseReport]:
        search_dirs = [
            self._project_root / "core",
            self._project_root / "config",
        ]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    if f"raise {error_type}" in content or f" {error_type}(" in content:
                        rel = str(py_file.relative_to(self._project_root)).replace(
                            "\\", "/"
                        )
                        return RootCauseReport(
                            anomaly=anomaly,
                            file_path=rel,
                            start_line=1,
                            end_line=min(content.count("\n") + 1, 100),
                            function_name="",
                            class_name="",
                            analysis=f"通过错误类型 {error_type} 定位到可能来源文件",
                            confidence=0.2,
                            source_code=content[:3000],
                            related_files=[],
                            suggested_fix="",
                        )
                except Exception:
                    continue
        return None

    async def _llm_analyze(
        self,
        anomaly: AnomalyEvent,
        source_code: str,
        file_path: Path,
        persona_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from core.core_engine.service_singletons import get_aveline_service
            from config.model_config import get_auto_heal_model

            aveline = get_aveline_service()
            if not aveline:
                return {"analysis": "LLM 不可用", "confidence": 0.0}

            model_hint = get_auto_heal_model("analysis")

            fp = anomaly.fingerprint
            error_info = ""
            if fp:
                error_info = (
                    f"错误类型: {fp.error_type}\n"
                    f"错误消息: {fp.error_message}\n"
                    f"堆栈追踪:\n{fp.sample_traceback[:2000]}\n"
                )

            from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
                AUTO_HEAL_PERSONA_PREFIX,
                AUTO_HEAL_ANALYSIS_PROMPT,
            )

            persona_prefix = ""
            if persona_context:
                persona_prefix = AUTO_HEAL_PERSONA_PREFIX.format(
                    persona_context=persona_context
                )

            prompt = AUTO_HEAL_ANALYSIS_PROMPT.format(
                persona_prefix=persona_prefix,
                anomaly_type=anomaly.anomaly_type.value,
                severity=anomaly.severity.value,
                description=anomaly.description,
                error_info=error_info,
                source_code=source_code[:6000],
                file_name=file_path.name,
            )

            response_text, _ = await aveline.generate_response(
                user_input=prompt,
                conversation_id="auto_heal_analysis",
                max_tokens=1024,
                temperature=0.3,
                model_hint=model_hint or None,
                save_history=False,
            )

            return self._parse_llm_json(response_text)
        except Exception as e:
            logger.warning(f"LLM 分析失败: {e}")
            return {"analysis": f"LLM 分析失败: {e}", "confidence": 0.0}

    def _parse_llm_json(self, text: str) -> Dict[str, Any]:
        import json
        import re

        code_block = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except json.JSONDecodeError:
                pass

        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return {
            "analysis": text[:500],
            "confidence": 0.3,
            "suggested_fix": "",
            "related_files": [],
        }

    def _resolve_source_path(self, rel_path: str) -> Optional[Path]:
        candidates = [
            self._project_root / rel_path,
            self._project_root / "src" / rel_path,
        ]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists() and resolved.is_file():
                try:
                    resolved.relative_to(self._project_root)
                except ValueError:
                    continue
                return resolved
        return None

    def _read_source_context(
        self, file_path: Path, center_line: int
    ) -> tuple:
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return "", 0, 0

        if center_line <= 0:
            center_line = 1

        total = len(lines)
        start = max(1, center_line - _EXTRA_CONTEXT_LINES)
        end = min(total, center_line + _EXTRA_CONTEXT_LINES)

        if end - start > _MAX_SOURCE_CONTEXT_LINES:
            end = start + _MAX_SOURCE_CONTEXT_LINES

        context_lines = lines[start - 1 : end]
        source = "\n".join(f"{i}: {line}" for i, line in zip(range(start, end + 1), context_lines))
        return source, start, end

    def _read_full_file(self, file_path: Path) -> str:
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _extract_function_class(
        self, source_code: str, relative_line: int
    ) -> tuple:
        import re

        func_name = ""
        class_name = ""

        lines = source_code.split("\n")
        for i in range(min(relative_line, len(lines)) - 1, -1, -1):
            if i >= len(lines):
                continue
            line = lines[i]

            func_match = re.match(r'\s*(?:async\s+)?def\s+(\w+)', line)
            if func_match and not func_name:
                func_name = func_match.group(1)

            class_match = re.match(r'\s*class\s+(\w+)', line)
            if class_match and not class_name:
                class_name = class_match.group(1)

            if func_name and class_name:
                break

        return func_name, class_name
