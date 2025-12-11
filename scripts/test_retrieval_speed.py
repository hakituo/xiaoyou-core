import time
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools.study_tools import KnowledgeRetrievalTool

def test_speed():
    print("Initializing KnowledgeRetrievalTool...")
    start_init = time.time()
    tool = KnowledgeRetrievalTool()
    # Trigger initialization (lazy loading)
    # The tool creates VectorSearch instance internally when run is called
    print(f"Tool created in {time.time() - start_init:.4f}s")

    print("\nRunning query '高考数学'...")
    start_query = time.time()
    # This will initialize VectorSearch and load the DB
    result = tool._run("高考数学", top_k=1)
    end_query = time.time()
    
    print(f"Query completed in {end_query - start_query:.4f}s")
    print("-" * 50)
    print(f"Result preview: {result[:200]}...")
    print("-" * 50)

    if (end_query - start_query) < 5.0:
        print("SUCCESS: Retrieval is fast (under 5s). No re-ingestion detected.")
    else:
        print("WARNING: Retrieval took longer than expected. Check for re-ingestion.")

if __name__ == "__main__":
    test_speed()
