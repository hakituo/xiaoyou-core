from typing import List, Dict, Optional, Any
from fastapi import APIRouter, Query, Body, HTTPException
import time
from core.services.study_service import get_study_service
from core.utils.logger import get_logger

logger = get_logger("STUDY_ROUTER")

router = APIRouter(prefix="/api/v1/study", tags=["study"])

@router.get("/daily")
async def get_daily_vocabulary(count: int = Query(20, ge=5, le=50)):
    """Get daily vocabulary list"""
    try:
        service = get_study_service()
        words = service.get_daily_words(count)
        return {
            "status": "success",
            "data": words,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Failed to get daily words: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/dictionary/stats")
async def get_dictionary_stats():
    """Get dictionary statistics"""
    try:
        service = get_study_service()
        stats = service.get_dictionary_stats()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/curve")
async def get_memory_curve():
    """Get memory retention curve data"""
    try:
        service = get_study_service()
        curve = service.get_memory_curve_data()
        return {
            "status": "success",
            "data": curve
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mistakes")
async def get_mistakes():
    """Get high error rate words"""
    try:
        service = get_study_service()
        mistakes = service.get_mistakes()
        return {
            "status": "success",
            "data": mistakes
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/tools")
async def list_tools():
    """List available study tools"""
    try:
        service = get_study_service()
        tools = service.list_tools()
        return {
            "status": "success",
            "data": tools
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/tools/{category}/{tool_id}/run")
async def run_tool(
    category: str, 
    tool_id: str, 
    params: Dict[str, Any] = Body(...)
):
    """Run a specific study tool"""
    try:
        service = get_study_service()
        result = service.run_tool(category, tool_id, params)
        return result
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        return {"status": "error", "message": str(e)}
