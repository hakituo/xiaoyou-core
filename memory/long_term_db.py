import sqlite3
import os
from typing import List

DB_PATH = 'long_term_memory.db'

def initialize_db():
    """Initialize database and table structure."""
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

# Call initialization on first run
initialize_db()

def retrieve_long_term_memory(keywords: List[str]) -> str:
    """
    Retrieve most relevant long-term memories based on keywords.
    (Note: This is a synchronous blocking function, use asyncio.to_thread in async environments)
    """
    if not keywords:
        return "No keywords available for retrieval."
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Build a simple LIKE query to match records containing any of the keywords
    # Vector search should be used in production, this is a simplified approach
    conditions = " OR ".join([f"keywords LIKE '%%{k}%%'" for k in keywords])
    
    query = f"SELECT text FROM long_term_memory WHERE {conditions} ORDER BY timestamp DESC LIMIT 3"
    
    results = cursor.execute(query).fetchall()
    conn.close()
    
    if not results:
        return "No relevant long-term memories found."
    
    mem_str = "\n".join([f"- {r[0]}" for r in results])
    return f"Retrieved long-term memories:\n{mem_str}"

def save_long_term_memory(text: str, keywords_str: str):
    """
    Save user message and keywords to long-term memory.
    (Note: This is a synchronous blocking function, use asyncio.to_thread in async environments)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO long_term_memory (text, keywords) VALUES (?, ?)", (text, keywords_str))
    conn.commit()
    conn.close()