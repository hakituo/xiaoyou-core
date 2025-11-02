import sqlite3
import os
from typing import List

DB_PATH = 'long_term_memory.db'

def initialize_db():
    """初始化数据库和表结构。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS long_term_memory (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            keywords TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# 首次运行时调用初始化
initialize_db()

def retrieve_long_term_memory(keywords: List[str]) -> str:
    """
    根据关键词检索最相关的长期记忆。
    (注意：这是一个同步阻塞函数，在异步环境中需用 asyncio.to_thread 包装)
    """
    if not keywords:
        return "无关键词可供检索。"
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 构建一个简单的 LIKE 查询，匹配任何包含关键词的记录
    # 实际应用中需要用向量搜索，这里用简单方法替代
    conditions = " OR ".join([f"keywords LIKE '%%{k}%%'" for k in keywords])
    
    query = f"SELECT text FROM long_term_memory WHERE {conditions} ORDER BY timestamp DESC LIMIT 3"
    
    results = cursor.execute(query).fetchall()
    conn.close()
    
    if not results:
        return "未找到相关长期记忆。"
    
    mem_str = "\n".join([f"- {r[0]}" for r in results])
    return f"检索到的长期记忆:\n{mem_str}"

def save_long_term_memory(text: str, keywords_str: str):
    """
    保存用户消息和关键词到长期记忆。
    (注意：这是一个同步阻塞函数，在异步环境中需用 asyncio.to_thread 包装)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO long_term_memory (text, keywords) VALUES (?, ?)", (text, keywords_str))
    conn.commit()
    conn.close()