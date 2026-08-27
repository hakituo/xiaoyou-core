from typing import Any, Dict, List


def build_tools_metadata() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "english": [
            {
                "id": "word_quiz",
                "name": "Word Quiz",
                "desc": "Quiz English words from recent daily logs, the long-term unfamiliar book, or both sources separately",
                "type": "quiz",
                "inputs": [
                    {
                        "name": "source",
                        "label": "Source (daily / unfamiliar / both)",
                        "type": "text",
                    },
                    {
                        "name": "count",
                        "label": "Number of Words to Quiz",
                        "type": "number",
                        "min": 1,
                        "max": 20,
                    },
                    {
                        "name": "priority",
                        "label": "Priority (high_count / random / new)",
                        "type": "text",
                    },
                    {
                        "name": "days",
                        "label": "For source=daily: optional recent N days (omit = yesterday)",
                        "type": "number",
                        "min": 1,
                        "max": 90,
                    },
                    {
                        "name": "date",
                        "label": "For source=daily: target date (YYYY/MM/DD)",
                        "type": "text",
                    },
                ],
            },
        ],
        "study_data": [
            {
                "id": "manage",
                "name": "Study Data Management",
                "desc": "Read/Write study records and history in the study folder",
                "type": "file_tool",
                "inputs": [
                    {"name": "action", "label": "Action", "type": "text"},
                    {"name": "path", "label": "Path", "type": "text"},
                ],
            }
        ],
    }


def build_subject_profiles() -> List[Dict[str, Any]]:
    return [
        {"subject": "english", "display_name": "英语", "focus_hint": "词汇、阅读与表达"},
        {"subject": "math", "display_name": "数学", "focus_hint": "题型训练与错题复盘"},
        {"subject": "chinese", "display_name": "语文", "focus_hint": "古诗文与语言表达"},
        {"subject": "biology", "display_name": "生物", "focus_hint": "概念辨析与遗传计算"},
        {"subject": "geography", "display_name": "地理", "focus_hint": "气候判读与地图思维"},
        {"subject": "general", "display_name": "综合", "focus_hint": "学习执行与总结整理"},
    ]
