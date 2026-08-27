"""
Stream Utils - 流式输出工具模块

临时实现：提供基本功能以修复导入错误
TODO: 完整实现各个模块（参见 README.md）
"""
import re
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

# 注：get_bert_analyzer 已改为 detect_wants_long 方法内延迟 import，
# 避免启动期触发 bert_runtime_mixin 顶层 import bert_engine_py（17 秒 C++ 扩展加载）


# ============================================================================
# 文本工具函数
# ============================================================================

def normalize_tilde_ending(text: str) -> str:
    """规范化波浪号结尾，将多个波浪号替换为单个"""
    if not text:
        return text
    # 将连续的波浪号替换为单个
    text = re.sub(r'~+$', '~', text)
    return text


def looks_formal_user_text(text: str) -> bool:
    """判断用户文本是否看起来正式"""
    if not text:
        return False
    # 简单判断：包含"请"、"您"等正式用语
    formal_markers = ['请', '您', '敬请', '恳请', '烦请']
    return any(marker in text for marker in formal_markers)


def looks_mostly_english(text: str) -> bool:
    """判断文本是否主要是英文"""
    if not text:
        return False
    # 统计ASCII字符比例
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return ascii_count / len(text) > 0.7


def find_stream_boundary(text: str, min_chars: int = 1, max_chars: int = 100) -> int:
    """查找流式输出的边界位置（句号、问号等）"""
    if len(text) < min_chars:
        return -1
    
    # 查找标点符号
    boundaries = ['.', '。', '!', '！', '?', '？', '\n']
    for i, char in enumerate(text):
        if i >= min_chars and char in boundaries:
            return i + 1
    
    # 如果超过max_chars，强制断句
    if len(text) >= max_chars:
        return max_chars
    
    return -1


# ============================================================================
# 图片检测
# ============================================================================

async def extract_image_request_prompt(message: str) -> Optional[str]:
    """提取图片请求的提示词"""
    if not message:
        return None
    text = str(message).strip()
    if not text:
        return None

    lowered = text.lower()

    negative_patterns = [
        r"画什么画",
        r"画了",
        r"画过",
        r"画完",
        r"画的",
        r"画出来",
        r"画好",
        r"画得",
        r"画着",
        r"在画什么",
        r"你到底在画什么",
        r"你画个什么",
        r"你画什么东西",
        r"别.*画",
        r"不要.*画",
        r"不(要|用|想|必).*画",
        r"别给我画",
        r"别再画",
        r"别画了",
        r"你会画画吗",
        r"画质",
        r"画面",
        r"看你画",
        r"给他画",
        r"给她画",
        r"给我画了",
        r"画[^，。！？\n]{0,6}画",
    ]
    for pat in negative_patterns:
        if re.search(pat, text) or re.search(pat, lowered):
            return None

    image_keywords = ['生成图片', '生成一张', '画一张', '画一只', '画一个', '画个', '画只', '画一幅', '画下', 'draw', 'generate image']

    for keyword in image_keywords:
        if keyword in lowered:
            idx = lowered.find(keyword)
            before = text[:idx]
            after = text[idx + len(keyword):]

            if keyword in ('画个', '画一张', '画一只', '画一个', '画只', '画一幅', '画下'):
                if re.search(r'[了过完得着]$', before):
                    return None

            prompt = after.strip()
            prompt = re.sub(r'^(一个|一张|一只|一幅|图片|图像)', '', prompt).strip()
            if prompt and not re.search(r"^(什么|啥|怎么|为何|为什么|为啥)(画|图)?$", prompt):
                if len(prompt) > 100:
                    return None
                return prompt

    return None


# ============================================================================
# 动态填充词（自然度增强）
# ============================================================================

DYNAMIC_FILLERS = [
    "嗯...", "让我想想...", "这个嘛...", "呃...", "那个..."
]

FILLER_BLOCK_RE = re.compile(r'\[FILLER:([^\]]+)\]')


# ============================================================================
# 流式文本平滑器
# ============================================================================

class StreamTextSmoother:
    """流式文本平滑器 - 控制输出速度和断句"""
    
    def __init__(
        self,
        enabled: bool = False,
        min_chars: int = 1,
        hard_chars: int = 1,
        max_delay_ms: int = 0
    ):
        self.enabled = enabled
        self.min_chars = min_chars
        self.hard_chars = hard_chars
        self.max_delay_ms = max_delay_ms
        self.buffer = ""
    
    def push(self, text: str, force: bool = False) -> List[str]:
        """推送文本，返回可以输出的chunks"""
        if not self.enabled or force:
            # 禁用模式：直接透传
            return [text] if text else []
        
        self.buffer += text
        chunks = []
        
        # 查找边界
        while len(self.buffer) >= self.min_chars:
            boundary = find_stream_boundary(
                self.buffer,
                min_chars=self.min_chars,
                max_chars=self.hard_chars
            )
            
            if boundary > 0:
                chunks.append(self.buffer[:boundary])
                self.buffer = self.buffer[boundary:]
            else:
                break
        
        return chunks
    
    def drain(self) -> str:
        """清空缓冲区，返回剩余内容"""
        remaining = self.buffer
        self.buffer = ""
        return remaining


# ============================================================================
# 上下文构建器
# ============================================================================

class StreamContextBuilder:
    """上下文构建器 - 模式检测和参数推断"""
    
    @staticmethod
    async def detect_sensitive_mode(
        agent: Any,
        user_id: str,
        message: str,
        system_prompt: Optional[str] = None
    ) -> bool:
        """检测是否为敏感模式"""
        # 简单实现：检查是否包含敏感关键词
        sensitive_keywords = ['隐私', '密码', '敏感', '机密']
        return any(kw in message for kw in sensitive_keywords)
    
    @staticmethod
    def detect_mode(agent: Any, message: str) -> str:
        """检测对话模式"""
        # 简单实现：返回默认模式
        return "chat"
    
    @staticmethod
    def detect_wants_long(message: str) -> bool:
        """检测用户是否想要长回复"""
        msg = str(message or "")
        if not msg.strip():
            return False
        msg_lower = msg.lower()
        try:
            # 延迟 import：避免启动期触发 bert_runtime_mixin 顶层 import bert_engine_py（17 秒 C++ 扩展加载）
            from core.services.data_ops.bert_analyzer import get_bert_analyzer
            result = get_bert_analyzer().analyze_intent(
                msg,
                candidates=[
                    "REQUEST_DETAILED_EXPLANATION",
                    "EMOTIONAL_SUPPORT",
                    "NONE",
                ],
            )
            intent = str((result or {}).get("intent") or "").strip().upper()
            confidence = float((result or {}).get("confidence") or 0.0)
            if intent in {"REQUEST_DETAILED_EXPLANATION", "EMOTIONAL_SUPPORT"} and confidence >= 0.58:
                return True
        except Exception:
            pass
        long_indicators = [
            "详细",
            "为什么",
            "具体",
            "完整",
            "全面",
            "detail",
            "elaborate",
            "安慰",
            "开导",
            "鼓励",
            "我很难受",
            "我好焦虑",
            "我崩溃了",
            "我想哭",
            "我很委屈",
            "我很难过",
            "失恋",
        ]
        return any(indicator in msg_lower for indicator in long_indicators)
    
    @staticmethod
    def infer_max_tokens(
        mode: str,
        is_sensitive_mode: bool,
        is_system_event: bool,
        wants_long: bool,
        pref_length: str,
        max_tokens: Optional[int] = None
    ) -> Optional[int]:
        """推断max_tokens，默认不限制输出长度"""
        if max_tokens:
            return max_tokens

        # 不设上限，由模型自行决定输出长度
        return None
    
    @staticmethod
    def infer_soft_reply_limit(
        mode: str,
        wants_long: bool,
        is_system_event: bool,
        message: str
    ) -> int:
        """推断软性回复字符限制"""
        if wants_long:
            return 1000
        elif is_system_event:
            return 300
        else:
            return 50  # 默认简短回复，符合角色设定


# ============================================================================
# 标签解析器
# ============================================================================

class TagParser:
    """标签解析器 - 处理 [EMO:], [GEN_IMG:] 等标签"""
    
    MARKER_EMOTION = "[EMO:"
    MARKER_IMAGE = "[GEN_IMG:"
    MARKER_THINK = "[THINK:"
    MARKER_TOPIC = "[TOPIC:"
    
    def __init__(self):
        self.in_emo_tag = False
        self.in_img_tag = False
        self.in_think_tag = False
        self.in_topic_tag = False
        
        self.emo_buffer = ""
        self.img_buffer = ""
        self.think_buffer = ""
        self.topic_buffer = ""
        
        self.collected_image_prompts: List[str] = []
        self.collected_think_store: List[str] = []
        self.extracted_topics: List[str] = []
    
    def is_parsing_tag(self) -> bool:
        """是否正在解析标签"""
        return (self.in_emo_tag or self.in_img_tag or 
                self.in_think_tag or self.in_topic_tag)
    
    def find_next_tag(self, text: str) -> Tuple[int, str]:
        """查找下一个标签的位置和类型"""
        markers = {
            self.MARKER_EMOTION: "emo",
            self.MARKER_IMAGE: "img",
            self.MARKER_THINK: "think",
            self.MARKER_TOPIC: "topic"
        }
        
        min_idx = len(text)
        found_type = ""
        
        for marker, tag_type in markers.items():
            idx = text.find(marker)
            if idx != -1 and idx < min_idx:
                min_idx = idx
                found_type = tag_type
        
        if found_type:
            return min_idx, found_type
        return -1, ""
    
    def start_tag(self, tag_type: str, text: str, marker_len: int) -> str:
        """开始解析标签，返回剩余文本"""
        if tag_type == "emo":
            self.in_emo_tag = True
            self.emo_buffer = ""
        elif tag_type == "img":
            self.in_img_tag = True
            self.img_buffer = ""
        elif tag_type == "think":
            self.in_think_tag = True
            self.think_buffer = ""
        elif tag_type == "topic":
            self.in_topic_tag = True
            self.topic_buffer = ""
        
        return text[marker_len:]
    
    def parse_emotion_tag(self, text: str) -> Tuple[bool, str, str]:
        """解析情感标签，返回 (是否完成, 剩余文本, 情感值)"""
        self.emo_buffer += text
        close_idx = self.emo_buffer.find(']')
        
        if close_idx != -1:
            emotion = self.emo_buffer[:close_idx].strip()
            remaining = self.emo_buffer[close_idx + 1:]
            self.in_emo_tag = False
            self.emo_buffer = ""
            return True, remaining, emotion
        
        return False, "", ""


# ============================================================================
# 并行处理器
# ============================================================================

class ParallelProcessor:
    """并行任务处理器"""
    
    @staticmethod
    async def process_all(
        agent: Any,
        message: str,
        intimacy_level: float
    ) -> Dict[str, Any]:
        """并行处理所有任务"""
        # 创建并行任务
        tasks = []
        
        # 生命统计
        life_stats_task = ParallelProcessor._get_life_stats(agent)
        tasks.append(("life_stats", life_stats_task))
        
        # 感官反馈
        sensory_task = ParallelProcessor._get_sensory_feedback(agent, message)
        tasks.append(("sensory_feedback", sensory_task))
        
        # 行为链
        behavior_task = ParallelProcessor._get_behavior_chain(agent, message)
        tasks.append(("behavior_chain", behavior_task))
        
        # 依赖结果
        dep_task = ParallelProcessor._get_dependency_result(agent, message, intimacy_level)
        tasks.append(("dep_result", dep_task))
        
        # 触发缺陷
        defects_task = ParallelProcessor._get_triggered_defects(agent, message)
        tasks.append(("triggered_defects", defects_task))
        
        # 执行所有任务
        results = {}
        task_coros = [task for _, task in tasks]
        task_names = [name for name, _ in tasks]
        
        completed = await asyncio.gather(*task_coros, return_exceptions=True)
        
        for name, result in zip(task_names, completed):
            if isinstance(result, Exception):
                results[name] = None
            else:
                results[name] = result
        
        return results
    
    @staticmethod
    async def _get_life_stats(agent: Any) -> Optional[Dict]:
        """获取生命统计"""
        try:
            if hasattr(agent, 'life_simulator'):
                return await agent.life_simulator.get_current_state()
        except Exception:
            pass
        return None
    
    @staticmethod
    async def _get_sensory_feedback(agent: Any, message: str) -> Optional[Dict]:
        """获取感官反馈"""
        try:
            if hasattr(agent, 'sensory_manager'):
                return await agent.sensory_manager.process(message)
        except Exception:
            pass
        return None
    
    @staticmethod
    async def _get_behavior_chain(agent: Any, message: str) -> Optional[Dict]:
        """获取行为链"""
        try:
            if hasattr(agent, 'behavior_manager'):
                return await agent.behavior_manager.process(message)
        except Exception:
            pass
        return None
    
    @staticmethod
    async def _get_dependency_result(agent: Any, message: str, intimacy_level: float) -> Dict:
        """获取依赖结果"""
        try:
            if hasattr(agent, 'dependency_manager'):
                return await agent.dependency_manager.check_unlocks(message, intimacy_level)
        except Exception:
            pass
        return {"new_unlocks": []}
    
    @staticmethod
    async def _get_triggered_defects(agent: Any, message: str) -> List[str]:
        """获取触发的缺陷"""
        try:
            if hasattr(agent, 'personality_defect_manager'):
                return await agent.personality_defect_manager.check_triggers(message)
        except Exception:
            pass
        return []
    
    @staticmethod
    def extract_life_stats(life_stats: Optional[Dict]) -> Tuple[float, float, bool, float, int]:
        """提取生命统计数据"""
        if not life_stats:
            return 0.5, 0.1, False, 0.0, 1
        
        mood_score = life_stats.get("mood_score", 0.5)
        shyness_score = life_stats.get("shyness_score", 0.1)
        is_sick = life_stats.get("is_sick", False)
        immune_damage = life_stats.get("immune_damage", 0.0)
        life_level = life_stats.get("level", 1)
        
        return mood_score, shyness_score, is_sick, immune_damage, life_level
    
    @staticmethod
    async def handle_intimacy_context(message: str, intimacy_level: float) -> Optional[float]:
        """处理亲密度上下文，返回更新后的害羞度"""
        # 简单实现：根据亲密度调整害羞度
        if intimacy_level > 0.7:
            return 0.05  # 高亲密度，低害羞
        elif intimacy_level < 0.3:
            return 0.3  # 低亲密度，高害羞
        return None  # 不调整


# ============================================================================
# JSON流式解析器
# ============================================================================

class JSONStreamParser:
    """JSON流式解析器 - 处理 {"analysis": ..., "response": ...} 格式"""
    
    def __init__(self):
        self.is_json_mode = False
        self.json_buffer = ""
        self.analysis_content = ""
        self.response_content = ""
        self.in_analysis = False
        self.in_response = False
        self.last_update_time = datetime.now()
    
    def try_enter_json_mode(self, text: str, allow_json: bool) -> Tuple[bool, str]:
        """尝试进入JSON模式"""
        if not allow_json:
            return False, text
        
        # 检查是否以 { 开头
        stripped = text.lstrip()
        if stripped.startswith('{'):
            self.is_json_mode = True
            self.json_buffer = stripped
            return True, ""
        
        return False, text
    
    def parse_chunk(self, chunk: str) -> Tuple[str, str, str]:
        """
        解析chunk
        返回: (可见文本, 思考内容, 当前状态)
        """
        if not self.is_json_mode:
            return chunk, "", "normal"
        
        self.json_buffer += chunk
        self.last_update_time = datetime.now()
        
        # 简单的JSON解析（实际应该更健壮）
        visible = ""
        thought = ""
        
        # 尝试提取analysis
        if '"analysis"' in self.json_buffer and not self.in_analysis:
            self.in_analysis = True
        
        # 尝试提取response
        if '"response"' in self.json_buffer and not self.in_response:
            self.in_response = True
        
        return visible, thought, "parsing"
    
    def check_stall(self, timeout_seconds: int = 30) -> bool:
        """检查是否卡住"""
        if not self.is_json_mode:
            return False
        
        elapsed = (datetime.now() - self.last_update_time).total_seconds()
        return elapsed > timeout_seconds


# ============================================================================
# 导出所有公共接口
# ============================================================================

__all__ = [
    # 文本工具
    "normalize_tilde_ending",
    "looks_formal_user_text",
    "looks_mostly_english",
    "find_stream_boundary",
    
    # 图片检测
    "extract_image_request_prompt",
    
    # 自然度增强
    "DYNAMIC_FILLERS",
    "FILLER_BLOCK_RE",
    
    # 类
    "StreamTextSmoother",
    "StreamContextBuilder",
    "TagParser",
    "ParallelProcessor",
    "JSONStreamParser",
]
