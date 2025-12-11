import os
import sys
import logging
import json
import csv
import traceback

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

try:
    import chromadb
    print("chromadb imported successfully")
except ImportError as e:
    print(f"Error importing chromadb: {e}")
except Exception as e:
    print(f"Error importing chromadb (other): {e}")

try:
    from core.vector_search import VectorSearch
except ImportError:
    print("Error importing VectorSearch. Make sure you are running this script from the project root or correct environment.")
    traceback.print_exc()
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def ingest_data():
    logger.info("Starting knowledge ingestion...")
    
    # Initialize VectorSearch with persistence
    # Note: VectorSearch stores data in ./chromadb by default when use_in_memory_db=False
    # We explicitly change directory to project root to ensure ./chromadb is in the right place
    original_cwd = os.getcwd()
    os.chdir(project_root)
    
    try:
        vs = VectorSearch(use_in_memory_db=False)
        
        # Paths to ingest
        paths_to_ingest = [
            os.path.join(project_root, "Gao Kao"),
            os.path.join(project_root, "data", "study_data")
        ]
        
        count = 0
        
        for root_path in paths_to_ingest:
            if not os.path.exists(root_path):
                logger.warning(f"Path not found: {root_path}")
                continue
                
            logger.info(f"Scanning {root_path}...")
            
            for dirpath, dirnames, filenames in os.walk(root_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    
                    # Skip some files
                    if filename.startswith('.') or filename.endswith('.pyc') or filename == "__pycache__":
                        continue
                    
                    try:
                        content = ""
                        metadata = {"source": file_path, "filename": filename}
                        
                        if filename.endswith('.py'):
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            metadata['type'] = 'code'
                        
                        elif filename.endswith('.json'):
                            with open(file_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                content = json.dumps(data, ensure_ascii=False, indent=2)
                            metadata['type'] = 'json'
                            
                        elif filename.endswith('.csv'):
                            with open(file_path, 'r', encoding='utf-8') as f:
                                reader = csv.reader(f)
                                rows = list(reader)
                                content = "\n".join([",".join(row) for row in rows])
                            metadata['type'] = 'csv'
                            
                        elif filename.endswith('.md') or filename.endswith('.txt'):
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            metadata['type'] = 'text'
                        
                        else:
                            # Skip unknown file types
                            continue
                            
                        if not content.strip():
                            continue
                            
                        # Chunk content
                        # We use a smaller chunk size to fit more documents and context
                        chunk_size = 1500 
                        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
                        
                        for i, chunk in enumerate(chunks):
                            # Ensure unique ID
                            doc_id = f"{filename}_{i}_{hash(file_path)}"
                            
                            # Add some context to the text
                            chunk_with_context = f"Filename: {filename}\nPath: {file_path}\nContent:\n{chunk}"
                            
                            success = vs.add_document(doc_id, chunk_with_context, metadata)
                            if success:
                                count += 1
                                if count % 100 == 0:
                                    logger.info(f"Ingested {count} documents...")
                            
                    except Exception as e:
                        logger.error(f"Error processing {file_path}: {e}")
                        
        logger.info(f"Ingestion complete. Total documents added: {count}")
        
        # Verify by querying
        logger.info("Verifying ingestion with a test query...")
        results = vs.query("biology genetics", top_k=1)
        if results:
            logger.info(f"Test query result: {results[:100]}...")
        else:
            logger.warning("Test query returned no results.")
            
    finally:
        # Restore cwd
        os.chdir(original_cwd)

if __name__ == "__main__":
    ingest_data()
