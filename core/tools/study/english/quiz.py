"""测验生成与每日取词层（解耦自 VocabularyManager）。

职责：
- get_daily_words：FSRS 到期词 + 昨天 daily 错词，合并去重
- generate_quiz / _generate_single_question / check_quiz_answer
- add_to_learning：手动加入学习列表

依赖 VocabDataStore 提供数据，依赖 fsrs_scheduler.apply_progress 写进度。
"""

import random
import time
from datetime import timedelta
from typing import Dict, List, Any

from core.utils.logger import get_logger

logger = get_logger("VocabQuiz")


def get_new_words(store, count: int = 20, order: str = "sequential") -> List[Dict[str, Any]]:
    """从当前词书取「从未学过」的新词。

    新词 = dictionary 中存在但 progress 中不存在的词。
    按 order 排序：sequential(词书原序) / shuffle(乱序)。
    返回的词标记 status="new"，含完整释义和例句。
    """
    store._ensure_loaded()
    if not store.dictionary:
        return []

    # 排除已在 progress 里的词（已学过）
    learned_keys = {w.lower() for w in store.progress.keys()}
    new_pool: List[Dict[str, Any]] = []
    for entry in store.dictionary:
        word = entry.get("word", "")
        if not word or word.lower() in learned_keys:
            continue
        sentence_info = store.get_sentence_info(word)
        new_pool.append(
            {
                **entry,
                **(
                    {"sentences": sentence_info.get("sentences", [])}
                    if sentence_info and sentence_info.get("sentences")
                    else {}
                ),
                "status": "new",
            }
        )

    if order == "shuffle":
        random.shuffle(new_pool)
    # sequential 保持词书原序

    return new_pool[:count] if count > 0 else new_pool


def get_daily_words(store, limit: int = 0, order: str = "sequential") -> List[Dict[str, Any]]:
    """获取每日复习词列表（FSRS 调度 + 昨天错词回看）。

    复习来源分两档，合并去重、不设上限（limit=0）：
      1) 优先「昨天的 daily/YYYY/MM/DD.txt」日志里的生词（按不认识次数降序）；
      2) 再补 FSRS 已到期（due <= now）的词（长期抗遗忘闭环）。
    传入正数 limit 则最多返回 limit 个。
    """
    store._ensure_loaded()
    result: List[Dict[str, Any]] = []
    used_words: set = set()  # 跨来源去重

    # 每次取词都兜底确保当天 daily 日志文件存在
    try:
        from .daily_word_log import get_daily_word_log

        get_daily_word_log().ensure_today_file()
    except Exception:
        pass

    # --- 第一阶段：昨天 daily 日志里的生词（按不认识次数降序）---
    try:
        from .daily_word_log import get_daily_word_log
        from core.utils.time_utils import get_current_time

        log = get_daily_word_log()
        yesterday = get_current_time().date() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y/%m/%d")
        recent_words = log.get_words_for_date(yesterday_str)

        if recent_words:
            for w in recent_words:
                w.setdefault("unknown_count", 0)
            # 不再按 unknown_count 降序选词：少数高频错词会因此长期钉在队首，
            # 体感像「固定生词本」，也违背「看昨天不会的单词」的诉求。
            # 改为按 daily 文件自然记录顺序（≈当天首次标记不认识的顺序），
            # 同词去重，使每日复习集合更均衡、慢性错词也能轮到但不独霸队首。
            seen_order: set = set()
            ordered: list = []
            for w in recent_words:
                key = w["word"].strip().lower()
                if key in seen_order:
                    continue
                seen_order.add(key)
                ordered.append(w)
            if order == "random":
                random.shuffle(ordered)
            # sequential：保持自然顺序

            for w in ordered:
                if limit and len(result) >= limit:
                    break
                key = w["word"].lower()
                if key in used_words:
                    continue
                word_info = store.get_word_info(w["word"])
                if not word_info:
                    # 词书里查不到（如未收录的生词）：仍按 daily 文件原样加入，
                    # 保证「昨天文件里给的词都出现」，不静默丢弃
                    word_info = {
                        "word": w["word"],
                        "translations": [{"type": "", "translation": "(词库未收录，待补充)"}],
                    }
                sentence_info = store.get_sentence_info(w["word"])
                result.append(
                    {
                        **word_info,
                        **(
                            {"sentences": sentence_info.get("sentences", [])}
                            if sentence_info and sentence_info.get("sentences")
                            else {}
                        ),
                        "status": "review",
                        "unknown_count": w["unknown_count"],
                    }
                )
                used_words.add(key)
    except Exception as e:
        logger.warning(f"从昨天 daily 日志取复习词失败: {e}")

    # --- 第二阶段：FSRS 已到期且「非今天刚复习过」的词（长期抗遗忘闭环）---
    # 排除今天 last_review 的词：刚 Again/刚学的词今天不再立刻重排进下一轮，
    # 避免「一直学到会为止」的体感；它们按 FSRS 调度明天/更晚才再次出现。
    try:
        now = time.time()
        today_start = now - (now % 86400)  # 当天 0 点时间戳（近似，仅用于排除今日刚复习）
        due_pool: List[Dict[str, Any]] = []
        for word, data in store.progress.items():
            due_ts = data.get("fsrs_due") or data.get("next_review", 0)
            if not due_ts or due_ts > now:
                continue
            last_review = data.get("fsrs_last_review") or 0
            if last_review and last_review >= today_start:
                continue  # 今天已复习过，跳过
            key = word.lower()
            if key in used_words:
                continue
            word_info = store.get_word_info(word)
            if not word_info:
                continue
            sentence_info = store.get_sentence_info(word)
            due_pool.append(
                {
                    **word_info,
                    **(
                        {"sentences": sentence_info.get("sentences", [])}
                        if sentence_info and sentence_info.get("sentences")
                        else {}
                    ),
                    "status": "review",
                    "due_time": due_ts,
                }
            )
        due_pool.sort(key=lambda x: x["due_time"])
        for w in due_pool:
            if limit and len(result) >= limit:
                break
            key = w["word"].lower()
            if key in used_words:
                continue
            result.append(w)
            used_words.add(key)
    except Exception as e:
        logger.warning(f"从 FSRS 到期队列取复习词失败: {e}")

    return result


def generate_quiz(store, mode: str = "multiple_choice", count: int = 20,
                  source: str = "all") -> List[Dict]:
    store._ensure_loaded()
    pool = []
    if source == "weak":
        pool = _get_weak_words(store, limit=100)
    elif source == "due":
        pool = get_daily_words(store, limit=100)
    else:
        pool = store.dictionary

    if not pool:
        pool = store.dictionary

    count = min(count, len(pool))
    if count == 0:
        return []

    selected_words = random.sample(pool, count)
    questions = []
    for word_data in selected_words:
        q = _generate_single_question(store, word_data, mode)
        if q:
            questions.append(q)
    return questions


def _generate_single_question(store, word_data: Dict, mode: str) -> Dict:
    word = word_data["word"]
    translations = word_data.get("translations", [])
    if not translations:
        return None

    correct_meaning = "; ".join(
        [f"{t.get('type')}. {t.get('translation')}" for t in translations]
    )

    if mode == "multiple_choice" or mode == "看词选义":
        options = [correct_meaning]
        distractors = []
        while len(distractors) < 3:
            other = random.choice(store.dictionary)
            if other["word"] != word:
                other_trans = other.get("translations", [])
                if other_trans:
                    meaning = "; ".join(
                        [f"{t.get('type')}. {t.get('translation')}" for t in other_trans]
                    )
                    if meaning not in options and meaning not in distractors:
                        distractors.append(meaning)
        options.extend(distractors)
        random.shuffle(options)
        return {
            "type": "multiple_choice",
            "question": word,
            "options": options,
            "answer": correct_meaning,
            "word_data": word_data,
        }
    elif mode == "dictation" or mode == "看义写词":
        return {
            "type": "dictation",
            "question": correct_meaning,
            "answer": word,
            "word_data": word_data,
        }
    return None


def check_quiz_answer(store, question: Dict, user_answer: str) -> Dict:
    """检查答案并更新进度。正确 quality=4，错误 quality=1。"""
    from .fsrs_scheduler import apply_progress

    is_correct = False
    correct_answer = question["answer"]
    word = question["word_data"]["word"]

    if question["type"] == "multiple_choice":
        is_correct = user_answer == correct_answer
    else:
        is_correct = user_answer.strip().lower() == correct_answer.strip().lower()

    quality = 4 if is_correct else 1
    apply_progress(store, word, quality)

    return {
        "is_correct": is_correct,
        "correct_answer": correct_answer,
        "user_answer": user_answer,
        "word": word,
    }


def add_to_learning(store, word: str) -> bool:
    store._ensure_loaded()
    if word in store.progress:
        return True  # Already in learning list
    word_info = store.get_word_info(word)
    if word_info:
        store.progress[word] = {
            "reps": 0,
            "interval": 0,
            "easiness": 2.5,
            "next_review": time.time(),  # Review immediately
            "history": [],
        }
        store.save_progress()
        return True
    return False


def _get_weak_words(store, limit: int = 50) -> List[Dict]:
    """内部弱词筛选（供 generate_quiz 复用，避免与 stats 循环依赖）。"""
    store._ensure_loaded()
    weak_words = []
    for word, data in store.progress.items():
        is_weak = False
        if data["interval"] < 3 and data["reps"] > 0:
            is_weak = True
        elif data["history"] and data["history"][-1]["quality"] < 3:
            is_weak = True
        if is_weak:
            word_info = store.get_word_info(word)
            if word_info:
                weak_words.append({**word_info, "stats": data})
    weak_words.sort(key=lambda x: x["stats"]["interval"])
    return weak_words[:limit]
