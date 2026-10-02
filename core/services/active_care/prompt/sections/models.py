"""主动关怀 Prompt 的结构化构建结果。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class PromptSection:
    name: str
    content: str

    @property
    def chars(self) -> int:
        return len(self.content or "")


@dataclass
class ActiveCarePromptBuildResult:
    prompt: str
    sections: List[PromptSection]
    dynamic_prompt: str = ""
    has_deferred_reminders: bool = False

    @property
    def static_prompt(self) -> str:
        return self.prompt

    @property
    def static_chars(self) -> int:
        return len(self.prompt or "")

    @property
    def dynamic_chars(self) -> int:
        return len(self.dynamic_prompt or "")

    @property
    def total_chars(self) -> int:
        return self.static_chars + self.dynamic_chars

    @property
    def non_empty_sections(self) -> int:
        return sum(1 for section in self.sections if (section.content or "").strip())

    def format_breakdown(self) -> str:
        lines = [
            f"- static_chars={self.static_chars}, dynamic_chars={self.dynamic_chars}",
            f"- non_empty_sections={self.non_empty_sections}",
        ]
        for section in self.sections:
            content = str(section.content or "").strip()
            preview = content.replace("\n", " ")[:80]
            lines.append(f"- {section.name}: chars={section.chars}, preview={preview}")
        return "\n".join(lines)
