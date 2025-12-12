import json
import os
import time
import math
import random
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from core.utils.logger import get_logger

# Import DataIO for compatibility with vocab_tester formats
try:
    from core.tools.study.common.data_io import DataIO
except ImportError:
    DataIO = None

logger = get_logger("VocabularyManager")

class VocabularyManager:
    def __init__(self, dictionary_path: str = None, progress_path: str = None):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        
        # Default paths
        if not dictionary_path:
            self.dictionary_path = os.path.join(self.base_dir, "data", "study_data", "English_words", "CET4-顺序.json")
        else:
            self.dictionary_path = dictionary_path
            
        if not progress_path:
            self.progress_dir = os.path.join(self.base_dir, "output", "user_data")
            os.makedirs(self.progress_dir, exist_ok=True)
            self.progress_path = os.path.join(self.progress_dir, "vocab_progress.json")
        else:
            self.progress_path = progress_path
            
        self.dictionary = []
        self.progress = {}
        self._load_data()

    def _load_data(self):
        """Load dictionary and user progress"""
        try:
            # Load dictionary
            if os.path.exists(self.dictionary_path):
                with open(self.dictionary_path, 'r', encoding='utf-8') as f:
                    self.dictionary = json.load(f)
                logger.info(f"Loaded {len(self.dictionary)} words from {self.dictionary_path}")
            else:
                logger.error(f"Dictionary file not found: {self.dictionary_path}")
                self.dictionary = []

            # Load progress
            if os.path.exists(self.progress_path):
                with open(self.progress_path, 'r', encoding='utf-8') as f:
                    self.progress = json.load(f)
                logger.info(f"Loaded progress for {len(self.progress)} words")
            else:
                self.progress = {}
                
        except Exception as e:
            logger.error(f"Failed to load vocabulary data: {e}")

    def import_from_file(self, file_path: str) -> int:
        """
        Import vocabulary from external file (Excel/TXT) using DataIO.
        Compatible with vocab_tester format.
        Returns number of new words added.
        """
        if not DataIO:
            logger.warning("DataIO not available, cannot import external files")
            return 0
            
        try:
            data = DataIO.import_data(file_path)
            if not data:
                return 0
                
            # Convert to internal format
            new_words = []
            for item in data:
                # Basic mapping from vocab_tester format (Excel/CSV usually has Chinese headers)
                if isinstance(item, dict):
                    word = item.get("单词") or item.get("word")
                    meaning = item.get("中文释义") or item.get("meaning") or item.get("translation")
                    pos = item.get("词性", "") or item.get("pos", "")
                    
                    if word and meaning:
                        new_words.append({
                            "word": str(word).strip(),
                            "translations": [{"type": str(pos).strip(), "translation": str(meaning).strip()}]
                        })
            
            # Merge into dictionary (avoid duplicates)
            existing_words = {w['word'] for w in self.dictionary}
            count = 0
            for w in new_words:
                if w['word'] not in existing_words:
                    self.dictionary.append(w)
                    existing_words.add(w['word'])
                    count += 1
            
            if count > 0:
                logger.info(f"Imported {count} new words from {file_path}")
                # We don't save back to the base JSON to avoid polluting the source, 
                # but in a real app we might want to save to a user dictionary.
                # For now, these are in-memory for this session or we could save to a separate file.
            
            return count
        except Exception as e:
            logger.error(f"Failed to import data: {e}")
            return 0

    def _save_progress(self):
        """Save user progress to disk"""
        try:
            with open(self.progress_path, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save vocabulary progress: {e}")

    def get_word_info(self, word: str) -> Optional[Dict]:
        """Get full dictionary entry for a word"""
        for entry in self.dictionary:
            if entry['word'] == word:
                return entry
        return None

    def get_daily_words(self, limit: int = 20) -> List[Dict]:
        """
        Get a mix of review words and new words for the day.
        Priority: Overdue reviews > New words
        """
        now = time.time()
        due_words = []
        
        # 1. Find due words
        for word, data in self.progress.items():
            if data['next_review'] <= now:
                word_info = self.get_word_info(word)
                if word_info:
                    due_words.append({
                        **word_info,
                        "status": "review",
                        "due_time": data['next_review']
                    })
        
        # Sort by due time (most overdue first)
        due_words.sort(key=lambda x: x['due_time'])
        
        result = due_words[:limit]
        
        # 2. Fill remaining quota with new words
        if len(result) < limit:
            remaining = limit - len(result)
            new_words = []
            
            # Find words not in progress
            known_words = set(self.progress.keys())
            
            # Simple sequential strategy for now (can be randomized or based on frequency if available)
            # Iterate through dictionary to find unseen words
            count = 0
            for entry in self.dictionary:
                if entry['word'] not in known_words:
                    new_words.append({
                        **entry,
                        "status": "new"
                    })
                    count += 1
                    if count >= remaining:
                        break
            
            result.extend(new_words)
            
        return result

    def update_word_progress(self, word: str, quality: int):
        """
        Update word progress using SM-2 algorithm
        quality: 0-5 (0=complete blackout, 5=perfect recall)
        """
        if word not in self.progress:
            # Initialize new word
            self.progress[word] = {
                "reps": 0,
                "interval": 0,
                "easiness": 2.5,
                "next_review": 0,
                "history": []
            }
            
        data = self.progress[word]
        
        # Update history
        data["history"].append({
            "timestamp": time.time(),
            "quality": quality
        })
        
        # SM-2 Algorithm
        if quality >= 3:
            if data["reps"] == 0:
                data["interval"] = 1
            elif data["reps"] == 1:
                data["interval"] = 6
            else:
                data["interval"] = round(data["interval"] * data["easiness"])
            
            data["reps"] += 1
            data["easiness"] += (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            if data["easiness"] < 1.3:
                data["easiness"] = 1.3
        else:
            data["reps"] = 0
            data["interval"] = 1
            
        data["next_review"] = time.time() + data["interval"] * 86400
        self._save_progress()
        
    def get_mistakes(self, limit: int = 20) -> List[Dict]:
        """Get words with high error rates"""
        mistake_counts = []
        
        for word, data in self.progress.items():
            errors = sum(1 for h in data.get("history", []) if h["quality"] < 3)
            if errors > 0:
                mistake_counts.append({
                    "word": word,
                    "error_count": errors,
                    "last_error": data.get("history", [])[-1]["timestamp"] if data.get("history") else 0
                })
        
        # Sort by error count descending
        mistake_counts.sort(key=lambda x: x["error_count"], reverse=True)
        
        # Get full details
        result = []
        for m in mistake_counts[:limit]:
            info = self.get_word_info(m["word"])
            if info:
                result.append({
                    **m,
                    "translations": info.get("translations", [])
                })
        
        return result

    def get_retention_curve(self) -> List[int]:
        """
        Calculate retention curve based on user's average stability/easiness.
        Returns projected retention % for days 1-7.
        """
        if not self.progress:
            return [100, 80, 60, 45, 35, 28, 25] # Default Ebbinghaus
            
        # Calculate average easiness
        total_easiness = sum(d["easiness"] for d in self.progress.values())
        avg_easiness = total_easiness / len(self.progress)
        
        # Calculate average interval (stability)
        total_interval = sum(d["interval"] for d in self.progress.values())
        avg_interval = total_interval / len(self.progress)
        
        # If user is advanced (high interval), curve is flatter
        # If user is struggling (low easiness), curve drops faster
        
        # Simplified projection model
        curve = []
        for day in range(1, 8): # Days 0 to 6? Frontend shows 7 bars.
            # R = e^(-t/S)
            # We scale S by avg_easiness/2.5 to account for difficulty
            
            # Use a blended stability factor: avg_interval (long term) + avg_easiness (inherent)
            # For new users, avg_interval is ~1.
            stability = max(1.0, avg_interval * 0.5 + (avg_easiness - 2.5) * 5)
            
            retention = math.exp(-day / stability) * 100
            curve.append(min(100, max(5, int(retention))))
            
        # Normalize first day to near 100 if it's too low? No, let it reflect reality.
        # But for UI consistency, maybe Day 0 is 100.
        # Frontend shows 7 bars. Let's assume they are Day 1-7.
        
        return curve

    def get_stats(self) -> Dict:
        """Get learning statistics"""
        total_learned = len(self.progress)
        due_count = sum(1 for d in self.progress.values() if d['next_review'] <= time.time())
        mastered_count = sum(1 for d in self.progress.values() if d['interval'] > 21) # Interval > 3 weeks considered mastered
        
        return {
            "total_words": len(self.dictionary),
            "learned_words": total_learned,
            "due_words": due_count,
            "mastered_words": mastered_count
        }

    # --- Added from VocabTester for unification ---

    def get_weak_words(self, limit: int = 50) -> List[Dict]:
        """
        Get list of weak words (interval < 3 days or recently failed).
        """
        weak_words = []
        for word, data in self.progress.items():
            # Criteria for weak words:
            # 1. Interval is small (e.g. < 3 days) and has been repped at least once
            # 2. Quality of last review was < 3
            is_weak = False
            if data['interval'] < 3 and data['reps'] > 0:
                is_weak = True
            elif data['history'] and data['history'][-1]['quality'] < 3:
                is_weak = True
                
            if is_weak:
                word_info = self.get_word_info(word)
                if word_info:
                    weak_words.append({
                        **word_info,
                        "stats": data
                    })
        
        # Sort by interval (ascending - worst first)
        weak_words.sort(key=lambda x: x['stats']['interval'])
        return weak_words[:limit]

    def generate_quiz(self, mode: str = "multiple_choice", count: int = 20, source: str = "all") -> List[Dict]:
        """
        Generate quiz questions.
        mode: "multiple_choice" (看词选义), "dictation" (看义写词/听写)
        source: "all" (random), "weak" (weak words), "due" (due for review)
        """
        # 1. Select words
        pool = []
        if source == "weak":
            pool = self.get_weak_words(limit=100)
        elif source == "due":
            pool = self.get_daily_words(limit=100) # This returns a mix
        else:
            pool = self.dictionary

        if not pool:
            pool = self.dictionary
            
        count = min(count, len(pool))
        if count == 0:
            return []
            
        selected_words = random.sample(pool, count)
        questions = []
        
        for word_data in selected_words:
            q = self._generate_single_question(word_data, mode)
            if q:
                questions.append(q)
                
        return questions

    def _generate_single_question(self, word_data: Dict, mode: str) -> Dict:
        """Generate a single question for a word"""
        word = word_data['word']
        translations = word_data.get('translations', [])
        if not translations:
            return None
            
        correct_meaning = "; ".join([f"{t.get('type')}. {t.get('translation')}" for t in translations])
        
        if mode == "multiple_choice" or mode == "看词选义":
            # Generate distractors
            options = [correct_meaning]
            
            # Find distractors from other words
            distractors = []
            while len(distractors) < 3:
                other = random.choice(self.dictionary)
                if other['word'] != word:
                    other_trans = other.get('translations', [])
                    if other_trans:
                        meaning = "; ".join([f"{t.get('type')}. {t.get('translation')}" for t in other_trans])
                        if meaning not in options and meaning not in distractors:
                            distractors.append(meaning)
            
            options.extend(distractors)
            random.shuffle(options)
            
            return {
                "type": "multiple_choice",
                "question": word,
                "options": options,
                "answer": correct_meaning,
                "word_data": word_data
            }
            
        elif mode == "dictation" or mode == "看义写词":
            return {
                "type": "dictation",
                "question": correct_meaning,
                "answer": word,
                "word_data": word_data
            }
            
        return None

    def check_quiz_answer(self, question: Dict, user_answer: str) -> Dict:
        """
        Check answer and update progress.
        Returns result dict.
        """
        is_correct = False
        correct_answer = question['answer']
        word = question['word_data']['word']
        
        if question['type'] == "multiple_choice":
            is_correct = (user_answer == correct_answer)
        else:
            # For dictation, case-insensitive, trim
            is_correct = (user_answer.strip().lower() == correct_answer.strip().lower())
            
        # Update progress
        # If correct, quality=4 (Good). If wrong, quality=1 (Wrong).
        # We can be more nuanced if we had response time, but for now simple mapping.
        quality = 4 if is_correct else 1
        self.update_word_progress(word, quality)
        
        return {
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "user_answer": user_answer,
            "word": word
        }

    def get_memory_curve_data(self) -> Dict:
        """
        Generate data for memory curve / study planning.
        """
        stats = self.get_stats()
        weak_words = self.get_weak_words(limit=1000)
        
        # Calculate future review distribution
        # Group by day
        future_reviews = {}
        now = time.time()
        for data in self.progress.values():
            if data['next_review'] > now:
                # Days from now
                days = math.ceil((data['next_review'] - now) / (24 * 3600))
                if days < 0: days = 0 # Should not happen if > now
                if days not in future_reviews:
                    future_reviews[days] = 0
                future_reviews[days] += 1
                
        # Sort by day
        future_review_list = [{"day": d, "count": c} for d, c in sorted(future_reviews.items()) if d <= 30] # Limit to 30 days
        
        return {
            "stats": stats,
            "weak_word_count": len(weak_words),
            "future_reviews": future_review_list,
            "review_advice": [
                {
                    "word": w['word'], 
                    "next_review": datetime.fromtimestamp(w['stats']['next_review']).strftime("%Y-%m-%d %H:%M:%S")
                } 
                for w in weak_words[:10]
            ]
        }
