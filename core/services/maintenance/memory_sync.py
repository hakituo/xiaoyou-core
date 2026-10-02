
import asyncio
import os
import json
from datetime import datetime
import re

from core.services.workspace.status_manager import get_user_status_manager
from memory.weighted_memory_manager import get_weighted_memory_manager
from core.utils.data_paths import get_user_weighted_history_dir
from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("MEMORY_SYNC")

async def sync_recent_memories_to_status():
    """
    Scan recent weighted memories (last 24h) for missed life events (Wakeup, Meals)
    and sync them to user_status.json if not already present.
    """
    logger.info("Starting memory sync...")
    
    # 1. Load User Status
    status_mgr = get_user_status_manager()
    current_statuses = status_mgr._load_statuses() # Use internal load to get raw dicts
    status_names = [s["name"] for s in current_statuses]
    logger.info(f"Current Active Statuses: {status_names}")
    
    # 2. Load Recent Memories (Weighted)
    mem_mgr = get_weighted_memory_manager()
    
    # Try loading from specific user file if default empty
    if not mem_mgr.weighted_memories:
        try:
            user_id = "default_user" # Try this specific ID often used
            history_dir = get_user_weighted_history_dir()
            path = os.path.join(str(history_dir), "weighted", f"{user_id}_weighted.json")
            if os.path.exists(path):
                logger.info(f"Loading manual memory file: {path}")
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "weighted_memories" in data:
                        for m in data["weighted_memories"]:
                            mem_mgr.weighted_memories[m["id"]] = m
        except Exception as e:
            logger.error(f"Failed to load manual memory: {e}")
            
    # Ensure memories are loaded
    if not mem_mgr.weighted_memories:
        try:
            # Check if there is a public load method or just rely on init
            # The manager loads on init usually.
            pass 
        except Exception:
            pass
        
    today_str = now_str("%Y-%m-%d")
    
    # Sort by time desc
    recent_memories = sorted(
        mem_mgr.weighted_memories.values(), 
        key=lambda x: x.get("timestamp", 0), 
        reverse=True
    )
    
    found_wakeup = False
    found_meals = []
    
    # Limit scan to recent 50
    for mem in recent_memories[:50]: 
        content = str(mem.get("content", "")).strip()
        role = str(mem.get("role", "")).strip()
        ts = float(mem.get("timestamp", 0))
        
        # Only check user messages
        if role != "user":
            continue
            
        # Check date (approx)
        dt = datetime.fromtimestamp(ts)
        mem_date = dt.strftime("%Y-%m-%d")
        # If memory is too old (not today), skip
        # (Assuming we only care about today's status)
        if mem_date != today_str:
            continue
            
        logger.debug(f"Scanning User Memory: {content}")
        
        # --- Wakeup Detection ---
        if not found_wakeup and "今日起床" not in status_names:
            # Keywords for wakeup
            if any(k in content for k in ["起床", "醒了", "早安", "起来了"]):
                time_str = dt.strftime("%H:%M")
                
                # Try extract "4点", "四点" etc
                # Handle Chinese numbers simple case
                cn_map = {"一":1, "二":2, "三":3, "四":4, "五":5, "六":6, "七":7, "八":8, "九":9, "十":10}
                
                # Check for "X点"
                m = re.search(r"([0-9]{1,2}|[一二三四五六七八九十]+)[点:：]", content)
                if m:
                    val = m.group(1)
                    h = -1
                    if val.isdigit():
                        h = int(val)
                    elif val in cn_map:
                        h = cn_map[val]
                    
                    if h != -1:
                        time_str = f"{h:02d}:00"
                
                logger.info(f" -> Detected Wakeup from memory: {time_str}")
                status_mgr.add_status("今日起床", f"时间: {time_str} (补录)", duration_days=1)
                found_wakeup = True
                status_names.append("今日起床")
                
        # --- Meal Detection ---
        # Keywords for meals
        if any(k in content for k in ["吃了", "吃过", "早饭", "午饭", "晚饭", "夜宵", "面", "粉", "饭", "披萨", "火锅"]):
            # Try to find explicit time mentioned like "七点吃了"
            # If explicit time found, override meal type
            meal_time_hour = dt.hour
            m_time = re.search(r"([0-9]{1,2}|[一二三四五六七八九十]+)[点:：]", content)
            if m_time:
                val = m_time.group(1)
                h = -1
                cn_map = {"一":1, "二":2, "三":3, "四":4, "五":5, "六":6, "七":7, "八":8, "九":9, "十":10, "十一":11, "十二":12}
                if val.isdigit():
                    h = int(val)
                elif val in cn_map:
                    h = cn_map[val]
                
                if h != -1:
                    # Adjust AM/PM if ambiguous? Assume 24h logic or context
                    # Simple heuristic: if > 12 likely afternoon unless specified
                    # But "七点" usually means 7:00 or 19:00.
                    # If current time is PM and 7 is mentioned, maybe 19:00?
                    # Let's just use the number for logic
                    meal_time_hour = h
                    # Fix 7 to 19 if it's dinner time context
                    if "晚" in content and h < 12:
                        meal_time_hour += 12

            meal_name = "用餐记录"
            if 5 <= meal_time_hour < 10:
                meal_name = "早餐"
            elif 11 <= meal_time_hour < 14:
                meal_name = "午餐"
            elif 17 <= meal_time_hour < 21:
                meal_name = "晚餐"
            elif meal_time_hour >= 21 or meal_time_hour < 5:
                meal_name = "夜宵"
            
            # Allow multiple items for same meal? Or just skip if exists
            # User might say "I ate X" then "I also ate Y". 
            # Current logic skips. Let's enable appending if same meal name.
            
            # Extract food content simply
            food = content
            remove_kws = ["我", "吃了", "吃过", "早饭", "午饭", "晚饭", "夜宵", "啊", "了", "的", "吧", "呢", "今天", "早上", "晚上", "中午", "七点", "八点", "九点", "十点", "十二点", "一点", "二点", "三点", "四点", "五点", "六点"]
            for kw in remove_kws:
                food = food.replace(kw, "")
            # Also remove regex time
            food = re.sub(r"([0-9]{1,2}|[一二三四五六七八九十]+)[点:：]", "", food)
            food = food.strip()
            
            if len(food) > 1:
                # Check if already recorded
                existing_status = next((s for s in current_statuses if s["name"] == meal_name), None)
                
                if existing_status:
                    # Append if not same content
                    if food not in existing_status["description"]:
                        new_desc = existing_status["description"] + f", {food}"
                        logger.info(f" -> Appending Meal from memory: {meal_name} - {food}")
                        status_mgr.add_status(meal_name, new_desc, duration_days=1)
                else:
                    logger.info(f" -> Detected Meal from memory: {meal_name} - {food}")
                    status_mgr.add_status(meal_name, f"内容: {food} (补录)", duration_days=1)
                    found_meals.append(meal_name)
                    status_names.append(meal_name)
                    # Refresh current_statuses list for next iteration
                    current_statuses = status_mgr._load_statuses()

    logger.info("Sync completed.")
    print(status_mgr.get_status_summary())

if __name__ == "__main__":
    asyncio.run(sync_recent_memories_to_status())
