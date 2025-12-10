import re
from typing import Optional, Tuple

def extract_and_strip_emotion(content: str) -> Tuple[str, Optional[str]]:
    """
    从回复中提取情绪标签 [EMO: emotion] 或 [emotion]
    返回: (content_without_tag, emotion_label)
    """
    # 1. 优先匹配 [EMO: label] 或 [EMO: {label}]
    pattern1 = r"\[EMO:\s*\{?\s*([a-zA-Z0-9_\u4e00-\u9fa5]+)\s*\}?\]"
    match = re.search(pattern1, content)
    if match:
        emotion = match.group(1)
        new_content = re.sub(pattern1, "", content).strip()
        return new_content, emotion

    # 2. 尝试匹配 [label] 格式 (仅限常见情绪词，避免误伤)
    # 常用情绪关键词列表
    emotion_keywords = r"(happy|neutral|angry|excited|lost|wronged|jealous|coquetry|shy|calm|sad|depressed|joy|开心|愉快|高兴|满足|喜悦|生气|愤怒|火大|暴躁|烦|不爽|兴奋|激动|期待|热情|亢奋|委屈|难过|伤心|失落|沮丧|低落|嫉妒|吃醋|傲娇|撒娇|害羞|羞涩|脸红|平静|中性|冷淡|冷静)"
    pattern2 = r"\[(" + emotion_keywords + r")\]"
    match2 = re.search(pattern2, content, re.IGNORECASE)
    if match2:
        emotion = match2.group(1)
        new_content = re.sub(pattern2, "", content).strip()
        return new_content, emotion
        
    return content, None
