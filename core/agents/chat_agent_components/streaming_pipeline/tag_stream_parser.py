"""
流式标签解析状态机
从 streaming.py 解耦：处理 LLM 流式输出中的标签解析（<think>、[GEN_IMG:]、
[EMO:]、[TOPIC:]、[TOOL_USE:]、DSML token）、时间戳前缀缓冲、
以及原生/标签两种工具调用的流内执行
"""
import json
import re
import time
from typing import Any, Dict, List, Optional

from config.debug_config import is_debug_enabled
from core.llm.llm_logger import log_stream_first_chunk
from core.utils.logger import get_logger

logger = get_logger("ChatAgent")

# 完整时间戳前缀（如 [23:10]、[05-22 01:45]、[2025-05-22 01:45:30 (周四)]）
TS_PREFIX_PATTERN = re.compile(
    r"^\[(?:\d{2,4}(?:-\d{2}){1,2}\s+)?\d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*"
)
# 可能构成时间戳前缀的不完整片段（流式输出逐段到达时用于判断是否继续缓冲）
TS_PREFIX_PARTIAL = re.compile(
    r"^\[$"
    r"|^\[\d{1,2}$"
    r"|^\[\d{2}:$"
    r"|^\[\d{2}:\d{1,2}$"
    r"|^\[\d{2}:\d{2}(?::\d{1,2})?$"
    r"|^\[\d{2}:\d{2}(?::\d{2})?\s*$"
    r"|^\[\d{2}:\d{2}(?::\d{2})?\s*\($"
    r"|^\[\d{2}:\d{2}(?::\d{2})?\s*\([^)]*$"
    r"|^\[\d{1,4}$"
    r"|^\[\d{2,4}-$"
    r"|^\[\d{2,4}-\d{1,2}$"
    r"|^\[\d{2,4}-\d{2} $"
    r"|^\[\d{2,4}-\d{2} \d{1,2}$"
    r"|^\[\d{2,4}-\d{2} \d{2}:$"
    r"|^\[\d{2,4}-\d{2} \d{2}:\d{1,2}$"
    r"|^\[\d{2,4}-\d{2} \d{2}:\d{2}(?::\d{1,2})?$"
    r"|^\[\d{2,4}-\d{2} \d{2}:\d{2}(?::\d{2})?\s*$"
    r"|^\[\d{2,4}-\d{2} \d{2}:\d{2}(?::\d{2})?\s*\($"
    r"|^\[\d{2,4}-\d{2} \d{2}:\d{2}(?::\d{2})?\s*\([^)]*$"
    r"|^\[\d{2,4}-\d{2}-$"
    r"|^\[\d{2,4}-\d{2}-\d{1,2}$"
    r"|^\[\d{2,4}-\d{2}-\d{2} $"
    r"|^\[\d{2,4}-\d{2}-\d{2} \d{1,2}$"
    r"|^\[\d{2,4}-\d{2}-\d{2} \d{2}:$"
    r"|^\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{1,2}$"
    r"|^\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{1,2})?$"
    r"|^\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?\s*$"
    r"|^\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?\s*\($"
    r"|^\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?\s*\([^)]*$"
)
TS_MAX_LEN = 30

# DSML 工具调用 token（DeepSeek 系模型偶发泄漏到 content 中）
DSML_START_MARKERS = [
    "<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>",
    "<\uff5c\uff5cDSML\uff5c\uff5cfunction_calls>",
    "<\uff5cDSML\uff5ctool_calls>",
    "<\uff5cDSML\uff5cfunction_calls>",
]
DSML_CLOSE_PATTERNS = [
    "</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>",
    "</\uff5c\uff5cDSML\uff5c\uff5cfunction_calls>",
    "</\uff5cDSML\uff5ctool_calls>",
    "</\uff5cDSML\uff5cfunction_calls>",
    "</tool_calls>",
    "</function_calls>",
]

# 标签标记的最大长度，用于保留 pending 尾部避免截断标记
MAX_MARKER_LEN = 11

# 所有可能出现在可见文本流中的标记前缀（用于判断 pending 尾部是否需要扣留防截断）
MARKER_PREFIXES = [
    "<think",
    "[gen_img:",
    "[emo:",
    "[topic:",
    "[voice]",
    "[tool_use:",
]


def _tail_may_start_marker(text: str) -> bool:
    """判断 text 尾部是否可能是某个标记的不完整开头（需扣留防截断）。

    只有当 pending_text 的末尾字符是某个 marker 前缀的『不完整前缀』时才返回 True，
    否则说明这段文本是纯可见内容，可以立即全部放行，避免无谓积压导致伪流式。
    """
    if not text:
        return False
    # 只检查尾部最多 MAX_MARKER_LEN 个字符
    tail = text[-MAX_MARKER_LEN:]
    for prefix in MARKER_PREFIXES:
        # tail 是 prefix 的子串前缀（tail 与 prefix 的前缀重合）
        common_len = min(len(tail), len(prefix))
        if common_len > 0 and tail[-common_len:] == prefix[:common_len]:
            return True
        # 更精确：tail 的某个后缀是 prefix 的前缀（如 text 以 '<t' 结尾）
        for cut in range(1, min(len(tail), len(prefix)) + 1):
            if tail[-cut:] == prefix[:cut]:
                return True
    return False


class StreamTagSession:
    """跨轮次的流式解析会话

    维护跨轮次状态（可见回复、思考内容、图片/话题/情绪收集、消息列表），
    以及每轮的解析状态（标签缓冲、DSML 缓冲、事件缓存、时间戳前缀缓冲）。
    每轮开始前调用 begin_turn()；轮内对每个 chunk 调用 process_chunk()，
    返回 True 表示本轮出现标签式工具调用，需要中断流式读取进入下一轮。
    """

    def __init__(
        self,
        agent: Any,
        user_id: str,
        is_sensitive_mode: bool,
        messages: List[Dict[str, Any]],
        model_path: Optional[str],
        allowed_tool_names: Optional[List[str]] = None,
    ):
        self.agent = agent
        self.user_id = user_id
        self.is_sensitive_mode = is_sensitive_mode
        self.messages = messages  # 引用共享，工具执行时就地追加
        self.model_path = model_path
        self.allowed_tool_names = list(dict.fromkeys(allowed_tool_names or []))
        self.discovered_tool_names: List[str] = []

        # 跨轮次状态
        self.current_response_content = ""
        self.thought_content = ""
        self.collected_image_prompts: List[str] = []
        self.extracted_topics: List[str] = []
        self.llm_emo_tag: Optional[str] = None

        # 每轮状态（begin_turn 重置）
        self.begin_turn()

    def begin_turn(self) -> None:
        """重置每轮解析状态"""
        self.chunk_count = 0
        self.in_tag = False
        self.in_think = False
        self.in_dsml = False
        self.dsml_buffer = ""
        self.tag_buffer = ""
        self.tag_type = ""
        self.tag_prefix = ""
        # 缓存当前轮次的事件，中间轮次（有工具调用）的内容不输出给用户
        self.turn_event_buffer: List[Dict[str, Any]] = []
        self.content_at_turn_start = self.current_response_content
        self.pending_text = ""
        self.tool_executed_this_turn = False
        self.ts_prefix_buffer = ""
        self.ts_prefix_flushed = False
        self.pending_tool_calls: Dict[str, Dict[str, Any]] = {}
        # 实时 token 发送队列（普通文本逐块发送，不进 turn_event_buffer）
        self.rt_emits: List[str] = []

    def discard_turn(self) -> None:
        """丢弃中间轮次（有工具调用）已缓存的事件并回退内容"""
        self.turn_event_buffer.clear()
        self.rt_emits.clear()
        self.current_response_content = self.content_at_turn_start

    def _record_discovered_tools(self, tool_name: str, tool_result: Any) -> None:
        """记录 search_tools 返回的候选，供下一模型轮次加载 schema。"""
        if tool_name != "search_tools":
            return
        try:
            payload = json.loads(str(tool_result))
        except (TypeError, ValueError):
            return
        allowed = set(self.allowed_tool_names)
        for item in payload.get("tools", []):
            name = str(item.get("name", "")).strip() if isinstance(item, dict) else ""
            if name and name in allowed and name not in self.discovered_tool_names:
                self.discovered_tool_names.append(name)

    # ------------------------------------------------------------------
    # 可见文本缓冲（含时间戳前缀剥离）
    # ------------------------------------------------------------------

    def _emit_tokens(self, text: str) -> None:
        """把可见文本逐字符推入实时发送队列。

        实时 token 不再缓存在 turn_event_buffer，而是放进 rt_emits，
        由 stream_chat_impl 在 process_chunk 后逐块 yield 给前端，
        实现真流式（普通文本立即逐块发送，而非最终轮次整段 dump）。
        """
        self.current_response_content += text
        for ch in text:
            self.rt_emits.append(ch)

    def _drain_rt_emits(self):
        """取出并清空实时 token 队列，供上层逐块发送。"""
        if not self.rt_emits:
            return
        tokens = self.rt_emits
        self.rt_emits = []
        logger.info(f"[TT] _drain_rt_emits drain {len(tokens)} chars @{time.time():.3f}: {''.join(tokens)[:60]!r}")
        for ch in tokens:
            yield {
                "type": "token",
                "content": ch,
                "done": False,
            }

    def _buffer_visible_text(self, text: str) -> None:
        """缓存可见文本事件，不直接 yield，在轮次结束时决定是否输出

        流式开始阶段先缓冲，确认前缀不是模型模仿的时间戳后再放行，
        避免"先发后剥"导致前端闪烁。
        """
        if not text:
            return
        if self.ts_prefix_flushed:
            self._emit_tokens(text)
            return
        self.ts_prefix_buffer += text
        full_match = TS_PREFIX_PATTERN.match(self.ts_prefix_buffer)
        if full_match and full_match.end() == len(self.ts_prefix_buffer):
            return
        if full_match and full_match.end() < len(self.ts_prefix_buffer):
            remainder = self.ts_prefix_buffer[full_match.end():]
            self.ts_prefix_flushed = True
            self._emit_tokens(remainder)
            self.ts_prefix_buffer = ""
            return
        if TS_PREFIX_PARTIAL.match(self.ts_prefix_buffer):
            if len(self.ts_prefix_buffer) >= TS_MAX_LEN:
                self.ts_prefix_flushed = True
                self._emit_tokens(self.ts_prefix_buffer)
                self.ts_prefix_buffer = ""
            return
        self.ts_prefix_flushed = True
        self._emit_tokens(self.ts_prefix_buffer)
        self.ts_prefix_buffer = ""

    # ------------------------------------------------------------------
    # chunk 处理入口
    # ------------------------------------------------------------------

    async def process_chunk(self, chunk: Dict[str, Any]) -> bool:
        """处理一个流式 chunk；返回 True 表示需要中断本轮流式读取"""
        if not chunk:
            return False

        # 累积原生 tool_calls
        if "tool_calls" in chunk:
            self._accumulate_tool_calls(chunk["tool_calls"])
            return False

        # finish_reason 标志流结束
        if "finish_reason" in chunk:
            if chunk["finish_reason"] == "tool_calls" and self.pending_tool_calls:
                await self._execute_native_tool_calls()
            return False

        # 处理 DeepSeek 思考模式 - 内部记录但不输出到前端
        reasoning = chunk.get("reasoning", "")
        if reasoning:
            self.thought_content += reasoning
            return False

        content = chunk.get("content", "")
        if not content:
            return False

        # DeepSeek 思考模式下，content 中可能冗余包含 <think/> 标签
        # 但思考内容已通过 reasoning 字段正确分离，此处直接清理
        if self.thought_content:
            cleaned = re.sub(r"<think\s*/?>", "", content, flags=re.IGNORECASE)
            cleaned = re.sub(r"</think\s*>", "", cleaned, flags=re.IGNORECASE)
            if cleaned != content:
                if is_debug_enabled("streaming"):
                    logger.info("[STREAM] Cleaned redundant <think/> tags from content chunk")
                content = cleaned
                if not content:
                    return False

        self.chunk_count += 1
        if self.chunk_count == 1:
            log_stream_first_chunk(
                provider="hybrid",
                model=self.model_path or "unknown",
                first_content=content,
                ttft_ms=0,
            )
        elif self.chunk_count % 10 == 0:
            logger.info(f"[STREAM] Chunk #{self.chunk_count} received")

        self.pending_text += str(content)
        await self._consume_pending()
        return self.tool_executed_this_turn

    # ------------------------------------------------------------------
    # 原生 function calling
    # ------------------------------------------------------------------

    def _accumulate_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> None:
        """按增量累积原生 tool_calls 片段"""
        for tc in tool_calls:
            tc_id = tc.get("id")
            fn = tc.get("function", {})
            tc_index = tc.get("index", 0)
            if tc_id:
                if tc_id not in self.pending_tool_calls:
                    self.pending_tool_calls[tc_id] = {
                        "index": tc_index,
                        "name": fn.get("name", ""),
                        "arguments": ""
                    }
                self.pending_tool_calls[tc_id]["arguments"] += fn.get("arguments", "")
            else:
                for existing_id, existing_tc in self.pending_tool_calls.items():
                    if existing_tc.get("index") == tc_index:
                        existing_tc["arguments"] += fn.get("arguments", "")
                        break

    async def _execute_native_tool_calls(self) -> None:
        """执行累积的原生 tool_calls，把结果追加到消息列表"""
        for tc_id, tc_info in self.pending_tool_calls.items():
            tool_name = tc_info["name"]
            tool_args_str = tc_info["arguments"]
            tool = self.agent.tool_registry.get_tool(tool_name) if hasattr(self.agent, "tool_registry") else None
            if tool:
                logger.info(f"[Native Tool] Executing: {tool_name}")
                tool.set_runtime_context({
                    "agent": self.agent,
                    "user_id": self.user_id,
                    "scope": "sensitive" if self.is_sensitive_mode else "sfw",
                    "allowed_tool_names": self.allowed_tool_names,
                })
                try:
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}
                    tool_result = await tool.run(**tool_args)
                except Exception as e:
                    tool_result = f"Error: {str(e)}"
                    logger.error(f"[Native Tool] Execution failed: {e}")

                self._record_discovered_tools(tool_name, tool_result)

                assistant_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": tool_args_str
                        }
                    }]
                }
                if self.thought_content:
                    assistant_msg["reasoning_content"] = self.thought_content
                self.messages.append(assistant_msg)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": str(tool_result)
                })
                self.tool_executed_this_turn = True
                logger.info(f"[Native Tool] Result appended for {tool_name}")
        self.pending_tool_calls = {}

    # ------------------------------------------------------------------
    # pending 文本解析主循环
    # ------------------------------------------------------------------

    async def _consume_pending(self) -> None:
        """解析 pending_text 中的标签/思考/DSML，剩余可见文本进入事件缓存"""
        while self.pending_text:
            lower_pending = self.pending_text.lower()

            if self.in_dsml:
                self.dsml_buffer += self.pending_text
                self.pending_text = ""
                for close_pat in DSML_CLOSE_PATTERNS:
                    close_idx = self.dsml_buffer.find(close_pat)
                    if close_idx >= 0:
                        self.in_dsml = False
                        self.dsml_buffer = self.dsml_buffer[close_idx + len(close_pat):]
                        break
                if not self.in_dsml and self.dsml_buffer:
                    self.pending_text = self.dsml_buffer
                    self.dsml_buffer = ""
                continue

            for _dsm in DSML_START_MARKERS:
                if _dsm in self.pending_text:
                    dsml_start_idx = self.pending_text.find(_dsm)
                    if dsml_start_idx > 0:
                        visible_text = self.pending_text[:dsml_start_idx]
                        self._buffer_visible_text(visible_text)
                    self.in_dsml = True
                    self.dsml_buffer = self.pending_text[dsml_start_idx:]
                    self.pending_text = ""
                    break
            if self.in_dsml:
                continue

            if self.in_think:
                close_a = lower_pending.find("</think")
                close_b = lower_pending.find("/think>")
                close_candidates = [x for x in [close_a, close_b] if x >= 0]
                close_idx = min(close_candidates) if close_candidates else -1
                if close_idx < 0:
                    self.thought_content += self.pending_text
                    self.pending_text = ""
                    break
                closer_len = len("</think")
                if close_b >= 0 and (close_idx == close_b):
                    closer_len = len("/think>")
                self.thought_content += self.pending_text[:close_idx]
                self.pending_text = self.pending_text[close_idx + closer_len:]
                self.in_think = False
                self.turn_event_buffer.append({
                    "type": "thought_chain",
                    "data": {
                        "stage": "reasoning",
                        "status": "end",
                        "description": "Thinking finished"
                    },
                    "done": False
                })
                continue

            if self.in_tag:
                close_idx = self.pending_text.find("]")
                if close_idx < 0:
                    self.tag_buffer += self.pending_text
                    self.pending_text = ""
                    break
                self.tag_buffer += self.pending_text[:close_idx]
                self.pending_text = self.pending_text[close_idx + 1:]
                self.in_tag = False
                await self._handle_tag_closed()

                self.tag_buffer = ""
                self.tag_type = ""
                self.tag_prefix = ""

                if self.tool_executed_this_turn:
                    break

                continue

            marker_candidates = {
                "<think": lower_pending.find("<think"),
                "[gen_img:": lower_pending.find("[gen_img:"),
                "[emo:": lower_pending.find("[emo:"),
                "[topic:": lower_pending.find("[topic:"),
                "[voice]": lower_pending.find("[voice]"),
                "[tool_use:": lower_pending.find("[tool_use:"),
            }
            valid_positions = [p for p in marker_candidates.values() if p >= 0]
            marker_pos = min(valid_positions) if valid_positions else -1

            if marker_pos < 0:
                # 尾部可能是某个标记的不完整开头时，才扣留防截断；
                # 否则整段都是纯可见文本，立即全部放行（避免伪流式积压）
                if _tail_may_start_marker(self.pending_text):
                    if len(self.pending_text) <= MAX_MARKER_LEN:
                        logger.info(f"[TT] _consume_pending hold {len(self.pending_text)} chars (marker prefix), pending={self.pending_text!r}")
                        break
                    visible_text = self.pending_text[:-MAX_MARKER_LEN]
                    self.pending_text = self.pending_text[-MAX_MARKER_LEN:]
                    logger.info(f"[TT] _consume_pending release {len(visible_text)} chars, keep tail {len(self.pending_text)} (marker prefix)")
                    self._buffer_visible_text(visible_text)
                    continue
                # 纯文本：全部放行，立即进入实时发送队列
                visible_text = self.pending_text
                self.pending_text = ""
                if visible_text:
                    logger.info(f"[TT] _consume_pending flush {len(visible_text)} chars (plain text)")
                    self._buffer_visible_text(visible_text)
                continue

            if marker_pos > 0:
                visible_text = self.pending_text[:marker_pos]
                self.pending_text = self.pending_text[marker_pos:]
                self._buffer_visible_text(visible_text)
                continue

            if lower_pending.startswith("<think"):
                # DeepSeek 思考模式下，content 中的 <think 是冗余标签
                # 思考内容已通过 reasoning 字段分离，直接跳过
                if self.thought_content:
                    close_a = lower_pending.find("</think")
                    close_b = lower_pending.find("/think>")
                    close_candidates = [x for x in [close_a, close_b] if x >= 0]
                    close_idx = min(close_candidates) if close_candidates else -1
                    if close_idx >= 0:
                        closer_len = len("</think")
                        if close_b >= 0 and close_idx == close_b:
                            closer_len = len("/think>")
                        self.pending_text = self.pending_text[close_idx + closer_len:]
                    else:
                        self.pending_text = self.pending_text[len("<think"):]
                        while self.pending_text and self.pending_text[0] in "> /":
                            self.pending_text = self.pending_text[1:]
                else:
                    self.in_think = True
                    self.pending_text = self.pending_text[len("<think"):]
                    self.turn_event_buffer.append({
                        "type": "thought_chain",
                        "data": {
                            "stage": "reasoning",
                            "status": "start",
                            "description": "Thinking started"
                        },
                        "done": False
                    })
                continue

            if lower_pending.startswith("/think>") or lower_pending.startswith("</think"):
                if lower_pending.startswith("</think"):
                    self.pending_text = self.pending_text[len("</think"):]
                    if self.thought_content:
                        while self.pending_text and self.pending_text[0] == ">":
                            self.pending_text = self.pending_text[1:]
                else:
                    self.pending_text = self.pending_text[len("/think>"):]
                continue

            if lower_pending.startswith("[gen_img:"):
                self.in_tag = True
                self.tag_type = "img"
                self.tag_prefix = "[GEN_IMG:"
                self.tag_buffer = ""
                self.pending_text = self.pending_text[len("[GEN_IMG:"):]
                continue

            if lower_pending.startswith("[emo:"):
                self.in_tag = True
                self.tag_type = "emo"
                self.tag_prefix = "[EMO:"
                self.tag_buffer = ""
                self.pending_text = self.pending_text[len("[EMO:"):]
                continue

            if lower_pending.startswith("[topic:"):
                self.in_tag = True
                self.tag_type = "topic"
                self.tag_prefix = "[TOPIC:"
                self.tag_buffer = ""
                self.pending_text = self.pending_text[len("[TOPIC:"):]
                continue

            if lower_pending.startswith("[tool_use:"):
                self.in_tag = True
                self.tag_type = "tool"
                self.tag_prefix = "[TOOL_USE:"
                self.tag_buffer = ""
                self.pending_text = self.pending_text[len("[TOOL_USE:"):]
                continue

            if lower_pending.startswith("[voice]"):
                self.pending_text = self.pending_text[len("[VOICE]"):]
                continue

            self._buffer_visible_text(self.pending_text[0])
            self.pending_text = self.pending_text[1:]

    async def _handle_tag_closed(self) -> None:
        """标签闭合后的分发处理"""
        if self.tag_type == "img":
            img_prompt = self.tag_buffer.strip()
            if img_prompt:
                self.collected_image_prompts.append(img_prompt)
                self.turn_event_buffer.append({
                    "type": "image_trigger",
                    "data": img_prompt,
                    "done": False
                })
        elif self.tag_type == "emo":
            emo = self.tag_buffer.strip()
            if emo:
                self.llm_emo_tag = emo
        elif self.tag_type == "topic":
            raw_topic_text = self.tag_buffer.strip()
            if raw_topic_text:
                raw_topics = [
                    t.strip()
                    for t in re.split(r"[,，/、\s]+", raw_topic_text)
                    if t.strip()
                ]
                for topic in raw_topics:
                    if topic not in self.extracted_topics:
                        self.extracted_topics.append(topic)
        elif self.tag_type == "tool":
            tool_json_str = self.tag_buffer.strip()
            try:
                tool_call = json.loads(tool_json_str)
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("arguments", {})
                tool = self.agent.tool_registry.get_tool(tool_name)
                if tool:
                    logger.info(f"Executing tool in stream: {tool_name} with args {tool_args}")
                    tool.set_runtime_context({
                        "agent": self.agent,
                        "user_id": self.user_id,
                        "scope": "sensitive" if self.is_sensitive_mode else "sfw",
                        "allowed_tool_names": self.allowed_tool_names,
                    })
                    tool_start = time.time()
                    tool_result = await tool.run(**tool_args)
                    self._record_discovered_tools(tool_name, tool_result)
                    logger.info(f"Tool execution took: {time.time() - tool_start:.4f}s")

                    self.messages.append({
                        "role": "assistant",
                        "content": self.current_response_content + f" [TOOL_USE: {tool_json_str}]"
                    })
                    self.messages.append({
                        "role": "system",
                        "content": f"工具\"{tool_name}\"输出：\n{tool_result}\n\n请基于该信息继续回答用户（不再输出工具调用）。",
                    })
                    self.current_response_content = ""
                    self.tool_executed_this_turn = True
            except Exception as e:
                logger.error(f"Error parsing/executing tool in stream: {e}")

    # ------------------------------------------------------------------
    # 收尾：流结束后的残留状态处理
    # ------------------------------------------------------------------

    def flush_tail(self) -> None:
        """流结束后处理残留的未闭合标签、pending 文本和时间戳缓冲"""
        if self.in_tag and (self.tag_buffer or self.pending_text):
            leaked_text = f"{self.tag_prefix}{self.tag_buffer}{self.pending_text}"
            self.pending_text = ""
            if leaked_text:
                self.current_response_content += leaked_text

        if self.pending_text and not self.in_think:
            self.current_response_content += self.pending_text
            self.pending_text = ""

        if self.ts_prefix_buffer and not self.ts_prefix_flushed:
            ts_match = TS_PREFIX_PATTERN.match(self.ts_prefix_buffer)
            if ts_match:
                self.ts_prefix_buffer = self.ts_prefix_buffer[ts_match.end():]
            if self.ts_prefix_buffer:
                self.current_response_content += self.ts_prefix_buffer
            self.ts_prefix_buffer = ""
