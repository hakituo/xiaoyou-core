import os
import sys
import json
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from .base import BaseTool

# Import Study tools
try:
    from core.tools.study.math.math_image_generator import MathImageGenerator
    from core.tools.study.common.data_io import DataIO
except ImportError as e:
    print(f"Warning: Failed to import Study tools: {e}")
    MathImageGenerator = None
    DataIO = None

# Import TTS Manager
try:
    from multimodal.tts_manager import get_tts_manager
except ImportError:
    get_tts_manager = None

# --- Math Plot Tool ---

class MathPlotInput(BaseModel):
    plot_type: str = Field(description="Type of plot to generate (e.g., 'sin', 'cos', 'cube', 'cylinder', 'sphere')")
    params: Dict[str, Any] = Field(description="Parameters for the plot (e.g., {'amplitude': 1, 'period': 6.28})")

class MathPlotTool(BaseTool):
    name = "generate_math_plot"
    description = "Generate mathematical plots and geometry figures using Python (matplotlib). Returns the path to the generated image."
    args_schema = MathPlotInput

    def _run(self, plot_type: str, params: Dict[str, Any]) -> str:
        if not MathImageGenerator:
            return "Error: MathImageGenerator is not available."
        
        try:
            generator = MathImageGenerator()
            
            # Map simple names to generator methods
            method_map = {
                # 3D Geometry
                "cuboid": generator.generate_cuboid,
                "cube": generator.generate_cube,
                "cylinder": generator.generate_cylinder,
                "cone": generator.generate_cone,
                "sphere": generator.generate_sphere,
                # Trig functions
                "sin": generator.generate_sin,
                "cos": generator.generate_cos,
                "tan": generator.generate_tan,
                "cot": generator.generate_cot,
                "compound_trig": generator.generate_compound_trig,
                # Conic sections
                "circle": generator.generate_circle,
                "ellipse": generator.generate_ellipse,
                "hyperbola": generator.generate_hyperbola,
                "parabola": generator.generate_parabola
            }
            
            if plot_type not in method_map:
                return f"Error: Unknown plot type '{plot_type}'. Available types: {list(method_map.keys())}"
            
            # Generate figure
            fig = method_map[plot_type](params)
            
            # Save to file
            # Use absolute path for safety
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(project_root, "static", "images", "generated")
            os.makedirs(output_dir, exist_ok=True)
            filename = f"math_plot_{plot_type}_{int(os.times()[4] * 100)}.png"
            filepath = os.path.join(output_dir, filename)
            
            fig.savefig(filepath)
            
            return f"[GEN_IMG: {filepath}]"
            
        except Exception as e:
            return f"Error generating plot: {str(e)}"

# --- File Creation Tool ---

class FileCreationInput(BaseModel):
    content: List[Dict[str, Any]] = Field(description="List of data items to write to file. Each item should be a dictionary.")
    filename: str = Field(description="Name of the file to create (including extension like .txt, .xlsx, .docx, .pdf)")
    title: Optional[str] = Field(default=None, description="Title for the document (for Word/PDF)")

class FileCreationTool(BaseTool):
    name = "create_file"
    description = "Create files (TXT, Excel, Word, PDF) with structured data."
    args_schema = FileCreationInput

    def _run(self, content: List[Dict[str, Any]], filename: str, title: Optional[str] = None) -> str:
        if not DataIO:
            return "Error: DataIO is not available."
            
        try:
            # Determine output path
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(project_root, "data", "output")
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, filename)
            
            # Call DataIO.export_data
            kwargs = {}
            if title:
                kwargs['title'] = title
                
            DataIO.export_data(content, filepath, **kwargs)
            
            return f"File successfully created at: {filepath}"
            
        except Exception as e:
            return f"Error creating file: {str(e)}"

# --- Text To Speech Tool ---

class TTSInput(BaseModel):
    text: str = Field(description="Text to convert to speech")
    emotion: str = Field(default="neutral", description="Emotion for the speech (e.g., neutral, happy, sad)")
    speed: float = Field(default=1.0, description="Speed of the speech (default: 1.0)")

class TextToSpeechTool(BaseTool):
    name = "text_to_speech"
    description = "Convert text to speech (audio file)."
    args_schema = TTSInput

    def _run(self, text: str, emotion: str = "neutral", speed: float = 1.0) -> str:
        if not get_tts_manager:
            return "Error: TTS Manager is not available."
            
        try:
            tts_manager = get_tts_manager()
            if not tts_manager:
                 return "Error: Could not initialize TTS Manager."
            
            if hasattr(tts_manager, 'text_to_speech'):
                result = tts_manager.text_to_speech(text, speed=speed, emotion=emotion)
                return f"[GEN_AUDIO: {result}]"
            else:
                return "Error: TTS method not found on manager."

        except Exception as e:
            return f"Error generating speech: {str(e)}"

# --- Knowledge Retrieval Tool ---

class KnowledgeRetrievalInput(BaseModel):
    query: str = Field(description="The query string to search for in the study knowledge base.")
    top_k: int = Field(default=3, description="Number of results to retrieve (default: 3).")

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

    def _run(self, query: str, top_k: int = 3) -> str:
        vs = self._get_vector_search()
        if not vs:
            return "Error: Vector Knowledge Base is not available."
        
        try:
            results = vs.query(query, top_k=top_k)
            if not results:
                return "No relevant knowledge found in the database."
            
            # Format results
            formatted_results = []
            for i, doc in enumerate(results):
                formatted_results.append(f"Result {i+1}:\n{doc}\n")
            
            return "\n".join(formatted_results)
        except Exception as e:
            return f"Error searching knowledge base: {str(e)}"

# --- Update Word Progress Tool ---

class UpdateWordProgressInput(BaseModel):
    word: str = Field(description="The English word to update progress for.")
    quality: int = Field(description="Recall quality rating (0-5). 0=Forgot, 1=Wrong, 2=Hard, 3=Ok, 4=Good, 5=Perfect.")

class UpdateWordProgressTool(BaseTool):
    name = "update_word_progress"
    description = "Update learning progress for an English word. Call this when the user indicates if they remember or forgot a word."
    args_schema = UpdateWordProgressInput
    
    def _run(self, word: str, quality: int) -> str:
        try:
            from core.services.study.vocabulary_manager import VocabularyManager
            vm = VocabularyManager()
            vm.update_word_progress(word, quality)
            
            # Feedback string
            if quality < 3:
                return f"Marked '{word}' as forgotten. Will review soon."
            else:
                return f"Marked '{word}' as remembered (Quality: {quality})."
        except Exception as e:
            return f"Error updating word progress: {str(e)}"

def register_study_tools(registry):
    """Register all Study tools to the provided registry."""
    registry.register(MathPlotTool())
    registry.register(FileCreationTool())
    registry.register(TextToSpeechTool())
    registry.register(KnowledgeRetrievalTool())
    registry.register(UpdateWordProgressTool())
