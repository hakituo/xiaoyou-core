import os
import json
import random
import math
import time
from typing import List, Dict, Any, Optional
from core.utils.logger import get_logger
from core.tools.study.english.vocabulary_manager import VocabularyManager
from core.tools.study.biology.genetics_calculator import GeneticsCalculator
from core.tools.study.biology.concept_comparison import ConceptComparison
from core.tools.study.chinese.poetry_quiz import PoetryQuiz
from core.tools.study.english.grammar_checker import GrammarChecker
from core.tools.study.geography.climate_judger import ClimateJudger
from core.tools.study.math.problem_generator import MathProblemGenerator
from core.tools.study.math.math_image_generator import MathImageGenerator

logger = get_logger("StudyService")

class StudyService:
    _instance = None

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.data_dir = os.path.join(self.base_dir, "data", "study_data")
        
        # Initialize Tools
        self.vocab_manager = VocabularyManager()
        self.genetics_calculator = GeneticsCalculator()
        self.concept_comparator = ConceptComparison()
        
        # Try to load biology concepts
        bio_concepts_path = os.path.join(self.data_dir, "biology_concepts.json")
        if os.path.exists(bio_concepts_path):
            try:
                with open(bio_concepts_path, 'r', encoding='utf-8') as f:
                    concepts_data = json.load(f)
                    for group in concepts_data:
                        self.concept_comparator.add_concept_group(group)
                logger.info(f"Loaded {len(concepts_data)} biology concept groups")
            except Exception as e:
                logger.warning(f"Failed to load biology concepts: {e}")
        
        self.poetry_quiz = PoetryQuiz()
        # Try to load poetry data
        poetry_path = os.path.join(self.data_dir, "Subjective_Questions", "2010-2022_Chinese_Language_Famous_Passages_and_Sentences_Dictation.json")
        if os.path.exists(poetry_path):
             try:
                self.poetry_quiz.load_poetry(poetry_path)
             except Exception as e:
                logger.warning(f"Failed to load poetry data: {e}")
                
        try:
            self.grammar_checker = GrammarChecker()
        except Exception as e:
            logger.warning(f"Failed to initialize GrammarChecker: {e}")
            self.grammar_checker = None
            
        self.climate_judger = ClimateJudger()
        self.math_generator = MathProblemGenerator()
        try:
            self.math_image_generator = MathImageGenerator()
        except Exception as e:
            logger.warning(f"Failed to initialize MathImageGenerator: {e}")
            self.math_image_generator = None
        
        # Tools Metadata
        self.tools_metadata = {
            "biology": [
                {
                    "id": "genetics_calc",
                    "name": "Genetics Calculator",
                    "desc": "Calculate offspring genotypes for 1-3 gene pairs",
                    "type": "calculator",
                    "inputs": [
                        {"name": "parent1", "label": "Parent 1 Genotype (e.g. AaBb)", "type": "text"},
                        {"name": "parent2", "label": "Parent 2 Genotype (e.g. aaBb)", "type": "text"},
                        {"name": "gene_count", "label": "Gene Pairs", "type": "number", "min": 1, "max": 3}
                    ]
                },
                {
                    "id": "concept_quiz", 
                    "name": "Concept Quiz Generator",
                    "desc": "Generate quiz for biological concepts (Requires loaded concept groups)",
                    "type": "generator",
                    "inputs": [
                         {"name": "count", "label": "Number of Questions", "type": "number", "min": 1, "max": 10}
                    ]
                }
            ],
            "chinese": [
                 {
                    "id": "poetry_quiz", 
                    "name": "Poetry Quiz",
                    "desc": "Test your knowledge of ancient poetry",
                    "type": "quiz",
                    "inputs": [
                        {"name": "count", "label": "Number of Questions", "type": "number", "min": 1, "max": 20}
                    ]
                }
            ],
            "english": [
                {
                    "id": "grammar_check",
                    "name": "Grammar Checker",
                    "desc": "Check English text for grammar errors",
                    "type": "tool",
                    "inputs": [
                        {"name": "text", "label": "Text to Check", "type": "text"}
                    ]
                }
            ],
            "geography": [
                {
                    "id": "climate_judger",
                    "name": "Climate Judger",
                    "desc": "Determine climate type from temperature/precipitation",
                    "type": "calculator",
                    "inputs": [
                        {"name": "temps", "label": "Monthly Temps (°C, comma-separated)", "type": "text"},
                        {"name": "precips", "label": "Monthly Precip (mm, comma-separated)", "type": "text"}
                    ]
                }
            ],
            "math": [
                {
                    "id": "problem_gen",
                    "name": "Problem Generator",
                    "desc": "Generate math problems",
                    "type": "generator",
                    "inputs": [
                        {"name": "module", "label": "Module (e.g. 三角函数, 立体几何)", "type": "text"},
                        {"name": "difficulty", "label": "Difficulty (基础, 中档, 难题)", "type": "text"},
                        {"name": "count", "label": "Count", "type": "number", "min": 1, "max": 10}
                    ]
                },
                {
                    "id": "plot_generator",
                    "name": "Math Plot Generator",
                    "desc": "Generate mathematical plots (Geometry, Functions)",
                    "type": "image_generator",
                    "inputs": [
                        {"name": "type", "label": "Plot Type (e.g. sin, cube, sphere)", "type": "text"},
                        {"name": "params", "label": "Parameters (JSON)", "type": "text"}
                    ]
                }
            ]
        }

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_daily_words(self, count: int = 20) -> List[Dict[str, Any]]:
        """Get a mix of new words and review words"""
        return self.vocab_manager.get_daily_words(count)

    def get_daily_study_summary_data(self) -> Dict[str, Any]:
        """Get summary data for daily study tasks"""
        try:
            # 1. Vocabulary Stats
            vocab_stats = self.get_dictionary_stats()
            
            # 2. Daily Words Preview (just counts)
            # We don't pop them here, just peek or estimate
            daily_quota = 20
            
            # 3. Pending Reviews
            to_review = vocab_stats.get("to_review", 0)
            
            return {
                "date": time.strftime("%Y-%m-%d"),
                "vocab": {
                    "total_learned": vocab_stats.get("learned_words", 0),
                    "to_review": to_review,
                    "daily_quota": daily_quota,
                    "target": f"Review {to_review} words + Learn new words"
                },
                "suggestion": "Focus on vocabulary review first." if to_review > 10 else "Good time to learn new concepts."
            }
        except Exception as e:
            logger.error(f"Failed to get daily summary: {e}")
            return {}

    def get_dictionary_stats(self) -> Dict[str, Any]:
        """Get statistics about the dictionary"""
        total = len(self.vocab_manager.dictionary)
        learned = len(self.vocab_manager.progress)
        # Calculate due reviews
        now = time.time()
        to_review = sum(1 for d in self.vocab_manager.progress.values() if d["next_review"] <= now)
        
        return {
            "total_words": total,
            "learned_words": learned,
            "to_review": to_review
        }

    def get_memory_curve_data(self) -> List[int]:
        """Get real memory curve data (retention rates)"""
        return self.vocab_manager.get_retention_curve()

    def get_mistakes(self) -> List[Dict[str, Any]]:
        """Get high error rate words"""
        return self.vocab_manager.get_mistakes()

    def list_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.tools_metadata

    def run_tool(self, category: str, tool_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific study tool"""
        
        # --- BIOLOGY ---
        if category == "biology":
            if tool_id == "genetics_calc":
                try:
                    p1 = params.get("parent1", "")
                    p2 = params.get("parent2", "")
                    count = int(params.get("gene_count", 1))
                    
                    result = self.genetics_calculator.calculate_offspring(p1, p2, count)
                    formatted_steps = result.get("calculation_steps", [])
                    return {
                        "status": "success",
                        "data": {
                            "offspring_ratios": result.get("genotype_ratios", {}),
                            "phenotypes": result.get("phenotype_ratios", {}),
                            "steps": formatted_steps
                        }
                    }
                except Exception as e:
                    logger.error(f"Genetics Tool Error: {e}")
                    return {"status": "error", "message": str(e)}
            
            elif tool_id == "concept_quiz":
                try:
                    # Note: concept groups must be added first for this to work
                    # Assuming we might want to allow adding groups via params in future
                    questions = self.concept_comparator.generate_test()
                    if not questions:
                        return {"status": "warning", "message": "No concept groups loaded. Please add concepts first."}
                    return {"status": "success", "data": questions}
                except Exception as e:
                    return {"status": "error", "message": str(e)}

        # --- CHINESE ---
        elif category == "chinese":
            if tool_id == "poetry_quiz":
                try:
                    count = int(params.get("count", 20))
                    # Temporary: ensure config matches request
                    self.poetry_quiz.config["question_count"] = count
                    quiz = self.poetry_quiz.generate_quiz()
                    if not quiz:
                        return {"status": "warning", "message": "No poetry data loaded or generation failed."}
                    return {"status": "success", "data": quiz}
                except Exception as e:
                    return {"status": "error", "message": str(e)}

        # --- ENGLISH ---
        elif category == "english":
            if tool_id == "grammar_check":
                if not self.grammar_checker:
                    return {"status": "error", "message": "Grammar Checker not initialized (LanguageTool missing?)"}
                try:
                    text = params.get("text", "")
                    errors = self.grammar_checker.check_text(text)
                    return {"status": "success", "data": errors}
                except Exception as e:
                    return {"status": "error", "message": str(e)}

        # --- GEOGRAPHY ---
        elif category == "geography":
            if tool_id == "climate_judger":
                try:
                    temps_str = params.get("temps", "")
                    precips_str = params.get("precips", "")
                    
                    # Parse CSV strings
                    temps = [float(x.strip()) for x in temps_str.split(",") if x.strip()]
                    precips = [float(x.strip()) for x in precips_str.split(",") if x.strip()]
                    
                    if len(temps) != 12 or len(precips) != 12:
                        return {"status": "error", "message": "Please provide exactly 12 values for temperature and precipitation."}
                        
                    data = {
                        "气温数据": temps,
                        "降水量数据": precips
                    }
                    
                    result = self.climate_judger.judge_climate(data)
                    return {"status": "success", "data": result}
                except ValueError:
                    return {"status": "error", "message": "Invalid number format. Use comma-separated numbers."}
                except Exception as e:
                    return {"status": "error", "message": str(e)}

        # --- MATH ---
        elif category == "math":
            if tool_id == "problem_gen":
                try:
                    module = params.get("module", "三角函数")
                    difficulty = params.get("difficulty", "基础")
                    count = int(params.get("count", 5))
                    
                    problems = self.math_generator.generate_problems(module, difficulty, count)
                    return {"status": "success", "data": problems}
                except Exception as e:
                    return {"status": "error", "message": str(e)}

            elif tool_id == "plot_generator":
                if not self.math_image_generator:
                    return {"status": "error", "message": "Math Image Generator not initialized"}
                
                try:
                    plot_type = params.get("type", "sin")
                    # Parse params if it's a string (which it might be from the frontend input)
                    plot_params = params.get("params", {})
                    if isinstance(plot_params, str):
                        try:
                            plot_params = json.loads(plot_params)
                        except:
                            plot_params = {}

                    # Map simplified type names to Chinese keys used in MathImageGenerator
                    type_map = {
                        "cuboid": "长方体", "cube": "正方体", "cylinder": "圆柱体", 
                        "cone": "圆锥体", "sphere": "球体",
                        "sin": "正弦函数", "cos": "余弦函数", "tan": "正切函数", 
                        "cot": "余切函数", "compound_trig": "复合函数",
                        "ellipse": "椭圆", "hyperbola": "双曲线", "parabola": "抛物线", "circle": "圆"
                    }
                    
                    # Also allow direct Chinese input or fallback
                    mapped_type = type_map.get(plot_type, plot_type)
                    
                    # Find the generator method
                    method = None
                    for category_dict in self.math_image_generator.image_types.values():
                        if mapped_type in category_dict:
                            method = category_dict[mapped_type]
                            break
                    
                    if not method:
                         return {"status": "error", "message": f"Unknown plot type: {plot_type}"}
                         
                    fig = method(plot_params)
                    
                    # Save image
                    static_dir = os.path.join(self.base_dir, "static", "images", "generated")
                    os.makedirs(static_dir, exist_ok=True)
                    filename = f"math_plot_{plot_type}_{int(time.time())}.png"
                    filepath = os.path.join(static_dir, filename)
                    
                    fig.savefig(filepath)
                    
                    # Return relative path for frontend
                    relative_path = f"/static/images/generated/{filename}"
                    return {"status": "success", "data": {"image_url": relative_path, "filepath": filepath}}
                    
                except Exception as e:
                    return {"status": "error", "message": str(e)}

        return {"status": "error", "message": "Tool not implemented or supported in Web API yet"}

def get_study_service():
    return StudyService.get_instance()
