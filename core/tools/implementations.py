import asyncio
from typing import Optional
from pydantic import BaseModel, Field
from .base import BaseTool
from .ad_classifier import get_ad_classifier
import aiohttp
import os
import re
from core.utils.time_utils import get_current_time_str
from core.utils.logger import get_logger

logger = get_logger("web_search_tool")

ZHIPU_SEARCH_MODEL = "glm-4.5-air"
ZHIPU_SEARCH_TIMEOUT = 45

ZHIPU_SEARCH_SYSTEM_PROMPT = (
    "你是一个搜索助手。请根据用户的问题，搜索并整理相关信息。"
    "只输出搜索到的关键事实，不要添加你自己的分析或观点。"
    "用简洁的要点列表格式输出。"
)


class TimeInput(BaseModel):
    pass


class TimeTool(BaseTool):
    name = "get_current_time"
    description = "Get the current system time."
    short_description = "获取当前系统时间"
    category = "utility"
    args_schema = TimeInput

    async def _run(self) -> str:
        return get_current_time_str("%Y-%m-%d %H:%M:%S")


class CalculatorInput(BaseModel):
    expression: str = Field(
        description="Mathematical expression to evaluate (e.g., '2 + 2')"
    )


class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Evaluate a mathematical expression and return the result."
    short_description = "计算数学表达式"
    category = "utility"
    args_schema = CalculatorInput

    async def _run(self, expression: str) -> str:
        try:
            allowed_chars = set("0123456789+-*/.()% ")
            cleaned = "".join(c for c in expression if c in allowed_chars)
            if not cleaned:
                return "Error: empty expression after sanitization"
            result = self._safe_eval_math(cleaned)
            return str(result)
        except ZeroDivisionError:
            return "Error: division by zero"
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def _safe_eval_math(expression: str) -> float:
        """安全的数学表达式解析器，使用 ast 模块替代 eval()"""
        import ast
        import operator

        # 允许的运算符映射
        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        def _eval_node(node):
            if isinstance(node, ast.Expression):
                return _eval_node(node.body)
            elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            elif isinstance(node, ast.BinOp) and type(node.op) in operators:
                left = _eval_node(node.left)
                right = _eval_node(node.right)
                return operators[type(node.op)](left, right)
            elif isinstance(node, ast.UnaryOp) and type(node.op) in operators:
                operand = _eval_node(node.operand)
                return operators[type(node.op)](operand)
            else:
                raise ValueError(f"不支持的表达式: {ast.dump(node)}")

        tree = ast.parse(expression, mode='eval')
        return _eval_node(tree)


class WebSearchInput(BaseModel):
    query: str = Field(description="The search query")
    count: int = Field(default=3, description="Number of results to return")


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the internet for up-to-date information."
    short_description = "搜索互联网获取最新信息"
    category = "utility"
    args_schema = WebSearchInput

    async def _run(self, query: str, count: int = 3) -> str:
        provider = self._resolve_provider()

        if provider == "zhipu":
            return await self._search_via_zhipu(query)

        if provider == "bocha":
            raw_results = await self._search_bocha(query, count)
            return await self._preprocess_bocha_results(query, raw_results)

        if provider == "serper":
            raw_results = await self._search_serper(query, count)
            return await self._preprocess_serper_results(query, raw_results)

        logger.warning(f"未知的web_search provider: {provider}, 回退到zhipu")
        return await self._search_via_zhipu(query)

    async def _search_via_zhipu(self, query: str) -> str:
        """通过智谱模型代理搜索：调用glm-4.5-air(开启web_search)完成搜索

        智谱服务端自动完成：判断是否需要搜索→搜索→过滤→融入回复
        返回的结果已经是处理好的，不需要额外预处理
        """
        zhipu_api_key = os.environ.get("ZHIPU_API_KEY")
        if not zhipu_api_key:
            return "Error: Web search unavailable (ZHIPU_API_KEY missing)."

        messages = [
            {"role": "system", "content": ZHIPU_SEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]

        payload = {
            "model": ZHIPU_SEARCH_MODEL,
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
            "tools": [{"type": "web_search", "web_search": {"enable": True}}],
        }

        headers = {
            "Authorization": f"Bearer {zhipu_api_key}",
            "Content-Type": "application/json",
        }

        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

        try:
            timeout = aiohttp.ClientTimeout(total=ZHIPU_SEARCH_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        choices = data.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                            if content:
                                logger.info(f"[WebSearch] 智谱代理搜索完成: query='{query[:30]}...', 结果{len(content)}字")
                                return content.strip()
                        return "No search results found."
                    else:
                        error_text = await response.text()
                        logger.warning(f"[WebSearch] 智谱代理搜索失败 ({response.status}): {error_text[:200]}")
                        return f"Search failed with status {response.status}"
        except asyncio.TimeoutError:
            logger.warning("[WebSearch] 智谱代理搜索超时")
            return "Search timed out."
        except Exception as e:
            logger.warning(f"[WebSearch] 智谱代理搜索异常: {e}")
            return f"Search error: {str(e)}"

    async def _preprocess_bocha_results(self, query: str, raw_results: str) -> str:
        """预处理Bocha搜索结果：朴素贝叶斯过滤广告 + LLM精炼"""
        if not raw_results or raw_results.startswith("Error") or raw_results.startswith("Search failed"):
            return raw_results

        if len(raw_results) < 100:
            return raw_results

        filtered = self._bayes_filter(raw_results)

        try:
            preprocessed = await self._call_preprocess_llm(query, filtered)
            if preprocessed and len(preprocessed) > 10:
                logger.info(f"[WebSearch] 预处理完成: 原始{len(raw_results)}字 -> 精简{len(preprocessed)}字")
                return preprocessed
        except Exception as e:
            logger.warning(f"[WebSearch] LLM预处理失败，使用贝叶斯过滤结果: {e}")

        return filtered

    def _bayes_filter(self, raw_results: str) -> str:
        """朴素贝叶斯过滤广告和无关搜索结果"""
        blocks = re.split(r'\n\n+', raw_results)
        classifier = get_ad_classifier()
        filtered_blocks = []
        removed_count = 0

        for block in blocks:
            if not block.strip():
                continue

            title_match = re.search(r'Title:\s*(.+)', block)
            snippet_match = re.search(r'Snippet:\s*(.+)', block)

            classify_text = ""
            if title_match:
                classify_text += title_match.group(1) + " "
            if snippet_match:
                classify_text += snippet_match.group(1)
            if not classify_text:
                classify_text = block

            is_ad, confidence = classifier.classify(classify_text)

            if is_ad and confidence > 0.6:
                removed_count += 1
                logger.debug(f"[WebSearch] 贝叶斯过滤广告 (置信度{confidence:.2f}): {classify_text[:50]}...")
            else:
                filtered_blocks.append(block)

        result = "\n\n".join(filtered_blocks)
        if removed_count > 0:
            logger.info(f"[WebSearch] 贝叶斯过滤: {len(blocks)}条 -> {len(filtered_blocks)}条 (去除{removed_count}条广告)")
        return result

    async def _call_preprocess_llm(self, query: str, raw_results: str) -> Optional[str]:
        """调用轻量LLM进行搜索结果预处理（Bocha模式专用）"""
        zhipu_api_key = os.environ.get("ZHIPU_API_KEY")
        if not zhipu_api_key:
            return None

        truncated_raw = raw_results[:3000] if len(raw_results) > 3000 else raw_results

        messages = [
            {"role": "system", "content": (
                "根据查询，从搜索结果中提取关键事实。删除广告和无关内容。"
                "直接输出要点列表，每条一句话。禁止输出分析过程。"
                "示例格式：\n- 事实1\n- 事实2\n- 事实3"
            )},
            {"role": "user", "content": f"查询：{query}\n\n搜索结果：\n{truncated_raw}"},
        ]

        payload = {
            "model": ZHIPU_SEARCH_MODEL,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
            "thinking": {"type": "disabled"},
        }

        headers = {
            "Authorization": f"Bearer {zhipu_api_key}",
            "Content-Type": "application/json",
        }

        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

        try:
            timeout = aiohttp.ClientTimeout(total=ZHIPU_SEARCH_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        choices = data.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                            if content:
                                cleaned = self._clean_llm_output(content.strip())
                                return cleaned if len(cleaned) > 10 else None
                    else:
                        error_text = await response.text()
                        logger.warning(f"[WebSearch] 预处理LLM调用失败 ({response.status}): {error_text[:200]}")
                        return None
        except asyncio.TimeoutError:
            logger.warning("[WebSearch] 预处理LLM超时")
            return None
        except Exception as e:
            logger.warning(f"[WebSearch] 预处理LLM异常: {e}")
            return None

    def _clean_llm_output(self, content: str) -> str:
        """清理LLM输出中的分析过程，只保留要点列表"""
        lines = content.strip().split("\n")
        result_lines = []
        in_list = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("- ") or stripped.startswith("• ") or stripped.startswith("* "):
                result_lines.append(stripped)
                in_list = True
            elif re.match(r'^\d+[.、)]\s', stripped):
                result_lines.append(stripped)
                in_list = True
            elif in_list and not stripped.startswith(("我", "让", "首", "从", "这", "第")):
                result_lines.append(stripped)

        if result_lines:
            return "\n".join(result_lines)
        return content

    def _resolve_provider(self) -> str:
        """从配置或运行时上下文解析搜索provider"""
        ctx = getattr(self, "_runtime_context", {}) or {}
        agent = ctx.get("agent")

        if agent and hasattr(agent, "llm_module"):
            try:
                model_name = agent.llm_module.get_current_model_name()
                llm_provider = self._extract_provider_from_model(model_name)
                if llm_provider:
                    from config.model_config import get_web_search_provider_for_llm
                    return get_web_search_provider_for_llm(llm_provider)
            except Exception:
                pass

        try:
            from config.model_config import get_web_search_config
            ws_config = get_web_search_config()
            return ws_config.get("default_provider", "serper")
        except Exception:
            return "serper"

    def _extract_provider_from_model(self, model_name: str) -> Optional[str]:
        """从模型路径中提取provider名称"""
        if not model_name:
            return None
        if model_name.startswith("cloud:"):
            parts = model_name.split(":", 2)
            if len(parts) >= 2:
                return parts[1]
        return None

    async def _search_bocha(self, query: str, count: int = 3) -> str:
        """使用Bocha AI搜索API"""
        try:
            from config.model_config import get_web_search_config
            ws_config = get_web_search_config()
            bocha_cfg = ws_config.get("providers", {}).get("bocha", {})
            api_url = bocha_cfg.get("api_url", "https://api.bochaai.com/v1/web-search")
            api_key_env = bocha_cfg.get("api_key_env", "BOCHA_API_KEY")
        except Exception:
            api_url = "https://api.bochaai.com/v1/web-search"
            api_key_env = "BOCHA_API_KEY"

        api_key = os.environ.get(api_key_env)
        if not api_key:
            return "Error: Web search is currently unavailable (API key missing)."

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "freshness": "noLimit",
            "summary": True,
            "count": count,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = []
                        web_pages = (
                            data.get("data", {}).get("webPages", {}).get("value", [])
                        )
                        for item in web_pages:
                            results.append(
                                f"Title: {item.get('name')}\nSnippet: {item.get('snippet')}\nURL: {item.get('url')}"
                            )
                        return "\n\n".join(results) if results else "No results found."
                    else:
                        return f"Search failed with status {response.status}"
        except Exception as e:
            return f"Search error: {str(e)}"

    async def _search_serper(self, query: str, count: int = 3) -> str:
        """使用Serper Google搜索API"""
        try:
            from config.model_config import get_web_search_config
            ws_config = get_web_search_config()
            serper_cfg = ws_config.get("providers", {}).get("serper", {})
            api_url = serper_cfg.get("api_url", "https://google.serper.dev/search")
            api_key_env = serper_cfg.get("api_key_env", "SERPER_API_KEY")
        except Exception:
            api_url = "https://google.serper.dev/search"
            api_key_env = "SERPER_API_KEY"

        api_key = os.environ.get(api_key_env)
        if not api_key:
            return "Error: Web search is currently unavailable (SERPER_API_KEY missing)."

        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "q": query,
            "gl": "cn",
            "hl": "zh-cn",
            "num": count,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(api_url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = []
                        # organic 是 Serper 的主要搜索结果字段
                        organic = data.get("organic", [])
                        for item in organic:
                            results.append(
                                f"Title: {item.get('title')}\nSnippet: {item.get('snippet')}\nURL: {item.get('link')}"
                            )
                        # 知识图谱结果（如果有）
                        kg = data.get("knowledgeGraph", {})
                        if kg and kg.get("description"):
                            results.insert(0, f"KnowledgeGraph: {kg.get('title', '')}\n{kg.get('description', '')}")
                        return "\n\n".join(results) if results else "No results found."
                    else:
                        error_text = await response.text()
                        logger.warning(f"[WebSearch] Serper搜索失败 ({response.status}): {error_text[:200]}")
                        return f"Search failed with status {response.status}"
        except asyncio.TimeoutError:
            logger.warning("[WebSearch] Serper搜索超时")
            return "Search timed out."
        except Exception as e:
            logger.warning(f"[WebSearch] Serper搜索异常: {e}")
            return f"Search error: {str(e)}"

    async def _preprocess_serper_results(self, query: str, raw_results: str) -> str:
        """预处理Serper搜索结果：贝叶斯过滤广告 + LLM精炼（复用Bocha的预处理逻辑）"""
        if not raw_results or raw_results.startswith("Error") or raw_results.startswith("Search failed"):
            return raw_results

        if len(raw_results) < 100:
            return raw_results

        filtered = self._bayes_filter(raw_results)

        try:
            preprocessed = await self._call_preprocess_llm(query, filtered)
            if preprocessed and len(preprocessed) > 10:
                logger.info(f"[WebSearch] Serper预处理完成: 原始{len(raw_results)}字 -> 精简{len(preprocessed)}字")
                return preprocessed
        except Exception as e:
            logger.warning(f"[WebSearch] Serper LLM预处理失败，使用贝叶斯过滤结果: {e}")

        return filtered
