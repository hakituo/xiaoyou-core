import os
import sys
import asyncio

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.chat_agent import ChatAgent

async def test_rag():
    print("Initializing ChatAgent...")
    try:
        agent = ChatAgent()
        # Ensure agent is initialized (handle_message does this, but good to be explicit for testing)
        await agent.initialize()
        print("ChatAgent initialized.")
        
        if not agent.vector_search:
            print("[ERROR] VectorSearch is not initialized in ChatAgent!")
            return

        # Test Query 1: Bajau people (from study_data)
        user_id = "test_user_rag"
        query1 = "Bajau people physical characteristics"
        print(f"\n--- Test 1: {query1} ---")
        
        response1 = await agent.handle_message(user_id, query1, message_id="test_msg_1")
        
        if response1["success"]:
            content = response1['content']
            print(f"Content: {content}")
            keywords = ["bajau", "sea", "diving", "ilardo", "spleen"]
            found_keywords = [kw for kw in keywords if kw in content.lower()]
            if found_keywords:
                print(f"[SUCCESS] RAG worked for study_data. Found: {found_keywords}")
            else:
                print("[WARNING] RAG might not have worked for study_data.")
        else:
            print(f"Error: {response1.get('error')}")

        # Test Query 2: Genetics Calculator (from Gao Kao tools)
        query2 = "Explain the genetics calculator code structure"
        print(f"\n--- Test 2: {query2} ---")
        
        response2 = await agent.handle_message(user_id, query2, message_id="test_msg_2")
        
        if response2["success"]:
            content = response2['content']
            print(f"Content: {content}")
            # genetics_calculator.py likely contains "GeneticsCalculator", "class", "def"
            keywords = ["genetics", "calculator", "class", "def", "python"]
            found_keywords = [kw for kw in keywords if kw in content.lower()]
            if found_keywords:
                print(f"[SUCCESS] RAG worked for Gao Kao tools. Found: {found_keywords}")
            else:
                print("[WARNING] RAG might not have worked for Gao Kao tools.")
        else:
            print(f"Error: {response2.get('error')}")

    except Exception as e:
        print(f"\n[ERROR] Failed to run RAG test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_rag())
