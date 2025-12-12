from typing import Type, Optional
from pydantic import BaseModel, Field
from .base import BaseTool
import aiohttp
import os
import json
from datetime import datetime

class WebSearchInput(BaseModel):
    query: str = Field(description="The search query")
    count: int = Field(default=3, description="Number of results to return")

class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the internet for up-to-date information."
    args_schema = WebSearchInput

    async def _run(self, query: str, count: int = 3) -> str:
        api_key = os.environ.get("BOCHA_API_KEY")
        if not api_key:
             return "Error: Web search is currently unavailable (API key missing)."
        
        url = "https://api.bochaai.com/v1/web-search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "query": query,
            "freshness": "noLimit",
            "summary": True,
            "count": count
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = []
                        # Adapt to Bocha response structure
                        web_pages = data.get("data", {}).get("webPages", {}).get("value", [])
                        for item in web_pages:
                            results.append(f"Title: {item.get('name')}\nSnippet: {item.get('snippet')}\nURL: {item.get('url')}")
                        return "\n\n".join(results) if results else "No results found."
                    else:
                        return f"Search failed with status {response.status}"
        except Exception as e:
            return f"Search error: {str(e)}"

class ImageGenInput(BaseModel):
    prompt: str = Field(description="Description of the image to generate")
    model_name: Optional[str] = Field(None, description="Specific model to use (e.g., 'chilloutmix', 'ghostmix', 'nsfw', 'pony', 'sdxl'). If not specified, uses default.")
    vae_name: Optional[str] = Field(None, description="Specific VAE to use (e.g., 'vaeKlF8Anime2'). If not specified, uses default.")

class ImageGenerationTool(BaseTool):
    name = "generate_image"
    description = "Generate an image based on a text prompt. Available models: chilloutmix (realistic), ghostmix (anime/2.5D), nsfw (adult), pony (SDXL anime), sdxl (SDXL realistic). VAE: vaeKlF8Anime2."
    args_schema = ImageGenInput

    async def _run(self, prompt: str, model_name: Optional[str] = None, vae_name: Optional[str] = None) -> str:
        # Return the tag that the system recognizes
        # Format: [GEN_IMG: prompt | model=xxx | vae=xxx]
        content = prompt
        if model_name:
            content += f" | model={model_name}"
        if vae_name:
            content += f" | vae={vae_name}"
        return f"[GEN_IMG: {content}]"

class TimeInput(BaseModel):
    pass

class TimeTool(BaseTool):
    name = "get_current_time"
    description = "Get the current system time."
    args_schema = TimeInput
    
    async def _run(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class CalculatorInput(BaseModel):
    expression: str = Field(description="Mathematical expression to evaluate (e.g., '2 + 2')")

class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Calculate mathematical expressions."
    args_schema = CalculatorInput

    async def _run(self, expression: str) -> str:
        try:
            # Safe eval
            allowed_names = {"abs": abs, "round": round, "min": min, "max": max}
            code = compile(expression, "<string>", "eval")
            for name in code.co_names:
                if name not in allowed_names:
                    return f"Error: Use of '{name}' is not allowed"
            return str(eval(code, {"__builtins__": {}}, allowed_names))
        except Exception as e:
            return f"Error calculating: {str(e)}"
