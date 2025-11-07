# TRM/STT 推理 I/O 终点 (FastAPI Server)
import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel
import httpx

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='history/trm_reflector.log'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="TRM Reflector API", description="TRM/STT 推理 I/O 终点")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求模型
class LLMQueryRequest(BaseModel):
    prompt: str
    model: str = "default"
    max_tokens: int = 1024
    temperature: float = 0.7

class STTDecodeRequest(BaseModel):
    audio_path: str
    language: str = "auto"

class ImageGenerateRequest(BaseModel):
    prompt: str
    style: str = "default"
    size: str = "1024x1024"

# 模拟LLM接口
async def mock_llm_response(prompt: str) -> str:
    """模拟LLM响应"""
    await asyncio.sleep(2)  # 模拟延迟
    return f"模拟响应: {prompt[:50]}..."

# 模拟STT接口
async def mock_stt_decode(audio_path: str) -> str:
    """模拟STT解码"""
    await asyncio.sleep(1)
    return "模拟语音转文字结果"

# 模拟图像生成
async def mock_image_generate(prompt: str) -> str:
    """模拟图像生成"""
    await asyncio.sleep(3)
    return f"generated/image_{hash(prompt)}.jpg"

# API端点
@app.post("/api/llm/query")
async def llm_query(request: LLMQueryRequest):
    try:
        logger.info(f"LLM查询请求: model={request.model}, max_tokens={request.max_tokens}")
        response = await mock_llm_response(request.prompt)
        return {"result": response}
    except Exception as e:
        logger.error(f"LLM查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt/decode")
async def stt_decode(request: STTDecodeRequest):
    try:
        logger.info(f"STT解码请求: path={request.audio_path}, language={request.language}")
        # 检查文件是否存在
        if not os.path.exists(request.audio_path):
            raise HTTPException(status_code=404, detail="音频文件不存在")
        result = await mock_stt_decode(request.audio_path)
        return {"text": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"STT解码失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/image/generate")
async def image_generate(request: ImageGenerateRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"图像生成请求: style={request.style}, size={request.size}")
        # 在实际场景中，这会是一个异步任务
        image_path = await mock_image_generate(request.prompt)
        return {"image_path": image_path}
    except Exception as e:
        logger.error(f"图像生成失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    # 确保生成目录存在
    os.makedirs("static/generated", exist_ok=True)
    
    # 从环境变量读取端口，默认8000
    port = int(os.getenv("TRM_PORT", "8000"))
    
    logger.info(f"TRM Reflector启动在端口 {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)