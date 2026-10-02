import os
import json
import asyncio
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field
from .base import BaseTool

# Import Study tools
try:
    from core.tools.study.common.data_io import DataIO
except ImportError as e:
    print(f"Warning: Failed to import Study tools: {e}")
    DataIO = None

# Import TTS Manager
try:
    from multimodal.tts_manager import get_tts_manager
except ImportError:
    get_tts_manager = None

# --- File Creation Tool ---


class FileCreationInput(BaseModel):
    content: List[Dict[str, Any]] = Field(
        description="List of data items to write to file. Each item should be a dictionary."
    )
    filename: str = Field(
        description="Name of the file to create (including extension like .txt, .xlsx, .docx, .pdf)"
    )
    title: Optional[str] = Field(
        default=None, description="Title for the document (for Word/PDF)"
    )


class FileCreationTool(BaseTool):
    name = "create_file"
    description = "Create files (TXT, Excel, Word, PDF) with structured data."
    args_schema = FileCreationInput

    async def _run(
        self, content: List[Dict[str, Any]], filename: str, title: Optional[str] = None
    ) -> str:
        if not DataIO:
            return "Error: DataIO is not available."

        def _sync() -> str:
            try:
                project_root = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
                output_dir = os.path.join(project_root, "data", "output")
                os.makedirs(output_dir, exist_ok=True)
                filepath = os.path.join(output_dir, filename)

                kwargs = {}
                if title:
                    kwargs["title"] = title

                DataIO.export_data(content, filepath, **kwargs)
                return f"File successfully created at: {filepath}"
            except Exception as e:
                return f"Error creating file: {str(e)}"

        return await asyncio.to_thread(_sync)


# --- Text To Speech Tool ---


class TTSInput(BaseModel):
    text: str = Field(description="Text to convert to speech")
    emotion: str = Field(
        default="neutral",
        description="Emotion for the speech (e.g., neutral, happy, sad)",
    )
    speed: float = Field(default=1.0, description="Speed of the speech (default: 1.0)")


class TextToSpeechTool(BaseTool):
    name = "text_to_speech"
    description = "Convert text to speech (audio file)."
    args_schema = TTSInput

    async def _run(
        self, text: str, emotion: str = "neutral", speed: float = 1.0
    ) -> str:
        if not get_tts_manager:
            return "Error: TTS Manager is not available."

        try:
            tts_manager = get_tts_manager()
            if not tts_manager:
                return "Error: Could not initialize TTS Manager."

            if hasattr(tts_manager, "async_text_to_speech"):
                result = await tts_manager.async_text_to_speech(
                    text, speed=speed, emotion=emotion
                )
                return f"[GEN_AUDIO: {result}]"
            elif hasattr(tts_manager, "text_to_speech"):
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: tts_manager.text_to_speech(
                        text, speed=speed, emotion=emotion
                    ),
                )
                return f"[GEN_AUDIO: {result}]"
            else:
                return "Error: TTS method not found on manager."

        except Exception as e:
            return f"Error generating speech: {str(e)}"


# --- Knowledge Retrieval Tool ---


class KnowledgeRetrievalInput(BaseModel):
    query: str = Field(
        description="The query string to search for in the study knowledge base."
    )
    top_k: int = Field(
        default=3, description="Number of results to retrieve (default: 3)."
    )


class KnowledgeRetrievalTool(BaseTool):
    name = "search_knowledge_base"
    description = "Search for specific knowledge points, formulas, or facts in the ingested study materials (Gao Kao / Study Data)."
    args_schema = KnowledgeRetrievalInput

    def __init__(self):
        super().__init__()
        # Lazy load VectorSearch to avoid circular imports or early init issues
        self.vector_search = None

    def _get_vector_search(self):
        if self.vector_search:
            return self.vector_search

        try:
            from core.vector_search import VectorSearch

            # Initialize with existing persistence
            self.vector_search = VectorSearch(use_in_memory_db=False)
            return self.vector_search
        except Exception as e:
            print(f"Error initializing VectorSearch in tool: {e}")
            return None

    async def _run(self, query: str, top_k: int = 3) -> str:
        vs = self._get_vector_search()
        if not vs:
            return "Error: Vector Knowledge Base is not available."

        def _sync() -> str:
            try:
                results = vs.query(query, top_k=top_k)
                if not results:
                    return "No relevant knowledge found in the database."

                formatted_results = []
                for i, doc in enumerate(results):
                    formatted_results.append(f"Result {i + 1}:\n{doc}\n")
                return "\n".join(formatted_results)
            except Exception as e:
                return f"Error searching knowledge base: {str(e)}"

        return await asyncio.to_thread(_sync)


# --- Update Word Progress Tool ---


class UpdateWordProgressInput(BaseModel):
    word: str = Field(description="The English word to update progress for.")
    quality: int = Field(
        description=(
            "Recall quality rating using the App contract (1-4): "
            "1=Again (forgot), 2=Hard, 3=Good, 4=Easy. "
            "0 is treated as Again and 5 as Easy for compatibility."
        )
    )


class UpdateWordProgressTool(BaseTool):
    name = "update_word_progress"
    description = "Update learning progress for an English word. Call this when the user indicates if they remember or forgot a word."
    args_schema = UpdateWordProgressInput

    async def _run(self, word: str, quality: int) -> str:
        def _sync() -> str:
            try:
                from config.integrated_config import get_settings
                if not get_settings().study.enabled:
                    return "词库功能未启用"
                from core.tools.study.english.vocabulary_manager import (
                    get_vocabulary_manager,
                )

                vm = get_vocabulary_manager()
                vm.update_word_progress(word, quality)

                # 现行契约下 2=Hard 也是成功回忆，只有 Again(<=1) 算忘了。
                if quality <= 1:
                    return f"Marked '{word}' as forgotten. Will review soon."
                return f"Marked '{word}' as remembered (Quality: {quality})."
            except Exception as e:
                return f"Error updating word progress: {str(e)}"

        return await asyncio.to_thread(_sync)


# --- Word Quiz Tool ---


class WordQuizInput(BaseModel):
    action: str = Field(
        default="quiz",
        description="Action to execute: quiz / stats / mark_unknown / mark_known",
    )
    source: Literal["daily", "unfamiliar", "both"] = Field(
        default="daily",
        description=(
            "Word source: 'daily' (default) uses recent per-day logs under "
            "daily/YYYY/MM/DD.txt; 'unfamiliar' uses the long-term "
            "unfamiliar_word.txt; 'both' returns the two sources separately."
        ),
    )
    count: int = Field(default=5, description="Number of words to quiz")
    word: Optional[str] = Field(default=None, description="Target word for mark action")
    priority: Literal["random", "high_count", "new"] = Field(
        default="random",
        description="Priority strategy: high_count / random / new",
    )
    days: Optional[int] = Field(
        default=None,
        ge=1,
        le=90,
        description=(
            "For source=daily: optional recent-day lookback. Omit both days and "
            "date to read yesterday's log, which is the default review source."
        ),
    )
    date: Optional[str] = Field(
        default=None,
        description=(
            "For source=daily: target a specific day, e.g. '2026/08/05' or '2026-08-05'. "
            "Takes precedence over 'days'."
        ),
    )


class WordQuizTool(BaseTool):
    name = "word_quiz"
    description = (
        "Quiz English words and track unknown counts. Use 'daily' for recently "
        "learned/missed words (default: yesterday's log), 'unfamiliar' for the "
        "long-term difficult-word book, or 'both' to inspect them separately. "
        "Never describe one source's result as the other source."
    )
    args_schema = WordQuizInput

    async def _run(
        self,
        action: str = "quiz",
        source: str = "daily",
        count: int = 5,
        word: Optional[str] = None,
        priority: str = "random",
        days: Optional[int] = None,
        date: Optional[str] = None,
    ) -> str:
        from core.services.study.service import get_study_service

        def _sync() -> str:
            try:
                result = get_study_service().run_tool(
                    "english",
                    "word_quiz",
                    {
                        "action": action,
                        "source": source,
                        "count": count,
                        "word": word,
                        "priority": priority,
                        "days": days,
                        "date": date,
                    },
                )
                return json.dumps(result, ensure_ascii=False)
            except Exception as e:
                return json.dumps(
                    {"status": "error", "message": str(e)},
                    ensure_ascii=False,
                )

        return await asyncio.to_thread(_sync)


def register_study_tools(registry):
    """Register all Study tools to the provided registry.

    注意：StudyDataTool 和 GetStudyProfileTool 已在 registry.py 中独立注册，
    此处不再重复注册。
    """
    registry.register(FileCreationTool())
    registry.register(TextToSpeechTool())
    registry.register(KnowledgeRetrievalTool())
    registry.register(UpdateWordProgressTool())
    registry.register(WordQuizTool())
